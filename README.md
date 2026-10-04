# ClearDoc: document digitization prototype

A small Flask app for OCR, local sensitive-data masking, structured extraction, human review, and Excel export. The privacy layer always runs locally before Gemini is called. Demo mode is enabled by default and sends no network request.

## Run locally

1. Use Python 3.10 or newer and install Tesseract OCR on the machine. Tesseract is an external system dependency used by `pytesseract`.
2. Create and activate a virtual environment, then install `requirements.txt`.
3. Copy `.env` to `.env`. Leave `DEMO_MODE=true` for offline development, or set it to `false` and add `GEMINI_API_KEY` to use Gemini. Do not commit `.env`.
4. Run `python app.py` and open http://127.0.0.1:5000.

The default upload limit is 20 MB. Change `MAX_CONTENT_LENGTH_MB` to adjust it. The app accepts PDF and common raster image formats. OCR and sensitive-data checks run on the Flask host. Images are sent to Gemini only after OCR-detected sensitive text regions are blacked out in generated local previews; Gemini receives the tokenized OCR text, never the original. The exported review is stored temporarily in process memory, so restarting the server clears review state. Approve a review before exporting an `.xlsx` file.

## Checks

Run the deterministic privacy checks with `python -m unittest discover -s tests`. Run `python -m py_compile app.py backend/pipeline.py` for syntax validation. OCR requires the Tesseract executable and language data installed on the host. OCR cannot guarantee detection of handwriting, low-quality scans, or sensitive values outside the included patterns; always inspect the redacted preview and extracted result before approval.
