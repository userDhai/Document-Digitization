"""Privacy-first document processing pipeline for the prototype."""
from __future__ import annotations

import hashlib
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

DEFAULT_TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

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
    r"full\s+name|first\s+name|given\s+name|middle\s+name|last\s+name|family\s+name|surname|"
    r"recipient(?:\s+name)?|holder(?:\s+name)?|employee\s+name|"
    r"customer\s+name|applicant(?:\s+name)?|patient(?:\s+name)?|name|"
    r"\u0627\u0644\u0627\u0633\u0645\s+(?:\u0627\u0644\u0623\u0648\u0644|\u0627\u0644\u0623\u0648\u0633\u0637|\u0627\u0644\u0623\u062e\u064a\u0631)|"
    r"\u0627\u0633\u0645\s+\u0627\u0644\u0639\u0627\u0626\u0644\u0629|\u0627\u0644\u0644\u0642\u0628|"
    r"\u0627\u0644\u0627\u0633\u0645|"
    r"\u0627\u0633\u0645\s+\u0627\u0644\u0645\u0633\u062a\u0644\u0645|"
    r"\u0627\u0633\u0645\s+\u0627\u0644\u0645\u0648\u0638\u0641|"
    r"\u0627\u0633\u0645\s+\u062d\u0627\u0645\u0644|"
    r"\u0627\u0644\u0645\u0633\u062a\u0644\u0645|"
    r"\u0645\u0642\u062f\u0645\s+\u0627\u0644\u0637\u0644\u0628"
)
_FIELD_LABELS = re.compile(
    r"\s+(?:first\s+name|given\s+name|middle\s+name|last\s+name|family\s+name|surname|"
    r"\u0627\u0644\u0627\u0633\u0645\s+(?:\u0627\u0644\u0623\u0648\u0644|\u0627\u0644\u0623\u0648\u0633\u0637|\u0627\u0644\u0623\u062e\u064a\u0631)|"
    r"\u0627\u0633\u0645\s+\u0627\u0644\u0639\u0627\u0626\u0644\u0629|\u0627\u0644\u0644\u0642\u0628|"
    r"employee\s*(?:id|number|no\.?)|national\s*(?:id|identity)|identity\s*(?:number|no\.?)|"
    r"passport(?:\s*(?:number|no\.?))?|id|phone|mobile|email|department|city|state|zip|postal\s+code|"
    r"start\s+date|date|address|date\s+of\s+birth|dob|gender|title|salary|"
    r"designation|position|nationality|passport|company|signature)\s*[:#-]", re.I)
_PERSON_WORDS = re.compile(r"[\w\u0600-\u06ff][\w\u0600-\u06ff'.-]*", re.UNICODE)
_ID_LABEL = re.compile(r"\b(?:employee\s*(?:id|number|no\.?))\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{4,})\b", re.I)
_GENERIC_ID_LABEL = re.compile(r"\bID\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{4,})\b", re.I)
_NATIONAL_ID_LABEL = re.compile(
    r"\b(?:national\s*(?:id|identity)|identity\s*(?:number|no\.?))\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{4,})\b", re.I)
_PASSPORT_LABEL = re.compile(r"\bpassport(?:\s*(?:number|no\.?))?\s*[:#-]\s*([A-Z0-9][A-Z0-9-]{4,})\b", re.I)
_ADDRESS_LABELS = (
    r"home\s+address|street\s+address|mailing\s+address|residential\s+address|"
    r"billing\s+address|address|\u0627\u0644\u0639\u0646\u0648\u0627\u0646|"
    r"\u0639\u0646\u0648\u0627\u0646\s+\u0627\u0644\u0633\u0643\u0646"
)


@dataclass
class Page:
    image: np.ndarray
    text: str
    words: list[dict[str, Any]]


class GeminiConfigurationError(RuntimeError):
    pass


class GeminiRequestError(RuntimeError):
    def __init__(self, exception_type: str, status_code: Any = None, status: Any = None):
        # Provider exception messages can echo request data, so retain safe fields only.
        self.exception_type = exception_type
        self.status_code = status_code if isinstance(status_code, (int, str)) else None
        self.status = status if isinstance(status, str) else None
        super().__init__("Gemini request failed")


