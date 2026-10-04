"""Privacy-first document processing pipeline for the prototype."""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytesseract
from PIL import Image
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

BASE_DIR = Path(__file__).resolve().parents[1]
TEMP_DIR = BASE_DIR / "temporary"
OUTPUT_DIR = BASE_DIR / "outputs"
TOKEN_RE = re.compile(r"\[\[([A-Z]+(?:_[A-Z]+)*_\d{3})\]\]")
PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "PHONE": re.compile(r"(?<!\w)(?:\+?\d[\d .()\-]{7,}\d)(?!\w)"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "DATE_OF_BIRTH": re.compile(r"\b(?:DOB|date of birth)\s*:?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.I),
}

# Context labels make names and identifiers detectable even when the value itself
# has no recognizable format. Arabic labels are escaped to keep this file portable.
_NAME_LABELS = (
    r"full\s+name|recipient(?:\s+name)?|holder(?:\s+name)?|employee\s+name|"
    r"customer\s+name|applicant(?:\s+name)?|patient|name|"
    r"\u0627\u0644\u0627\u0633\u0645|"
    r"\u0627\u0633\u0645\s+\u0627\u0644\u0645\u0633\u062a\u0644\u0645|"
    r"\u0627\u0633\u0645\s+\u0627\u0644\u0645\u0648\u0638\u0641|"
    r"\u0627\u0633\u0645\s+\u062d\u0627\u0645\u0644|"
    r"\u0627\u0644\u0645\u0633\u062a\u0644\u0645|"
    r"\u0645\u0642\u062f\u0645\s+\u0627\u0644\u0637\u0644\u0628"
)
_FIELD_LABELS = re.compile(
    r"\s+(?:employee\s*(?:id|number|no\.?)|id|phone|mobile|email|department|"
    r"start\s+date|address|date\s+of\s+birth|dob)\s*[:#-]", re.I)
_PERSON_WORDS = re.compile(r"[\w\u0600-\u06ff][\w\u0600-\u06ff'’.-]*", re.UNICODE)
_ID_LABEL = re.compile(r"\b(?:employee\s*(?:id|number|no\.?))\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{4,})\b", re.I)


@dataclass
class Page:
    image: np.ndarray
    text: str
    words: list[dict[str, Any]]


def load_document(path: Path) -> list[Page]:
    """Rasterize PDF pages or load a supported image; OCR locally before any API call."""
    images: list[np.ndarray] = []
    if path.suffix.lower() == ".pdf":
        import fitz
        doc = fitz.open(path)
        try:
            for page in doc:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                images.append(cv2.cvtColor(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n), cv2.COLOR_RGB2BGR))
        finally:
            doc.close()
    else:
        with Image.open(path) as source:
            rgb = np.asarray(source.convert("RGB"))
            images.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    pages = []
    for image in images:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = []
        for i, value in enumerate(data["text"]):
            value = value.strip()
            if value:
                words.append({"text": value, "x": int(data["left"][i]), "y": int(data["top"][i]),
                              "w": int(data["width"][i]), "h": int(data["height"][i]),
                              "block": int(data["block_num"][i]), "line": int(data["line_num"][i])})
        pages.append(Page(image, " ".join(w["text"] for w in words), words))
    return pages


