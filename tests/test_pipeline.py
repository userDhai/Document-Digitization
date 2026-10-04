"""Synthetic end-to-end checks for the local privacy and approval workflow."""
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
from app import create_app


SYNTHETIC_OCR = (
    "Name: Test Person Employee ID: 9999999999 Phone: 0500000000 "
    "Email: test@example.com Department: Human Resources"
)


class PrivacyPipelineTests(unittest.TestCase):
    def test_contextual_name_labels_include_english_and_arabic_forms(self):
        labels = ["Name", "Full Name", "Recipient", "Recipient Name", "Holder",
                  "Holder Name", "Employee Name", "Customer Name", "Applicant",
                  "Applicant Name", "\u0627\u0644\u0627\u0633\u0645",
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

    def test_synthetic_pii_is_tokenized_and_only_locally_mapped(self):
        safe, token_map, findings = pipeline.detect_and_tokenize(SYNTHETIC_OCR)
        self.assertEqual(len(findings), 4)
        for private_value in ("Test Person", "9999999999", "0500000000", "test@example.com"):
            self.assertNotIn(private_value, safe)
            self.assertIn(private_value, token_map.values())
        self.assertIn("[[PERSON_001]]", safe)
        self.assertIn("[[EMPLOYEE_ID_001]]", safe)
        self.assertEqual(pipeline.restore_tokens(safe, token_map), SYNTHETIC_OCR)

    def test_outgoing_gemini_payload_contains_tokens_only_and_verifies_fail_closed(self):
        safe, token_map, _ = pipeline.detect_and_tokenize(SYNTHETIC_OCR)
        payload = pipeline.build_gemini_payload(safe)
        self.assertTrue(pipeline.verify_privacy(payload, token_map, visual_verified=True))
        for private_value in token_map.values():
            self.assertNotIn(private_value, payload)
        self.assertIn("[[PERSON_001]]", payload)
        self.assertFalse(pipeline.verify_privacy(payload + " Test Person", token_map, True))
        self.assertFalse(pipeline.verify_privacy(payload, token_map, visual_verified=False))

    def test_process_sends_only_sanitized_payload_and_restores_fake_response_locally(self):
        safe, token_map, _ = pipeline.detect_and_tokenize(SYNTHETIC_OCR)
        image = np.full((60, 300, 3), 255, dtype=np.uint8)
        page = Page(image, SYNTHETIC_OCR, [])
        model_response = {
            "document_type": "employee_form",
            "summary": "Employee information form",
            "fields": {"name": "[[PERSON_001]]", "employee_id": "[[EMPLOYEE_ID_001]]",
                       "phone": "[[PHONE_001]]", "email": "[[EMAIL_001]]",
                       "department": "Human Resources"},
        }
        captured = {}

        def fake_gemini(payload):
            captured["payload"] = payload
            return model_response, "fake"

        with patch.object(pipeline, "load_document", return_value=[page]), \
             patch.object(pipeline, "_redact_visuals", return_value=(["/api/preview/fake/redacted-1.png"], True)), \
             patch.object(pipeline, "call_gemini", side_effect=fake_gemini):
            response = pipeline.process_file(Path("unused-synthetic.pdf"))

        for original in token_map.values():
            self.assertNotIn(original, captured["payload"])
        self.assertIn("[[PERSON_001]]", captured["payload"])
        self.assertEqual(response["review"]["result"]["fields"]["name"], "Test Person")
        self.assertEqual(response["review"]["result"]["fields"]["employee_id"], "9999999999")
        self.assertEqual(response["_token_map"]["[[PHONE_001]]"], "0500000000")

    def test_redacted_preview_covers_sensitive_word_boxes(self):
        image = np.full((50, 140, 3), 255, dtype=np.uint8)
        words = [
            {"text": "Name:", "x": 5, "y": 10, "w": 28, "h": 12},
            {"text": "Test", "x": 40, "y": 10, "w": 25, "h": 12},
            {"text": "Person", "x": 68, "y": 10, "w": 35, "h": 12},
        ]
        page = Page(image, "Name: Test Person", words)
        with tempfile.TemporaryDirectory(dir=pipeline.TEMP_DIR) as temp_root:
            old_temp = pipeline.TEMP_DIR
            try:
                pipeline.TEMP_DIR = Path(temp_root) / "temp"
                previews, verified = pipeline._redact_visuals([page], {"[[PERSON_001]]": "Test Person"})
                self.assertTrue(verified)
                saved = pipeline.TEMP_DIR / previews[0].split("/")[-2] / previews[0].split("/")[-1]
                redacted = cv2.imread(str(saved))
                self.assertTrue(np.all(redacted[10:22, 40:103] == 0))
            finally:
                pipeline.TEMP_DIR = old_temp

    def test_excel_uses_dynamic_columns_and_restores_tokens(self):
        review = {
            "result": {"document_type": "employee_form", "summary": "Employee information form",
                       "fields": {"name": "[[PERSON_001]]", "employee_id": "[[EMPLOYEE_ID_001]]",
                                  "phone": "[[PHONE_001]]", "department": "Human Resources",
                                  "metadata": {"source": "scan", "tags": ["approved", "2026"]}}},
            "_token_map": {"[[PERSON_001]]": "Test Person", "[[EMPLOYEE_ID_001]]": "9999999999",
                           "[[PHONE_001]]": "0500000000"},
        }
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "review.xlsx"
            pipeline.export_excel(review, destination)
            sheet = load_workbook(destination, data_only=True)["Extracted data"]
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

    def test_preview_ui_and_explicit_approval_gate(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        with patch("app.pipeline.process_file", return_value={
            "review": {"result": {"document_type": "employee_form", "summary": "Demo",
                                   "fields": {"name": "Test Person"}}, "findings": [],
                       "redacted_previews": ["/api/preview/fake/redacted-1.png"],
                       "review_required": True, "status": "pending"},
            "privacy_verified": True, "mode": "fake", "page_count": 1,
            "_token_map": {"[[PERSON_001]]": "Test Person"},
        }):
            uploaded = client.post("/api/process", data={"file": (BytesIO(b"synthetic"), "test.png")},
                                   content_type="multipart/form-data")
        self.assertEqual(uploaded.status_code, 200)
        job_id = uploaded.json["job_id"]
        self.assertNotIn("_token_map", uploaded.json)
        html = client.get("/").get_data(as_text=True)
        self.assertIn("PRIVACY-SANITIZED PREVIEW", html)
        self.assertLess(html.index("preview-wrap"), html.index("class=\"results\""))
        self.assertEqual(client.get(f"/api/export/{job_id}").status_code, 409)
        reviewer_edit = {"document_type": "employee_form", "summary": "Demo",
                         "fields": {"name": "[[PERSON_001]]"}}
        approved = client.post(f"/api/review/{job_id}",
                               json={"action": "approve", "result": reviewer_edit})
        self.assertEqual(approved.status_code, 200)
        self.assertNotIn("_token_map", approved.json)
        exported = client.get(f"/api/export/{job_id}")
        self.assertEqual(exported.status_code, 200)
        output_file = pipeline.OUTPUT_DIR / f"{job_id}.xlsx"
        self.assertTrue(output_file.exists())
        self.assertEqual(load_workbook(output_file, data_only=True)["Extracted data"]["C2"].value, "Test Person")
        output_file.unlink(missing_ok=True)
        self.assertEqual(client.post(f"/api/review/{job_id}", json={"action": "reject"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