class GeminiResponseError(ValueError):
    pass


def load_document(path: Path) -> list[Page]:
    """Rasterize PDF pages or load a supported image; OCR locally before any API call."""
    # Resolve this at processing time so values loaded from the project's .env
    # are honored even when the pipeline module was imported earlier.
    pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD", DEFAULT_TESSERACT_CMD)
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
                    r"(?:employee\s*(?:id|number|no\.?)|national\s*(?:id|identity)|"
                    r"identity\s*(?:number|no\.?)|passport(?:\s*(?:number|no\.?))?|id)\s*[:#-]\s*$",
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
    for match in _GENERIC_ID_LABEL.finditer(text):
        if re.search(r"national\s*$", text[max(0, match.start() - 40):match.start()], re.I):
            continue
        spans.append((match.start(1), match.end(1), "ID", match.group(1)))
    for pattern, category in ((_NATIONAL_ID_LABEL, "NATIONAL_ID"), (_PASSPORT_LABEL, "PASSPORT")):
        for match in pattern.finditer(text):
            spans.append((match.start(1), match.end(1), category, match.group(1)))
    # Address values have no reliable standalone format, so detect them by field label.
    for label in re.finditer(rf"(?i)(?<!\w)(?:{_ADDRESS_LABELS})\s*[:#-]\s*", text):
        start = label.end()
        stop = re.search(r"[;|\n]|\s{2,}", text[start:])
        end = start + stop.start() if stop else len(text)
        next_field = _FIELD_LABELS.search(text, start, end)
        if next_field:
            end = next_field.start()
        address = text[start:end].strip(" ,;:-")
        if address and not TOKEN_RE.fullmatch(address):
            leading = len(text[start:end]) - len(text[start:end].lstrip())
            spans.append((start + leading, start + leading + len(address), "ADDRESS", address))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    selected = []
    for span in spans:
        if not selected or span[0] >= selected[-1][1]:
            selected.append(span)
    return selected


def detect_and_tokenize(text: str, extra_spans: list[tuple[int, int, str, str]] | None = None
                        ) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    spans = [*_sensitive_spans(text), *(extra_spans or [])]
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))
    selected_spans = []
    for span in spans:
        if 0 <= span[0] < span[1] <= len(text) and (not selected_spans or span[0] >= selected_spans[-1][1]):
            selected_spans.append(span)
    counts: dict[str, int] = {}
    mapping, findings, out, cursor = {}, [], [], 0
    for start, end, kind, value in selected_spans:
        counts[kind] = counts.get(kind, 0) + 1
        token = f"[[{kind}_{counts[kind]:03d}]]"
        out.extend((text[cursor:start], token))
        cursor = end
        mapping[token] = value
        findings.append({"token": token, "category": kind, "masked_value": "Detected and tokenized locally"})
    out.append(text[cursor:])
    return "".join(out), mapping, findings