def _sensitive_spans(text: str) -> list[tuple[int, int, str, str]]:
    spans = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if kind == "PHONE" and re.search(
                    r"employee\s*(?:id|number|no\.?)\s*[:#-]\s*$",
                    text[max(0, match.start() - 48):match.start()], re.I):
                continue
            value = match.group(0)
            if kind == "PHONE" and len(re.sub(r"\D", "", value)) < 9:
                continue
            if kind == "CARD":
                digits = re.sub(r"\D", "", value)
                if not 13 <= len(digits) <= 19:
                    continue
            spans.append((match.start(), match.end(), kind, value))
    # Extract a name only when it follows an explicit person/recipient label.
    for label in re.finditer(rf"(?i)(?<!\w)(?:{_NAME_LABELS})\s*[:#-]\s*", text):
        start = label.end()
        stop = re.search(r"[,;|\n]|\s{2,}", text[start:])
        end = start + stop.start() if stop else len(text)
        next_field = _FIELD_LABELS.search(text, start, end)
        if next_field:
            end = next_field.start()
        candidate = text[start:end].strip()
        if TOKEN_RE.fullmatch(candidate):
            continue
        words = list(_PERSON_WORDS.finditer(candidate))
        if not words:
            continue
        # Keep at most five name-like words, excluding trailing form text.
        candidate_end = words[min(len(words), 5) - 1].end()
        name = candidate[:candidate_end].strip(" .:-")
        if name:
            name_start = start + len(text[start:end]) - len(text[start:end].lstrip())
            spans.append((name_start, name_start + len(name), "PERSON", name))
    # Capture labelled employee numbers, including values that are not phone-shaped.
    for match in _ID_LABEL.finditer(text):
        spans.append((match.start(1), match.end(1), "EMPLOYEE_ID", match.group(1)))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    selected = []
    for span in spans:
        if not selected or span[0] >= selected[-1][1]:
            selected.append(span)
    return selected


def detect_and_tokenize(text: str) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    spans = _sensitive_spans(text)
    counts: dict[str, int] = {}
    mapping, findings, out, cursor = {}, [], [], 0
    for start, end, kind, value in spans:
        counts[kind] = counts.get(kind, 0) + 1
        token = f"[[{kind}_{counts[kind]:03d}]]"
        out.extend((text[cursor:start], token))
        cursor = end
        mapping[token] = value
        findings.append({"token": token, "category": kind, "masked_value": f"{value[:2]}\\u2026" if len(value) > 2 else "\\u2022\\u2022"})
    out.append(text[cursor:])
    return "".join(out), mapping, findings


def _redact_visuals(pages: list[Page], mappings: dict[str, str]) -> tuple[list[str], bool]:
    """Black out and verify every OCR box holding detected sensitive text."""
    previews = []
    all_covered = True
    safe_dir = TEMP_DIR / uuid.uuid4().hex
    safe_dir.mkdir(parents=True, exist_ok=True)
    for index, page in enumerate(pages, 1):
        img = page.image.copy()
        lower = page.text.lower()
        redaction_mask = np.zeros(page.image.shape[:2], dtype=np.uint8)
        for value in mappings.values():
            needle = value.lower()
            offset = 0
            found = False
            while (pos := lower.find(needle, offset)) >= 0:
                found = True
                end = pos + len(needle)
                char_pos = 0
                selected = []
                for word in page.words:
                    begin, finish = char_pos, char_pos + len(word["text"])
                    if finish > pos and begin < end:
                        selected.append(word)
                    char_pos = finish + 1
                if not selected:
                    all_covered = False
                for word in selected:
                    x, y, w, h = word["x"], word["y"], word["w"], word["h"]
                    x0, y0 = max(0, x - 3), max(0, y - 3)
                    x1, y1 = min(img.shape[1], x + w + 3), min(img.shape[0], y + h + 3)
                    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), -1)
                    cv2.rectangle(redaction_mask, (x0, y0), (x1, y1), 255, -1)
                    all_covered = all_covered and bool(np.all(redaction_mask[y:y + h, x:x + w] == 255))
                offset = end
            # Every local token must correspond to text found and covered on at least one page.
            if not found and value in page.text:
                all_covered = False
        path = safe_dir / f"redacted-{index}.png"
        if not cv2.imwrite(str(path), img):
            raise ValueError("Could not create a privacy-sanitized preview")
        previews.append(f"/api/preview/{safe_dir.name}/{path.name}")
    # Verify that every unique detected value occurred in OCR text and has a covered box.
    combined = "\n".join(page.text for page in pages).lower()
    all_covered = all_covered and all(value.lower() in combined for value in mappings.values())
    return previews, all_covered


def verify_privacy(outgoing_payload: str, mapping: dict[str, str], visual_verified: bool = True) -> bool:
    """Check the exact model payload, required tokens, and local visual redaction result."""
    safe = outgoing_payload.casefold()
    if not visual_verified:
        return False
    if any(not value or value.casefold() in safe for value in mapping.values()):
        return False
    if any(token not in outgoing_payload for token in mapping):
        return False
    return not _sensitive_spans(outgoing_payload)


