import io
import re
import uuid
import zipfile
import csv
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template, request, send_file, flash, redirect, url_for, abort

app = Flask(__name__)
app.secret_key = "change-me-in-production"

BATCH_SIZE = 1000
MAX_WORKERS = 10
BITBUCKET_RAW = "https://bitbucket.org/eads004/{submodule}/raw/master/{filename}"
ID_PATTERN = re.compile(r"^[A-Za-z]\d{3,}$")

# Temporary in-memory store for multi-batch jobs: {uid: [[id, ...], [id, ...], ...]}
batch_store = {}


def parse_ids(stream):
    reader = csv.reader(stream)
    ids = []
    for row in reader:
        if row:
            val = row[0].strip()
            if ID_PATTERN.match(val):
                ids.append(val.upper())
    return ids


def fetch_text(text_id):
    submodule = text_id[:3]
    filename = f"{text_id}.xml"
    url = BITBUCKET_RAW.format(submodule=submodule, filename=filename)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return filename, resp.content


def build_zip(text_ids):
    fetched = {}
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_text, tid): tid for tid in text_ids}
        for future in as_completed(futures):
            tid = futures[future]
            try:
                filename, content = future.result()
                fetched[filename] = content
            except requests.HTTPError as e:
                errors.append(f"{tid}: HTTP {e.response.status_code}")
            except requests.RequestException as e:
                errors.append(f"{tid}: {e}")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in fetched.items():
            zf.writestr(filename, content)
        if errors:
            error_lines = ["The following IDs could not be downloaded:", ""] + errors
            zf.writestr("errors.txt", "\n".join(error_lines))

    zip_buffer.seek(0)
    return zip_buffer


@app.route("/")
def index():
    return render_template("index.html", batch_size=BATCH_SIZE)


@app.route("/download", methods=["POST"])
def download():
    is_fetch = request.headers.get("X-Requested-With") == "fetch"

    def error(msg):
        if is_fetch:
            return jsonify({"error": msg}), 400
        flash(msg, "error")
        return redirect(url_for("index"))

    if "csv_file" not in request.files or request.files["csv_file"].filename == "":
        return error("Please select a CSV file.")

    csv_file = request.files["csv_file"]
    stream = io.StringIO(csv_file.stream.read().decode("utf-8-sig"))
    text_ids = parse_ids(stream)

    if not text_ids:
        return error(
            "No valid text IDs found in the CSV. "
            "IDs should start with a letter followed by digits (e.g. A00001)."
        )

    batches = [text_ids[i:i + BATCH_SIZE] for i in range(0, len(text_ids), BATCH_SIZE)]

    if len(batches) == 1:
        return send_file(
            build_zip(batches[0]),
            mimetype="application/zip",
            as_attachment=True,
            download_name="eebo_texts.zip",
        )

    uid = str(uuid.uuid4())
    batch_store[uid] = batches
    if is_fetch:
        return jsonify({"redirect": url_for("batches_page", uid=uid)})
    return redirect(url_for("batches_page", uid=uid))


@app.route("/batches/<uid>")
def batches_page(uid):
    if uid not in batch_store:
        abort(404)
    batches = batch_store[uid]
    return render_template(
        "batches.html",
        uid=uid,
        batch_count=len(batches),
        total_ids=sum(len(b) for b in batches),
        batch_size=BATCH_SIZE,
    )


@app.route("/batches/<uid>/<int:batch_num>")
def download_batch(uid, batch_num):
    if uid not in batch_store:
        abort(404)
    batches = batch_store[uid]
    if batch_num < 0 or batch_num >= len(batches):
        abort(404)
    return send_file(
        build_zip(batches[batch_num]),
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"eebo_texts_batch_{batch_num + 1}.zip",
    )


if __name__ == "__main__":
    app.run(debug=True)
