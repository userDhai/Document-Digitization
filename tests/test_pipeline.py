"""Synthetic checks for the two human approval gates and privacy boundary."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from openpyxl import load_workbook

from backend import pipeline
from backend.pipeline import Page
from app import create_app, jobs

SYNTHETIC_OCR = (
    "Name: Test Person Employee ID: 9999999999 Phone: 0500000000 "
    "Email: test@example.com Address: 123 Test Road, Riyadh Department: Human Resources"
)


def local_result():
    safe_text, mapping, findings = pipeline.detect_and_tokenize(SYNTHETIC_OCR)
    return {
        "safe_ocr_text": safe_text,
        "sanitized_payload": pipeline.build_gemini_payload(safe_text),
        "redacted_previews": ["/api/preview/fake/redacted-1.png"],
        "findings": findings,
        "page_count": 1,
        "_token_map": mapping,
        "_visual_verified": True,
    }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.job_ids = []

    def tearDown(self):
        for job_id in self.job_ids:
            job = jobs.pop(job_id, {})
            source = job.get("_source_path")
            if source:
                Path(source).unlink(missing_ok=True)

    def upload_local(self, prepared=None):
        with patch("app.pipeline.prepare_document", return_value=prepared or local_result()):
            response = self.client.post(
                "/api/process", data={"file": (BytesIO(b"synthetic image"), "employee.png")},
                content_type="multipart/form-data")
        if response.is_json and response.json.get("job_id"):
            self.job_ids.append(response.json["job_id"])
        return response

    def test_contextual_english_and_arabic_names(self):
        labels = ["Name", "Full Name", "First Name", "Given Name", "Middle Name",
                  "Last Name", "Family Name", "Surname", "Recipient", "Recipient Name", "Holder",
                  "Holder Name", "Employee Name", "Customer Name", "Applicant",
                  "Applicant Name", "\u0627\u0644\u0627\u0633\u0645", "\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0623\u0648\u0644",
                  "\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0623\u0648\u0633\u0637",
                  "\u0627\u0644\u0627\u0633\u0645 \u0627\u0644\u0623\u062e\u064a\u0631",
                  "\u0627\u0633\u0645 \u0627\u0644\u0639\u0627\u0626\u0644\u0629", "\u0627\u0644\u0644\u0642\u0628",
                  "\u0627\u0633\u0645 \u0627\u0644\u0645\u0633\u062a\u0644\u0645",
                  "\u0627\u0633\u0645 \u0627\u0644\u0645\u0648\u0638\u0641",
                  "\u0627\u0633\u0645 \u062d\u0627\u0645\u0644",
                  "\u0627\u0644\u0645\u0633\u062a\u0644\u0645",
                  "\u0645\u0642\u062f\u0645 \u0627\u0644\u0637\u0644\u0628"]
        for label in labels:
            with self.subTest(label=label):
                safe, mapping, _ = pipeline.detect_and_tokenize(f"{label}: Test Person")
                self.assertEqual(mapping, {"[[PERSON_001]]": "Test Person"})
                self.assertEqual(safe, f"{label}: [[PERSON_001]]")

    def test_local_ocr_text_is_tokenized_and_originals_stay_in_private_map(self):
        safe, mapping, findings = pipeline.detect_and_tokenize(SYNTHETIC_OCR)
        self.assertEqual(len(findings), 5)
        for private_value in ("Test Person", "9999999999", "0500000000", "test@example.com",
                              "123 Test Road, Riyadh"):
            self.assertNotIn(private_value, safe)
            self.assertIn(private_value, mapping.values())
        self.assertIn("[[PERSON_001]]", safe)
        self.assertIn("[[EMPLOYEE_ID_001]]", safe)
        self.assertEqual(pipeline.restore_tokens(safe, mapping), SYNTHETIC_OCR)

    def test_addresses_and_other_labeled_identifiers_are_masked(self):
        text = "Address: 123 Test Road, Riyadh National ID: 1234567890 Passport Number: AB1234567"
        safe, mapping, _ = pipeline.detect_and_tokenize(text)
        self.assertEqual(mapping["[[ADDRESS_001]]"], "123 Test Road, Riyadh")
        self.assertEqual(mapping["[[NATIONAL_ID_001]]"], "1234567890")
        self.assertEqual(mapping["[[PASSPORT_001]]"], "AB1234567")
        self.assertNotIn("123 Test Road", safe)
        self.assertNotIn("1234567890", safe)
        self.assertNotIn("AB1234567", safe)

    def test_payload_verification_checks_tokens_values_and_visual_flag(self):
        prepared = local_result()
        mapping = prepared["_token_map"]
        payload = prepared["sanitized_payload"]
        self.assertTrue(pipeline.verify_privacy(payload, mapping, True))
        for original in mapping.values():
            self.assertNotIn(original, payload)
        self.assertIn("[[PERSON_001]]", payload)
        self.assertFalse(pipeline.verify_privacy(payload + " Test Person", mapping, True))
        self.assertFalse(pipeline.verify_privacy(payload, mapping, False))
        with self.assertRaisesRegex(ValueError, "not sent to external AI"):
            pipeline.extract_document("Name: Test Person", mapping, True)

    def test_preparation_stops_at_local_boundary_and_ai_result_keeps_tokens(self):
        page = Page(np.full((60, 300, 3), 255, dtype=np.uint8), SYNTHETIC_OCR, [])
        captured = {}

        def fake_ai(payload, _mapping, _visual_verified):
            captured["payload"] = payload
            return {"document_type": "employee_form", "summary": "Test form",
                    "fields": {"name": "[[PERSON_001]]", "phone": "[[PHONE_001]]"}}, "fake"

        with patch.object(pipeline, "load_document", return_value=[page]), \
             patch.object(pipeline, "_redact_visuals", return_value=(["/api/preview/fake/redacted-1.png"], True)), \
             patch.object(pipeline, "call_gemini", side_effect=fake_ai) as model:
            prepared = pipeline.prepare_document(Path("synthetic.pdf"))
            model.assert_not_called()
            result, mode = pipeline.extract_document(prepared["sanitized_payload"],
                                                      prepared["_token_map"], prepared["_visual_verified"])
        for original in prepared["_token_map"].values():
            self.assertNotIn(original, captured["payload"])
        self.assertIn("[[PERSON_001]]", captured["payload"])
        self.assertEqual(result["fields"]["name"], "[[PERSON_001]]")
        self.assertEqual(mode, "fake")

    def test_redacted_preview_verifies_and_blacks_out_sensitive_boxes(self):
        image = np.full((50, 140, 3), 255, dtype=np.uint8)
        words = [{"text": "Name:", "x": 5, "y": 10, "w": 28, "h": 12},
                 {"text": "Test", "x": 40, "y": 10, "w": 25, "h": 12},
                 {"text": "Person", "x": 68, "y": 10, "w": 35, "h": 12}]
        with tempfile.TemporaryDirectory(dir=pipeline.TEMP_DIR) as temporary_root:
            old_temp = pipeline.TEMP_DIR
            try:
                pipeline.TEMP_DIR = Path(temporary_root) / "generated"
                previews, verified = pipeline._redact_visuals(
                    [Page(image, "Name: Test Person", words)], {"[[PERSON_001]]": "Test Person"})
                self.assertTrue(verified)
                destination = pipeline.TEMP_DIR / previews[0].split("/")[-2] / previews[0].split("/")[-1]
                redacted = cv2.imread(str(destination))
                self.assertTrue(np.all(redacted[10:22, 40:103] == 0))
            finally:
                pipeline.TEMP_DIR = old_temp

    def test_excel_has_dynamic_columns_nested_values_and_restores_tokens(self):
        review = {"result": {"document_type": "employee_form", "summary": "Test form",
                             "fields": {"name": "[[PERSON_001]]", "employee_id": "[[EMPLOYEE_ID_001]]",
                                        "phone": "[[PHONE_001]]", "department": "Human Resources",
                                        "metadata": {"source": "scan", "tags": ["approved", "2026"]}}},
                  "_token_map": {"[[PERSON_001]]": "Test Person",
                                 "[[EMPLOYEE_ID_001]]": "9999999999",
                                 "[[PHONE_001]]": "0500000000"}}
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "review.xlsx"
            pipeline.export_excel(review, destination)
            workbook = load_workbook(destination, data_only=True)
            sheet = workbook["Extracted data"]
            headers = [cell.value for cell in sheet[1]]
            row = [cell.value for cell in sheet[2]]
            values = dict(zip(headers, row))
            self.assertEqual(headers[:2], ["Document Type", "Summary"])
            self.assertEqual(headers[2:], ["name", "employee_id", "phone", "department", "metadata"])
            self.assertEqual(values["name"], "Test Person")
            self.assertEqual(values["employee_id"], "9999999999")
            self.assertEqual(values["phone"], "0500000000")
            self.assertIn('"source": "scan"', values["metadata"])
            self.assertFalse(any(isinstance(value, str) and value.startswith('{"document_type"') for value in row))
            workbook.close()

    def test_api_requires_pre_ai_approval_then_final_approval_before_export(self):
        response = self.upload_local()
        self.assertEqual(response.status_code, 200)
        job_id = response.json["job_id"]
        self.assertEqual(response.json["status"], "awaiting_ai_approval")
        self.assertEqual(response.json["metadata"]["privacy_status"], "PASSED")
        self.assertNotIn("_token_map", response.json)
        self.assertEqual(self.client.get(f"/api/export/{job_id}").status_code, 409)
        with patch("app.pipeline.extract_document") as premature_ai:
            self.assertEqual(self.client.post(f"/api/ai/{job_id}", json={}).status_code, 409)
            premature_ai.assert_not_called()
        with patch("app.pipeline.extract_document", return_value=(
                {"document_type": "employee_form", "summary": "Test form",
                 "fields": {"name": "[[PERSON_001]]", "department": "Human Resources"}}, "fake")) as ai:
            ai_response = self.client.post(f"/api/ai/{job_id}", json={})
        self.assertEqual(ai_response.status_code, 200)
        self.assertEqual(ai.call_count, 1)
        self.assertIn("[[PERSON_001]]", ai.call_args.args[0])
        self.assertNotIn("Test Person", ai.call_args.args[0])
        self.assertEqual(ai_response.json["status"], "awaiting_final_approval")
        self.assertIn("[[PERSON_001]]", ai_response.json["ai_result"]["fields"]["name"])
        self.assertEqual(self.client.get(f"/api/export/{job_id}").status_code, 409)
        edited = {"document_type": "employee_form", "summary": "Approved test form",
                  "fields": {"name": "[[PERSON_001]]", "department": "People"}}
        approval = self.client.post(f"/api/review/{job_id}", json={"action": "approve", "result": edited})
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.json["status"], "approved")
        self.assertNotIn("_token_map", approval.json)
        export_response = self.client.get(f"/api/export/{job_id}")
        self.assertEqual(export_response.status_code, 200)
        output_path = pipeline.OUTPUT_DIR / f"{job_id}.xlsx"
        workbook = load_workbook(output_path, data_only=True)
        self.assertEqual(workbook["Extracted data"]["C2"].value, "Test Person")
        self.assertEqual(workbook["Extracted data"]["D2"].value, "People")
        workbook.close()
        output_path.unlink(missing_ok=True)

    def test_reject_retains_local_state_and_retry_requires_local_review_again(self):
        uploaded = self.upload_local()
        job_id = uploaded.json["job_id"]
        original_path = Path(jobs[job_id]["_source_path"])
        self.assertTrue(original_path.exists())
        rejected = self.client.post(f"/api/review/{job_id}", json={"action": "reject"})
        self.assertEqual(rejected.json["status"], "rejected")
        self.assertTrue(original_path.exists())
        with patch("app.pipeline.extract_document") as ai:
            self.assertEqual(self.client.post(f"/api/ai/{job_id}", json={}).status_code, 409)
            ai.assert_not_called()
        retry = self.client.post(f"/api/review/{job_id}", json={"action": "retry"})
        self.assertEqual(retry.json["status"], "awaiting_ai_approval")
        self.assertTrue(retry.json["safe_ocr_text"])

    def test_privacy_failure_blocks_job_and_ai_route(self):
        with patch("app.pipeline.prepare_document", side_effect=ValueError(
                "Privacy verification failed. The document was not sent to external AI.")):
            blocked = self.upload_local()
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(blocked.json["metadata"]["privacy_status"], "BLOCKED")
        self.assertEqual(blocked.json["error"], "Privacy verification failed. The document was not sent to external AI.")
        with patch("app.pipeline.extract_document") as ai:
            response = self.client.post(f"/api/ai/{blocked.json['job_id']}", json={})
            self.assertEqual(response.status_code, 409)
            ai.assert_not_called()

    def test_ai_endpoint_rechecks_the_exact_payload_before_any_model_call(self):
        uploaded = self.upload_local()
        job_id = uploaded.json["job_id"]
        jobs[job_id]["sanitized_payload"] += " Test Person"
        with patch("app.pipeline.call_gemini") as model:
            response = self.client.post(f"/api/ai/{job_id}", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn("Privacy verification failed", response.json["error"])
        model.assert_not_called()

    def test_frontend_exposes_preview_payload_and_both_approval_actions(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Privacy-sanitized document preview", html)
        self.assertIn("Approve &amp; send to AI", html)
        self.assertIn("Sanitized OCR text", html)
        self.assertIn("Approve &amp; export Excel", html)
        self.assertIn("id=\"fields-body\"", html)


if __name__ == "__main__":
    unittest.main()
