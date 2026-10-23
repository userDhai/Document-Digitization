# ClearDoc: document digitization prototype

A small Flask app for OCR, local sensitive-data masking, structured extraction, human review, and Excel or Word export. The interface and output labels can be switched between English and Arabic. **Sensitive information is technically redacted/tokenized locally before cloud AI processing.** This prototype does not claim production-grade privacy or regulatory compliance.

## Trust boundary and review flow

**Local trusted processing:** OCR, contextual name/address and identifier detection, token mapping, visual redaction, privacy verification, token restoration, human review, and Excel export run on the Flask host. The original-value token map stays in server-side job state and is not returned by the API.

**Cloud AI processing:** Gemini receives only the verified, tokenized OCR text and generated sanitized page images. The original upload and original PII values are never included in the Gemini request. If an original sensitive value remains in the outgoing text, a token is missing, a manual mask is not blacked out, or a sanitized image changes after verification, processing stops before Gemini is called. Set `DEMO_MODE=true` explicitly for offline mock extraction; with demo mode off, missing Gemini configuration is reported clearly.

The user workflow has three steps: upload, visual mask review, then editable extraction results and Excel or Word export. The visual review has a canvas editor for multiple masks, selection, moving, resizing, undo, deletion, page removal, and reordering. Every edit rebuilds OCR and privacy verification from the original local document, and keeps the visible page position. OCR text and token maps remain behind the server privacy boundary; collapsed OCR diagnostics show recognized text with detected sensitive spans tokenized.

Uploaded originals remain in the local `uploads/` directory and are never sent to Gemini. Reviewers can edit extracted fields and choose Arabic or English interface and output labels. Document values stay exactly in their source language. Excel and Word exports restore known tokens locally; Excel uses columns and Word uses a two-column table.

## Run locally

1. Use Python 3.10 or newer and install Tesseract OCR on the machine with both English (`eng`) and Arabic (`ara`) traineddata files. Tesseract is an external system dependency used by `pytesseract`; the default Windows executable is `C:\Program Files\Tesseract-OCR\tesseract.exe`, configurable with `TESSERACT_CMD`. The default OCR languages are `eng+ara`; set `TESSERACT_LANG` to adjust the language order while retaining both models. PDF pages are rendered at 300 DPI by default (`PDF_RENDER_DPI` can be set from 150 to 600).
2. Create and activate a virtual environment, then install `requirements.txt`.
3. Copy `.env.example` to `.env`. Leave `DEMO_MODE=true` for offline development, or set it to `false` and add `GEMINI_API_KEY` to use Gemini. The default model is `gemini-3.6-flash` with low thinking for faster extraction (`GEMINI_THINKING_LEVEL` also accepts `medium` or `high`). Gemini receives JPEG-encoded sanitized pages capped at 1400 pixels on the long edge; the local preview and source remain full resolution. Do not commit `.env`.
4. Run `python app.py` and open http://127.0.0.1:5000.

The default upload limit is 20 MB. Change `MAX_CONTENT_LENGTH_MB` to adjust it. The app accepts PDF and common raster image formats. Tesseract must have both language models installed; processing reports a clear local error if either is unavailable. OCR recognizes English and Arabic together at the original page resolution and keeps Tesseract's block, line, and word coordinates for mask placement. Name detection uses explicit name labels and a conservative known-name check for unlabelled lines; international phone numbers are detected with a country-neutral format rule. Reviews and local token maps are held in memory, so restarting the server clears them. Approved `.xlsx` and `.docx` files are saved under `outputs/`.

## Checks

Run the synthetic privacy and workflow checks with `python -m unittest discover -s tests`. Run `python -m py_compile app.py backend/pipeline.py` for syntax validation. OCR requires the Tesseract executable and language data installed on the host. The local name and phone rules are heuristics rather than a general named-entity recognizer, so low-quality OCR or unusual names and number formats may be missed; inspect every preview and add manual masks when needed. Gemini failures distinguish configuration, request, and invalid-response errors. Technical logs include exception type and safe HTTP status fields, never provider exception messages, OCR text, or token values.
