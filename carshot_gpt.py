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

PROMPT = (
    "Replace only the background with a realistic modern car dealership showroom. "
    "Keep the exact same car, angle, rims, body shape, paint color, reflections, "
    "headlights, windows, ride height, and all original details completely unchanged. "
    "Do not redesign or modify the vehicle in any way. Do not change the wheels. "
    "Do not change the grille. Do not change proportions. Keep OEM details exactly the same. "
    "Use soft natural dealership lighting, clean grey tiled floor, large showroom windows, "
    "realistic shadows and reflections. "
    "Make it look like a professional car listing photo for AutoScout24 or dealership inventory. "
    "Ultra realistic, photorealistic, seamless background integration."
)


def prepare_image(file_bytes):
    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    img.thumbnail((1024, 1024), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def process_with_gpt(image_buf):
    image_buf.seek(0)
    response = client.images.edit(
        model="gpt-image-1",
        image=image_buf,
        prompt=PROMPT,
        n=1,
        size="1024x1024",
    )
    item = response.data[0]
    if getattr(item, "b64_json", None):
        return base64.b64decode(item.b64_json)
    import requests
    return requests.get(item.url).content


@app.route("/")
def index():
    return send_file(str(BASE_DIR / "carshot_final.html"))


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
            buf = prepare_image(f.read())
            result = process_with_gpt(buf)
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

        return jsonify({"download_url": "/download/" + job_id, "status": "done"})

    except Exception as e:
        return jsonify({"error": "Verarbeitungsfehler: " + str(e)}), 500


@app.route("/download/<job_id>")
def download(job_id):
    job = JOBS.get(job_id)
    if not job:
        return "Nicht gefunden", 404
    filepath = JOBS_DIR / job_id / job["file"]
    if not filepath.exists():
        return "Datei fehlt", 404
    mimetype = "application/zip" if filepath.suffix == ".zip" else "image/png"
    return send_file(str(filepath), as_attachment=True, download_name=filepath.name, mimetype=mimetype)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
