"""Flask API and static UI for the document digitization prototype."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from backend import pipeline

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def public_job(job: dict) -> dict:
    """Never expose the local original-value token map through the API."""
    return {key: value for key, value in job.items() if not key.startswith("_")}


def create_app() -> Flask:
    load_dotenv(BASE_DIR / ".env")
    app = Flask(__name__, static_folder="frontend", static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH_MB", "20")) * 1024 * 1024

    @app.get("/")
    def index():
        return send_from_directory(BASE_DIR / "frontend", "index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "demo_mode": os.getenv("DEMO_MODE", "true").lower() == "true" or not os.getenv("GEMINI_API_KEY")})

    @app.post("/api/process")
    def process():
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify(error="Choose a PDF or image to upload."), 400
        filename = secure_filename(uploaded.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED:
            return jsonify(error="Supported formats: PDF, PNG, JPG, TIFF, BMP."), 415
        UPLOAD_DIR.mkdir(exist_ok=True)
        file_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
        uploaded.save(file_path)
        job_id = uuid.uuid4().hex
        with jobs_lock:
            jobs[job_id] = {"status": "processing"}
        try:
            response = pipeline.process_file(file_path)
            token_map = response.pop("_token_map", {})
            with jobs_lock:
                jobs[job_id] = {"status": "pending", **response, "_token_map": token_map}
            return jsonify({"job_id": job_id, **response}), 200
        except Exception as exc:
            with jobs_lock:
                jobs[job_id] = {"status": "failed", "error": str(exc)}
            return jsonify(error=str(exc), job_id=job_id), 422
        finally:
            pipeline.cleanup(file_path)

    @app.get("/api/review/<job_id>")
    def get_review(job_id: str):
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Review not found."), 404
            return jsonify(public_job(job))

    @app.post("/api/review/<job_id>")
    def update_review(job_id: str):
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in {"approve", "reject"}:
            return jsonify(error="Action must be approve or reject."), 400
        with jobs_lock:
            job = jobs.get(job_id)
            if not job or job.get("status") != "pending":
                return jsonify(error="Review not found or not ready."), 404
            if action == "reject":
                job["status"] = "rejected"
                job["review"]["status"] = "rejected"
                return jsonify(public_job(job))
            edits = body.get("result")
            if edits is not None:
                if not isinstance(edits, dict):
                    return jsonify(error="result must be a JSON object."), 400
                job["review"]["result"] = edits
            job["status"] = "approved"
            job["review"]["status"] = "approved"
            return jsonify(public_job(job))

    @app.get("/api/export/<job_id>")
    def export(job_id: str):
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Review not found."), 404
            if job.get("status") != "approved":
                return jsonify(error="Approve this review before exporting."), 409
            review = {**job["review"], "_token_map": job.get("_token_map", {})}
        path = OUTPUT_DIR / f"{job_id}.xlsx"
        pipeline.export_excel(review, path)
        return send_file(path, as_attachment=True, download_name="digitized-document.xlsx")

    @app.get("/api/preview/<folder>/<filename>")
    def preview(folder: str, filename: str):
        # Only serve generated redacted PNGs from a direct child of temporary/.
        if not folder.isalnum() or not filename.startswith("redacted-") or not filename.endswith(".png"):
            return jsonify(error="Preview not found."), 404
        path = pipeline.TEMP_DIR / folder / filename
        if not path.is_file():
            return jsonify(error="Preview not found."), 404
        return send_file(path, mimetype="image/png")

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(error="File exceeds the configured size limit."), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