def _redact_visuals(pages: list[Page], mappings: dict[str, str],
                    manual_masks: list[dict[str, int]] | None = None) -> tuple[list[str], bool]:
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
        for mask in manual_masks or []:
            if mask["page"] != index - 1:
                continue
            x, y = mask["x"], mask["y"]
            x1 = min(img.shape[1], x + mask["width"])
            y1 = min(img.shape[0], y + mask["height"])
            if x < 0 or y < 0 or x1 <= x or y1 <= y:
                all_covered = False
                continue
            cv2.rectangle(img, (x, y), (x1, y1), (0, 0, 0), -1)
            redaction_mask[y:y1, x:x1] = 255
            all_covered = all_covered and bool(np.all(img[y:y1, x:x1] == 0))
        path = safe_dir / f"redacted-{index}.png"
        if not cv2.imwrite(str(path), img):
            raise ValueError("Privacy verification failed. The document was not sent to external AI.")
        previews.append(f"/api/preview/{safe_dir.name}/{path.name}")
    # Verify that every unique detected value occurred in OCR text and has a covered box.
    combined = "\n".join(page.text for page in pages).lower()
    all_covered = all_covered and all(value.lower() in combined for value in mappings.values())
    return previews, all_covered


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_privacy(outgoing_payload: str, mapping: dict[str, str], visual_verified: bool = True,
                   preview_paths: list[str] | None = None, preview_hashes: list[str] | None = None,
                   manual_masks: list[dict[str, int]] | None = None) -> bool:
    """Check tokenized text and integrity/coverage of the exact sanitized images."""
    safe = outgoing_payload.casefold()
    if not visual_verified:
        return False
    if any(not value or value.casefold() in safe for value in mapping.values()):
        return False
    if any(token not in outgoing_payload for token in mapping):
        return False
    if _sensitive_spans(outgoing_payload):
        return False
    if preview_paths is not None:
        if not preview_paths or (preview_hashes is not None and len(preview_hashes) != len(preview_paths)):
            return False
        images = []
        for index, item in enumerate(preview_paths):
            path = Path(item)
            if not path.is_file():
                return False
            if preview_hashes is not None and _file_sha256(path) != preview_hashes[index]:
                return False
            image = cv2.imread(str(path))
            if image is None:
                return False
            images.append(image)
        for mask in manual_masks or []:
            page = mask["page"]
            if not 0 <= page < len(images):
                return False
            image = images[page]
            x, y = mask["x"], mask["y"]
            x1, y1 = x + mask["width"], y + mask["height"]
            if x < 0 or y < 0 or x1 > image.shape[1] or y1 > image.shape[0]:
                return False
            if not np.all(image[y:y1, x:x1] == 0):
                return False
    elif manual_masks:
        return False
    return True


def _validate_json(candidate: str) -> dict[str, Any]:
    candidate = (candidate or "").strip()
    if not candidate:
        raise GeminiResponseError("Gemini returned an empty response.")
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise GeminiResponseError("Gemini returned a response that could not be parsed.") from None
        try:
            value = json.loads(candidate[start:end + 1])
        except json.JSONDecodeError:
            raise GeminiResponseError("Gemini returned a response that could not be parsed.") from None
    if not isinstance(value, dict):
        raise GeminiResponseError("Gemini returned data that does not match the expected extraction format.")
    if not isinstance(value.get("document_type"), str) or not isinstance(value.get("summary"), str):
        raise GeminiResponseError("Gemini returned data that does not match the expected extraction format.")
    if not isinstance(value.get("fields"), (dict, list)):
        raise GeminiResponseError("Gemini returned data that does not match the expected extraction format.")
    return value


def build_gemini_payload(safe_text: str) -> str:
    """Build the complete outgoing text payload before privacy verification."""
    return ("Return only JSON with document_type, summary, and fields as an object. "
            "Preserve privacy tokens exactly.\n\n" + safe_text)


def call_gemini(verified_payload: str, mapping: dict[str, str], visual_verified: bool,
                image_paths: list[str] | None = None, image_hashes: list[str] | None = None,
                manual_masks: list[dict[str, int]] | None = None) -> tuple[dict[str, Any], str]:
    """Send only verified tokenized OCR and generated sanitized page images."""
    if not verify_privacy(verified_payload, mapping, visual_verified, image_paths, image_hashes, manual_masks):
        raise ValueError("Privacy verification failed. The document was not sent to external AI.")
    key = os.getenv("GEMINI_API_KEY")
    if os.getenv("DEMO_MODE", "false").lower() == "true":
        return {"document_type": "Demo document", "summary": "Demo extraction generated from privacy-filtered OCR text.",
                "fields": {"extracted_text": verified_payload.split("\n\n", 1)[-1][:1000]}}, "demo"
    if not key:
        raise GeminiConfigurationError("Gemini API key is not configured.")
    try:
        from google import genai
    except ImportError:
        raise GeminiConfigurationError("Gemini SDK is not installed. Install project requirements.") from None
    try:
        client = genai.Client(api_key=key)
        images = []
        for image_path in image_paths or []:
            with Image.open(image_path) as source:
                images.append(source.convert("RGB"))
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[verified_payload, *images],
            config={"response_mime_type": "application/json"},
        )
    except Exception as exc:
        raise GeminiRequestError(type(exc).__name__, getattr(exc, "code", None), getattr(exc, "status", None)) from None
    return _validate_json(response.text or ""), "gemini"


