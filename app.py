"""Flask API and static UI for the document digitization prototype."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from backend import pipeline

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
        return jsonify({"status": "ok", "demo_mode": os.getenv("DEMO_MODE", "false").lower() == "true"})

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
        job_id = uuid.uuid4().hex
        file_path = UPLOAD_DIR / f"{job_id}{suffix}"
        uploaded.save(file_path)
        try:
            local = pipeline.prepare_document(file_path)
            token_map = local.pop("_token_map", {})
            visual_verified = local.pop("_visual_verified", False)
            image_paths = local.pop("_sanitized_image_paths", [])
            image_hashes = local.pop("_sanitized_image_hashes", [])
            metadata = {
                "file_name": filename,
                "file_type": suffix.lstrip(".").upper(),
                "page_count": local["page_count"],
                "processing_status": "LOCAL_REVIEW_READY",
                "ocr_status": "COMPLETED",
                "privacy_status": "PASSED",
                "sensitive_field_count": len(local["findings"]),
                "sensitive_field_types": sorted({item["category"] for item in local["findings"]}),
                "manual_mask_count": len(local.get("manual_masks", [])),
            }
            job = {"status": "awaiting_ai_approval", "metadata": metadata,
                   "privacy_verified": True, "visual_verified": visual_verified,
                   "review_required": True, **local,
                   "ai_result": None, "review_result": None,
                   "_token_map": token_map, "_source_path": str(file_path),
                   "_sanitized_image_paths": image_paths, "_sanitized_image_hashes": image_hashes}
            with jobs_lock:
                jobs[job_id] = job
            return jsonify({"job_id": job_id, **public_job(job)}), 200
        except Exception as exc:
            privacy_blocked = "Privacy verification failed" in str(exc)
            error = ("Privacy verification failed. The document was not sent to external AI."
                     if privacy_blocked else "Local OCR or privacy processing failed. Check the document and try again.")
            metadata = {"file_name": filename, "file_type": suffix.lstrip(".").upper(),
                        "processing_status": "BLOCKED",
                        "ocr_status": "COMPLETED" if privacy_blocked else "FAILED",
                        "privacy_status": "BLOCKED"}
            with jobs_lock:
                jobs[job_id] = {"status": "blocked", "metadata": metadata,
                                "privacy_verified": False, "error": error,
                                "_source_path": str(file_path)}
            app.logger.warning("Local processing blocked (%s)", type(exc).__name__)
            return jsonify({"job_id": job_id, **public_job(jobs[job_id])}), 422
        finally:
            pipeline.cleanup()

    @app.post("/api/manual-masks/<job_id>")
    def update_manual_masks(job_id: str):
        body = request.get_json(silent=True) or {}
        masks = body.get("masks")
        if not isinstance(masks, list):
            return jsonify(error="masks must be a list of page coordinates."), 400
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Document review not found."), 404
            if job.get("status") != "awaiting_ai_approval":
                return jsonify(error="Manual redaction is only available before AI approval."), 409
            source_path = job.get("_source_path")
            job["status"] = "mask_processing"
        try:
            local = pipeline.prepare_document(Path(source_path), masks)
        except ValueError as exc:
            if "Privacy verification failed" in str(exc):
                with jobs_lock:
                    job["status"] = "blocked"
                    job["privacy_verified"] = False
                    job["metadata"]["privacy_status"] = "BLOCKED"
                    job["metadata"]["processing_status"] = "BLOCKED"
                return jsonify(error="Privacy verification failed. The document was not sent to external AI.",
                               status="blocked"), 422
            with jobs_lock:
                if job.get("status") == "mask_processing":
                    job["status"] = "awaiting_ai_approval"
            return jsonify(error="Manual mask coordinates are invalid."), 400
        except Exception as exc:
            app.logger.warning("Manual redaction processing failed (exception_type=%s)", type(exc).__name__)
            with jobs_lock:
                if job.get("status") == "mask_processing":
                    job["status"] = "awaiting_ai_approval"
            return jsonify(error="Manual redaction could not be applied. Please try again."), 422
        token_map = local.pop("_token_map", {})
        visual_verified = local.pop("_visual_verified", False)
        image_paths = local.pop("_sanitized_image_paths", [])
        image_hashes = local.pop("_sanitized_image_hashes", [])
        with jobs_lock:
            if job.get("status") != "mask_processing":
                return jsonify(error="Document review is no longer available."), 409
            job.update(local)
            job["_token_map"] = token_map
            job["_sanitized_image_paths"] = image_paths
            job["_sanitized_image_hashes"] = image_hashes
            job["visual_verified"] = visual_verified
            job["privacy_verified"] = visual_verified
            job["metadata"]["privacy_status"] = "PASSED" if visual_verified else "BLOCKED"
            job["metadata"]["processing_status"] = "LOCAL_REVIEW_READY" if visual_verified else "BLOCKED"
            job["metadata"]["sensitive_field_count"] = len(local["findings"])
            job["metadata"]["sensitive_field_types"] = sorted({item["category"] for item in local["findings"]})
            job["metadata"]["manual_mask_count"] = len(local.get("manual_masks", []))
            if not visual_verified:
                job["status"] = "blocked"
                job["error"] = "Privacy verification failed. The document was not sent to external AI."
            else:
                job["status"] = "awaiting_ai_approval"
                job.pop("error", None)
        return jsonify(public_job(job)), 200 if visual_verified else 422

    @app.post("/api/ai/<job_id>")
    def send_to_ai(job_id: str):
        # Claim the one-shot approval so double-clicks cannot issue duplicate AI calls.
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Document review not found."), 404
            if job.get("status") != "awaiting_ai_approval":
                return jsonify(error="This document is not ready for AI approval."), 409
            if job.get("metadata", {}).get("privacy_status") != "PASSED":
                return jsonify(error="Privacy verification failed. The document was not sent to external AI."), 409
            job["status"] = "ai_processing"
            payload = job["sanitized_payload"]
            token_map = job.get("_token_map", {})
            visual_verified = job.get("visual_verified", False)
            image_paths = job.get("_sanitized_image_paths", [])
            image_hashes = job.get("_sanitized_image_hashes", [])
            manual_masks = job.get("manual_masks", [])
        try:
            result, mode = pipeline.extract_document(payload, token_map, visual_verified,
                                                     image_paths, image_hashes, manual_masks)
        except Exception as exc:
            privacy_blocked = "Privacy verification failed" in str(exc)
            error_code = "privacy_block" if privacy_blocked else "api_error"
            if privacy_blocked:
                message = "Privacy verification failed. The document was not sent to external AI."
            elif isinstance(exc, pipeline.GeminiConfigurationError):
                error_code, message = "configuration_error", str(exc)
            elif isinstance(exc, pipeline.GeminiResponseError):
                error_code, message = "invalid_response", str(exc)
            elif isinstance(exc, pipeline.GeminiRequestError):
                error_code, message = "api_error", "Gemini request failed. Please retry."
            else:
                message = "AI processing failed unexpectedly. Please retry."
            with jobs_lock:
                job["status"] = "blocked" if privacy_blocked else "ai_failed"
                job["error"] = message
                job["error_code"] = error_code
                job["metadata"]["processing_status"] = "BLOCKED" if privacy_blocked else "AI_FAILED"
                if privacy_blocked:
                    job["metadata"]["privacy_status"] = "BLOCKED"
                    job["privacy_verified"] = False
            if isinstance(exc, pipeline.GeminiRequestError):
                app.logger.error("Gemini request failed (exception_type=%s status_code=%s status=%s)",
                                 exc.exception_type, exc.status_code, exc.status)
            elif isinstance(exc, pipeline.GeminiConfigurationError):
                app.logger.error("Gemini configuration error (%s)", error_code)
            elif isinstance(exc, pipeline.GeminiResponseError):
                app.logger.error("Gemini response rejected (%s)", error_code)
            else:
                app.logger.error("AI processing failed (exception_type=%s category=%s)",
                                 type(exc).__name__, error_code)
            return jsonify(error=message, error_code=error_code, status=job["status"]), 422 if privacy_blocked else 502
        with jobs_lock:
            job["status"] = "awaiting_final_approval"
            job["ai_mode"] = mode
            job["ai_result"] = result
            job["review_result"] = result
            job["metadata"]["processing_status"] = "AI_EXTRACTION_READY"
        return jsonify(public_job(job)), 200

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
        if action not in {"approve", "reject", "retry"}:
            return jsonify(error="Action must be approve, reject, or retry."), 400
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Review not found."), 404
            if action == "retry" and job.get("status") in {"rejected", "ai_failed"}:
                if not job.get("sanitized_payload"):
                    return jsonify(error="Local processing data is unavailable. Upload the document again."), 409
                if not pipeline.verify_privacy(job["sanitized_payload"], job.get("_token_map", {}),
                                               job.get("visual_verified", False)):
                    job["status"] = "blocked"
                    job["privacy_verified"] = False
                    job["metadata"]["privacy_status"] = "BLOCKED"
                    job["metadata"]["processing_status"] = "BLOCKED"
                    job["error"] = "Privacy verification failed. The document was not sent to external AI."
                    return jsonify(public_job(job)), 409
                job["status"] = "awaiting_ai_approval"
                job.pop("error", None)
                job["metadata"]["processing_status"] = "LOCAL_REVIEW_READY"
                job["metadata"]["privacy_status"] = "PASSED"
                job["privacy_verified"] = True
                job["review_result"] = None
                return jsonify(public_job(job))
            if action == "reject":
                if job.get("status") not in {"awaiting_ai_approval", "awaiting_final_approval"}:
                    return jsonify(error="This document cannot be rejected in its current state."), 409
                job["status"] = "rejected"
                job["metadata"]["processing_status"] = "REJECTED"
                job.pop("error", None)
                return jsonify(public_job(job))
            if job.get("status") != "awaiting_final_approval":
                return jsonify(error="Final approval is not available yet."), 409
            edits = body.get("result")
            if edits is not None:
                if not isinstance(edits, dict):
                    return jsonify(error="result must be a JSON object."), 400
                job["review_result"] = edits
            job["status"] = "approved"
            job["metadata"]["processing_status"] = "APPROVED_FOR_EXPORT"
            return jsonify(public_job(job))

    @app.get("/api/export/<job_id>")
    def export(job_id: str):
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Review not found."), 404
            if job.get("status") != "approved":
                return jsonify(error="Complete final approval before exporting."), 409
            review = {"result": job["review_result"], "findings": job["findings"],
                      "_token_map": job.get("_token_map", {})}
        path = OUTPUT_DIR / f"{job_id}.xlsx"
        try:
            pipeline.export_excel(review, path)
        except Exception as exc:
            app.logger.error("Excel export failed (%s)", type(exc).__name__)
            return jsonify(error="Excel export failed. Please try again."), 500
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
