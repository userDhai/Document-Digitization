# ClearDoc: document digitization prototype

A small Flask app for OCR, local sensitive-data masking, structured extraction, human review, and Excel export. **Sensitive information is technically redacted/tokenized locally before cloud AI processing.** This prototype does not claim production-grade privacy or regulatory compliance.

## Trust boundary and review flow

**Local trusted processing:** OCR, contextual name and identifier detection, token mapping, visual redaction, privacy verification, token restoration, human review, and Excel export run on the Flask host. The original-value token map stays in server-side job state and is not returned by the API.

**Cloud AI processing:** Gemini receives only the verified, tokenized OCR text. The original image and original PII values are never included in the Gemini request. If a sensitive value is not found in the outgoing text, its token is missing, or the corresponding OCR boxes are not covered in the generated preview, processing stops before Gemini is called. Demo mode is enabled by default and makes no network request.

The workflow requires explicit reviewer approval before export. Reviewers can edit the extracted JSON locally. Excel export restores known tokens locally and creates dynamic columns for document type, summary, and each key in `fields`.

## Run locally

1. Use Python 3.10 or newer and install Tesseract OCR on the machine. Tesseract is an external system dependency used by `pytesseract`.
2. Create and activate a virtual environment, then install `requirements.txt`.
3. Copy `.env.example` to `.env`. Leave `DEMO_MODE=true` for offline development, or set it to `false` and add `GEMINI_API_KEY` to use Gemini. Do not commit `.env`.
4. Run `python app.py` and open http://127.0.0.1:5000.

The default upload limit is 20 MB. Change `MAX_CONTENT_LENGTH_MB` to adjust it. The app accepts PDF and common raster image formats. Reviews and local token maps are held in memory, so restarting the server clears them. Approved `.xlsx` files are saved under `outputs/`.

## Checks

Run the synthetic privacy and workflow checks with `python -m unittest discover -s tests`. Run `python -m py_compile app.py backend/pipeline.py` for syntax validation. OCR requires the Tesseract executable and language data installed on the host. OCR and contextual detection cannot guarantee detection of handwriting, low-quality scans, or sensitive values outside the implemented patterns. Inspect the sanitized preview and extracted result before approval.