def restore_tokens(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return TOKEN_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [restore_tokens(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: restore_tokens(item, mapping) for key, item in value.items()}
    return value


def _manual_mask_spans(pages: list[Page], masks: list[dict[str, Any]]) -> list[tuple[int, int, str, str]]:
    spans = []
    page_offset = 0
    for page_index, page in enumerate(pages):
        for mask in (item for item in masks if item["page"] == page_index):
            x0, y0 = mask["x"], mask["y"]
            x1, y1 = x0 + mask["width"], y0 + mask["height"]
            char_position = 0
            selected = []
            for word in page.words:
                begin, end = char_position, char_position + len(word["text"])
                wx, wy, ww, wh = word["x"], word["y"], word["w"], word["h"]
                if wx < x1 and wx + ww > x0 and wy < y1 and wy + wh > y0:
                    selected.append((begin, end))
                char_position = end + 1
            if selected:
                start, end = selected[0][0], selected[-1][1]
                spans.append((page_offset + start, page_offset + end, "PERSON_MANUAL",
                              page.text[start:end]))
        page_offset += len(page.text) + 1
    return spans


def _normalize_manual_masks(pages: list[Page], masks: list[dict[str, Any]] | None
                            ) -> list[dict[str, int]]:
    normalized = []
    for mask in masks or []:
        if not isinstance(mask, dict):
            raise ValueError("Manual mask coordinates are invalid.")
        page, x, y, width, height = (mask.get(name) for name in ("page", "x", "y", "width", "height"))
        if isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < len(pages):
            raise ValueError("Manual mask page is invalid.")
        coords = (x, y, width, height)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in coords):
            raise ValueError("Manual mask coordinates are invalid.")
        x, y, width, height = (round(value) for value in coords)
        image_height, image_width = pages[page].image.shape[:2]
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > image_width or y + height > image_height:
            raise ValueError("Manual mask must stay within the document page.")
        normalized.append({"page": page, "x": x, "y": y, "width": width, "height": height})
    return normalized


def prepare_document(path: Path, manual_masks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run local OCR, automatic/manual masking, tokenization, and verification."""
    TEMP_DIR.mkdir(exist_ok=True)
    pages = load_document(path)
    masks = _normalize_manual_masks(pages, manual_masks)
    raw_text = "\n".join(page.text for page in pages)
    manual_spans = _manual_mask_spans(pages, masks)
    safe_text, mapping, findings = detect_and_tokenize(raw_text, manual_spans)
    previews, visual_verified = _redact_visuals(pages, mapping, masks)
    preview_paths = [str(TEMP_DIR / Path(url).parts[-2] / Path(url).name) for url in previews]
    preview_hashes = [_file_sha256(Path(item)) for item in preview_paths]
    payload = build_gemini_payload(safe_text)
    if not verify_privacy(payload, mapping, visual_verified, preview_paths, preview_hashes, masks):
        raise ValueError("Privacy verification failed. The document was not sent to external AI.")
    return {"safe_ocr_text": safe_text, "sanitized_payload": payload,
            "redacted_previews": previews, "findings": findings,
            "page_count": len(pages), "manual_masks": masks,
            "page_dimensions": [{"width": page.image.shape[1], "height": page.image.shape[0]} for page in pages],
            "_token_map": mapping, "_visual_verified": visual_verified,
            "_sanitized_image_paths": preview_paths, "_sanitized_image_hashes": preview_hashes}


def extract_document(payload: str, mapping: dict[str, str], visual_verified: bool,
                     image_paths: list[str] | None = None, image_hashes: list[str] | None = None,
                     manual_masks: list[dict[str, int]] | None = None) -> tuple[dict[str, Any], str]:
    """Call Gemini only after rechecking the exact text and sanitized image files."""
    if not verify_privacy(payload, mapping, visual_verified, image_paths, image_hashes, manual_masks):
        raise ValueError("Privacy verification failed. The document was not sent to external AI.")
    result, mode = call_gemini(payload, mapping, visual_verified, image_paths, image_hashes, manual_masks)
    if not result or not isinstance(result, dict):
        raise ValueError("AI returned an empty or invalid extraction")
    return result, mode


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