def _validate_json(candidate: str) -> dict[str, Any]:
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model did not return valid JSON")
        value = json.loads(candidate[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Model response must be a JSON object")
    return value


def build_gemini_payload(safe_text: str) -> str:
    """Build the complete outgoing text payload before privacy verification."""
    return ("Return only JSON with document_type, summary, and fields as an object. "
            "Preserve privacy tokens exactly.\n\n" + safe_text)


def call_gemini(verified_payload: str) -> tuple[dict[str, Any], str]:
    """Send only a previously verified payload; demo mode remains fully offline."""
    key = os.getenv("GEMINI_API_KEY")
    if os.getenv("DEMO_MODE", "true").lower() == "true" or not key:
        return {"document_type": "Demo document", "summary": "Demo extraction generated from privacy-filtered OCR text.",
                "fields": {"extracted_text": verified_payload.split("\n\n", 1)[-1][:1000]}}, "demo"
    from google import genai
    client = genai.Client(api_key=key)
    response = client.models.generate_content(model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        contents=verified_payload)
    return _validate_json(response.text or ""), "gemini"


def restore_tokens(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return TOKEN_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [restore_tokens(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: restore_tokens(item, mapping) for key, item in value.items()}
    return value


def prepare_review(result: dict[str, Any], findings: list[dict[str, str]], previews: list[str]) -> dict[str, Any]:
    return {"result": result, "findings": findings, "redacted_previews": previews,
            "review_required": True, "status": "pending"}


def process_file(path: Path) -> dict[str, Any]:
    TEMP_DIR.mkdir(exist_ok=True)
    pages = load_document(path)
    raw_text = "\n".join(page.text for page in pages)
    safe_text, mapping, findings = detect_and_tokenize(raw_text)
    previews, visual_verified = _redact_visuals(pages, mapping)
    payload = build_gemini_payload(safe_text)
    if not verify_privacy(payload, mapping, visual_verified):
        raise ValueError("Privacy verification failed. The document was not sent to external AI.")
    result, mode = call_gemini(payload)
    restored = restore_tokens(result, mapping)
    return {"review": prepare_review(restored, findings, previews), "privacy_verified": True,
            "mode": mode, "page_count": len(pages), "_token_map": mapping}


def export_excel(review: dict[str, Any], path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Extracted data"
    result = restore_tokens(review["result"], review.get("_token_map", {}))
    fields = result.get("fields", {})
    if isinstance(fields, list):  # Compatibility with the original demo response.
        fields = {str(item.get("label", f"field_{index + 1}")): item.get("value", "")
                  for index, item in enumerate(fields) if isinstance(item, dict)}
    if not isinstance(fields, dict):
        fields = {"fields": fields}
    headers = ["Document Type", "Summary", *[str(key) for key in fields]]
    sheet.append(headers)
    def cell_value(value: Any) -> Any:
        return json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else value
    sheet.append([cell_value(result.get("document_type", "")), cell_value(result.get("summary", "")),
                  *[cell_value(value) for value in fields.values()]])
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1B5945")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        values = [len(str(cell.value or "")) for cell in column]
        sheet.column_dimensions[column[0].column_letter].width = min(max(max(values, default=12) + 2, 14), 48)
    findings = workbook.create_sheet("Sensitive data")
    findings.append(["Token", "Category", "Masked value"])
    for item in review.get("findings", []):
        findings.append([item["token"], item["category"], item["masked_value"]])
    path.parent.mkdir(exist_ok=True)
    workbook.save(path)


def cleanup(path: Path | None = None) -> None:
    if path and path.exists():
        path.unlink(missing_ok=True)
    # Keep recent redacted previews accessible during the session; remove stale temp directories.
    if TEMP_DIR.exists():
        import time
        cutoff = time.time() - 24 * 60 * 60
        for child in TEMP_DIR.iterdir():
            try:
                if child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
            except OSError:
                pass
