import os
import io
import uuid
import base64
import zipfile
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from openai import OpenAI
from PIL import Image

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

JOBS = {}
BASE_DIR = Path(__file__).parent
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)


def prepare_image(file_bytes):
    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    img.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def analyze_car(img_b64):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + img_b64}
                    },
                    {
                        "type": "text",
                        "text": "Describe this car precisely: make, model, trim, exact color and paint finish, wheel design, body style, camera angle. Only describe the car, not the background."
                    }
                ]
            }
        ],
        max_tokens=400
    )
    return response.choices[0].message.content


def generate_showroom(car_description):
    prompt = (
        "Professional dealership showroom photograph. "
        "Car: " + car_description + ". "
        "Keep the exact car shape, proportions, color, rims, and all details 100% realistic and unchanged. "
        "Replace the background with a modern high-end car showroom: "
        "clean architecture, large glass windows with soft natural daylight from the side, "
        "minimalistic design, polished floor with subtle car reflections. "
        "Soft diffused lighting, realistic reflections on car body, glossy premium finish, no harsh shadows. "
        "Ultra sharp, HDR, professional automotive photography style. "
        "Luxury car advertisement look. No people, no other vehicles, no text."
    )
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        n=1,
        size="1024x1024",
        quality="hd",
        response_format="b64_json"
    )
    return base64.b64decode(response.data[0].b64_json)


@app.route("/")
def index():
    html_path = BASE_DIR / "carshot_final.html"
    return send_file(str(html_path))


@app.route("/process", methods=["POST"])
def process():
    order_type = request.form.get("type", "single")
    files = request.files.getlist("images")

    if not files or not files[0].filename:
        return jsonify({"error": "Kein Bild hochgeladen"}), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir()

    try:
        result_files = []

        for i, f in enumerate(files, 1):
            img_bytes = f.read()
            buf = prepare_image(img_bytes)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            car_desc = analyze_car(img_b64)
            result = generate_showroom(car_desc)

            out = job_dir / ("carshot_" + str(i) + ".png")
            out.write_bytes(result)
            result_files.append(out)

            if order_type == "single":
                break

        if len(result_files) == 1:
            JOBS[job_id] = {"file": result_files[0].name}
        else:
            zip_path = job_dir / "carshot_bundle.zip"
            with zipfile.ZipFile(str(zip_path), "w") as zf:
                for rf in result_files:
                    zf.write(str(rf), rf.name)
            JOBS[job_id] = {"file": "carshot_bundle.zip"}

        return jsonify({
            "download_url": "/download/" + job_id,
            "status": "done"
        })

    except Exception as e:
        return jsonify({"error": "Verarbeitungsfehler: " + str(e)}), 500


@app.route("/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job:
        return "Nicht gefunden", 404

    job_dir = JOBS_DIR / job_id
    filepath = job_dir / job["file"]

    if not filepath.exists():
        return "Datei fehlt", 404

    mimetype = "application/zip" if filepath.suffix == ".zip" else "image/png"
    return send_file(str(filepath), as_attachment=True, download_name=filepath.name, mimetype=mimetype)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
