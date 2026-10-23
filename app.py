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
    """Keep token maps and raw OCR review rows behind the local server boundary."""
    private_keys = {"ocr_items", "approved_transmissions"}
    return {key: value for key, value in job.items()
            if not key.startswith("_") and key not in private_keys}


def gemini_error_details(error: pipeline.GeminiRequestError) -> tuple[str, str]:
    """Translate safe provider status fields into a useful, non-sensitive message."""
    code = error.status_code
    status = (error.status or "").upper()
    if code in {401, 403} or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
        return "gemini_auth", "Gemini rejected the API key or its permissions. Check the key's access and try again."
    if code == 404 or status == "NOT_FOUND":
        return "gemini_model", "Gemini could not find the configured model. Check GEMINI_MODEL and try again."
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return "gemini_quota", "Gemini's rate limit or quota was reached. Wait a little, then retry."
    if code in {408, 504} or status == "DEADLINE_EXCEEDED":
        return "gemini_timeout", "Gemini took too long to respond. Retry the extraction."
    if (isinstance(code, int) and code >= 500) or status in {"UNAVAILABLE", "INTERNAL"}:
        return "gemini_unavailable", "Gemini is temporarily unavailable. Retry in a moment."
    if code == 400 or status == "INVALID_ARGUMENT":
        return "gemini_request", "Gemini rejected the request format. Check the model and request settings."
    return "gemini_connection", "The app could not complete its Gemini request. Check the server connection and retry."


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
            ocr_cache = local.pop("_ocr_cache", [])
            visual_verified = local.pop("_visual_verified", False)
            image_paths = local.pop("_sanitized_image_paths", [])
            image_hashes = local.pop("_sanitized_image_hashes", [])
            verified = local.get("privacy_verified") is True
            metadata = {
                "file_name": filename,
                "file_type": suffix.lstrip(".").upper(),
                "page_count": local["page_count"],
                "processing_status": "LOCAL_REVIEW_READY" if verified else "PRIVACY_REVIEW_REQUIRED",
                "ocr_status": "COMPLETED",
                "privacy_status": "PASSED" if verified else "BLOCKED",
                "sensitive_field_count": len(local["findings"]),
                "sensitive_field_types": sorted({item["category"] for item in local["findings"]}),
                "manual_mask_count": len(local.get("manual_masks", [])),
            }
            job = {"status": "awaiting_ai_approval" if verified else "privacy_blocked", "metadata": metadata,
                   "privacy_verified": verified, "visual_verified": visual_verified,
                   "review_required": True, **local,
                   "ai_result": None, "review_result": None,
                   "_token_map": token_map, "_ocr_cache": ocr_cache,
                   "_source_path": str(file_path),
                   "_sanitized_image_paths": image_paths, "_sanitized_image_hashes": image_hashes}
            with jobs_lock:
                jobs[job_id] = job
            return jsonify({"job_id": job_id, **public_job(job)}), 200
        except Exception as exc:
            privacy_blocked = "Privacy verification failed" in str(exc)
            if privacy_blocked:
                error = "Privacy verification failed. The document was not sent to external AI."
            elif isinstance(exc, pipeline.OCRConfigurationError):
                error = str(exc)
            else:
                error = "Local OCR or privacy processing failed. Check the document and try again."
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
        masks = body.get("manual_masks", body.get("masks"))
        if not isinstance(masks, list):
            return jsonify(error="manual_masks must be a list of page coordinates."), 400
        keep_pages = body.get("keep_pages")
        disabled = body.get("disabled_automatic_mask_ids", [])
        overrides = body.get("automatic_mask_overrides", [])
        ocr_items = body.get("ocr_items")
        include_confirmed = body.get("include_confirmed") is True
        output_language = body.get("output_language", "en")
        if (keep_pages is not None and not isinstance(keep_pages, list) or
                not isinstance(disabled, list) or not isinstance(overrides, list) or
                (ocr_items is not None and not isinstance(ocr_items, list)) or
                output_language not in {"en", "ar"}):
            return jsonify(error="Page and automatic mask selections are invalid."), 400
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Document review not found."), 404
            if job.get("status") not in {"awaiting_ai_approval", "privacy_blocked", "blocked"}:
                return jsonify(error="Manual redaction is only available before AI approval."), 409
            source_path = job.get("_source_path")
            ocr_cache = job.get("_ocr_cache", [])
            prior_status = job.get("status")
            job["status"] = "mask_processing"
        try:
            local = pipeline.prepare_document(Path(source_path), masks, keep_pages, disabled, overrides,
                                              ocr_items, include_confirmed, output_language,
                                              ocr_cache=ocr_cache)
        except ValueError as exc:
            if "Explicit confirmation is required" in str(exc):
                with jobs_lock:
                    if job.get("status") == "mask_processing":
                        job["status"] = prior_status
                return jsonify(error=str(exc), requires_transmission_confirmation=True), 409
            if "Privacy verification failed" in str(exc):
                with jobs_lock:
                    job["status"] = "blocked"
                    job["privacy_verified"] = False
                    job["error"] = "Privacy verification failed. The document was not sent to external AI."
                    job["metadata"]["privacy_status"] = "BLOCKED"
                    job["metadata"]["processing_status"] = "BLOCKED"
                return jsonify(error="Privacy verification failed. The document was not sent to external AI.",
                               status="blocked"), 422
            with jobs_lock:
                if job.get("status") == "mask_processing":
                    job["status"] = prior_status
            return jsonify(error=str(exc) or "The local OCR/privacy selections are invalid."), 400
        except Exception as exc:
            app.logger.warning("Manual redaction processing failed (exception_type=%s)", type(exc).__name__)
            with jobs_lock:
                if job.get("status") == "mask_processing":
                    job["status"] = prior_status
            return jsonify(error="Manual redaction could not be applied. Please try again."), 422
        token_map = local.pop("_token_map", {})
        ocr_cache = local.pop("_ocr_cache", ocr_cache)
        visual_verified = local.pop("_visual_verified", False)
        image_paths = local.pop("_sanitized_image_paths", [])
        image_hashes = local.pop("_sanitized_image_hashes", [])
        approved_transmissions = local.pop("_approved_transmissions", [])
        with jobs_lock:
            if job.get("status") != "mask_processing":
                return jsonify(error="Document review is no longer available."), 409
            job.update(local)
            job["_token_map"] = token_map
            job["_ocr_cache"] = ocr_cache
            job["_sanitized_image_paths"] = image_paths
            job["_sanitized_image_hashes"] = image_hashes
            job["_approved_transmissions"] = approved_transmissions
            job["visual_verified"] = visual_verified
            verified = local.get("privacy_verified") is True
            job["privacy_verified"] = verified
            job["metadata"]["privacy_status"] = "PASSED" if verified else "BLOCKED"
            job["metadata"]["processing_status"] = "LOCAL_REVIEW_READY" if verified else "PRIVACY_REVIEW_REQUIRED"
            job["metadata"]["sensitive_field_count"] = len(local["findings"])
            job["metadata"]["page_count"] = local["page_count"]
            job["metadata"]["sensitive_field_types"] = sorted({item["category"] for item in local["findings"]})
            job["metadata"]["manual_mask_count"] = len(local.get("manual_masks", []))
            job["status"] = "awaiting_ai_approval" if verified else "privacy_blocked"
            if not verified:
                job["error"] = "Privacy check needs attention. Review your masks; Continue to AI will proceed with your approval."
            else:
                job.pop("error", None)
                job.pop("error_code", None)
        return jsonify(public_job(job)), 200

    @app.post("/api/ai/<job_id>")
    def send_to_ai(job_id: str):
        approval = request.get_json(silent=True) or {}
        if approval.get("approved") is not True:
            return jsonify(error="Explicitly approve the verified document before AI processing."), 409
        output_language = approval.get("output_language", "en")
        if output_language not in {"en", "ar"}:
            return jsonify(error="Choose Arabic or English output."), 400
        # Claim the one-shot approval so double-clicks cannot issue duplicate AI calls.
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Document review not found."), 404
            if job.get("status") not in {"awaiting_ai_approval", "privacy_blocked", "blocked"}:
                return jsonify(error="This document is not ready for AI approval."), 409
            if not job.get("sanitized_payload") or not job.get("_sanitized_image_paths"):
                return jsonify(error="Local processing data is unavailable. Upload the document again."), 409
            job["status"] = "ai_processing"
            payload = job["sanitized_payload"]
            token_map = job.get("_token_map", {})
            visual_verified = job.get("visual_verified", False)
            image_paths = job.get("_sanitized_image_paths", [])
            image_hashes = job.get("_sanitized_image_hashes", [])
            manual_masks = job.get("manual_masks", [])
            page_numbers = job.get("_page_numbers", [])
            payload = pipeline.build_gemini_payload(job.get("safe_ocr_text", ""), output_language)
            approved_transmissions = job.get("_approved_transmissions", [])
            # Local processing already checked this payload and redacted image set.
            # The language choice changes only output labels; call_gemini still checks
            # every sanitized file's hash immediately before constructing the request.
            verified = job.get("privacy_verified") is True
            job["privacy_verified"] = verified
            job["metadata"]["privacy_status"] = "PASSED" if verified else "USER_APPROVED"
            job["metadata"]["privacy_override"] = not verified
            job["sanitized_payload"] = payload
            job["output_language"] = output_language
        try:
            result, mode = pipeline.extract_document(payload, token_map, visual_verified,
                                                     image_paths, image_hashes, manual_masks, page_numbers,
                                                     approved_transmissions, human_approved=True)
        except Exception as exc:
            error_code = "api_error"
            if isinstance(exc, pipeline.GeminiConfigurationError):
                error_code, message = "configuration_error", str(exc)
            elif isinstance(exc, pipeline.GeminiResponseError):
                error_code, message = "invalid_response", str(exc)
            elif isinstance(exc, pipeline.GeminiRequestError):
                error_code, message = gemini_error_details(exc)
            else:
                message = "AI processing failed unexpectedly. Please retry."
            with jobs_lock:
                job["status"] = "ai_failed"
                job["error"] = message
                job["error_code"] = error_code
                job["metadata"]["processing_status"] = "AI_FAILED"
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
            return jsonify(error=message, error_code=error_code, status=job["status"]), 502
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
                verified = pipeline.verify_privacy(job["sanitized_payload"], job.get("_token_map", {}),
                                                   job.get("visual_verified", False),
                                                   job.get("_sanitized_image_paths", []),
                                                   job.get("_sanitized_image_hashes", []),
                                                   job.get("manual_masks", []), job.get("_page_numbers", []),
                                                   job.get("_approved_transmissions", []))
                job["status"] = "awaiting_ai_approval" if verified else "privacy_blocked"
                job.pop("error", None)
                job["metadata"]["processing_status"] = "LOCAL_REVIEW_READY"
                job["metadata"]["privacy_status"] = "PASSED" if verified else "BLOCKED"
                job["privacy_verified"] = verified
                job["review_result"] = None
                return jsonify(public_job(job))
            if action == "reject":
                if job.get("status") not in {"awaiting_ai_approval", "awaiting_final_approval"}:
                    return jsonify(error="This document cannot be rejected in its current state."), 409
                job["status"] = "rejected"
                job["metadata"]["processing_status"] = "REJECTED"
                job.pop("error", None)
                return jsonify(public_job(job))
            if job.get("status") not in {"awaiting_final_approval", "approved"}:
                return jsonify(error="Final approval is not available yet."), 409
            output_language = body.get("output_language", job.get("output_language", "en"))
            if output_language not in {"en", "ar"}:
                return jsonify(error="Choose Arabic or English output."), 400
            edits = body.get("result")
            export_fields = body.get("export_fields")
            if edits is not None:
                if not isinstance(edits, dict):
                    return jsonify(error="result must be a JSON object."), 400
                job["review_result"] = edits
            job["output_language"] = output_language
            if export_fields is not None:
                current_fields = job.get("review_result", {}).get("fields", {})
                if isinstance(current_fields, list):
                    current_keys = {str(item.get("label", f"field_{index + 1}")) for index, item in enumerate(current_fields)
                                    if isinstance(item, dict)}
                elif isinstance(current_fields, dict):
                    current_keys = {str(key) for key in current_fields}
                else:
                    current_keys = set()
                if (not isinstance(export_fields, list) or
                        any(not isinstance(key, str) or key not in current_keys for key in export_fields) or
                        len(set(export_fields)) != len(export_fields)):
                    return jsonify(error="Export field selections are invalid."), 400
                job["export_fields"] = export_fields
            job["status"] = "approved"
            job["metadata"]["processing_status"] = "APPROVED_FOR_EXPORT"
            return jsonify(public_job(job))

    @app.get("/api/export/<job_id>")
    def export(job_id: str):
        export_format = request.args.get("format", "excel").lower()
        if export_format not in {"excel", "word"}:
            return jsonify(error="Choose Excel or Word export."), 400
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                return jsonify(error="Review not found."), 404
            if job.get("status") != "approved":
                return jsonify(error="Complete final approval before exporting."), 409
            review = {"result": job["review_result"], "findings": job["findings"],
                      "output_language": job.get("output_language", "en"),
                      "export_fields": job.get("export_fields"),
                      # This private mapping is used only to prepare the approved local workbook.
                      "_token_map": job.get("_token_map", {})}
        extension = "docx" if export_format == "word" else "xlsx"
        path = OUTPUT_DIR / f"{job_id}.{extension}"
        try:
            (pipeline.export_word if export_format == "word" else pipeline.export_excel)(review, path)
        except Exception as exc:
            app.logger.error("%s export failed (%s)", export_format.title(), type(exc).__name__)
            return jsonify(error=f"{export_format.title()} export failed. Please try again."), 500
        return send_file(path, as_attachment=True, download_name=f"digitized-document.{extension}")

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
