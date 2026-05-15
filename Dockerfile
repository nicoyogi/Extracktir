# Extracktir: PDF -> Excel web app with OCR support.
#
# This image bundles ocrmypdf + tesseract + ghostscript so the OCR fallback
# works out of the box. The default CMD runs the FastAPI app on port 8000.

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# System deps:
#   ocrmypdf: needs tesseract (OCR engine), ghostscript (PDF processing),
#             unpaper (deskew/clean), pngquant + jbig2 (compression),
#             qpdf (PDF rewriting).
#   build-essential is needed by some pdfplumber / pillow wheels on slim.
#   Default tesseract languages: eng. Add more via TESSDATA_LANGS build arg.
ARG TESSDATA_LANGS="eng"
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ghostscript \
        qpdf \
        ocrmypdf \
        tesseract-ocr \
        unpaper \
        pngquant \
        ca-certificates \
        curl \
 && for lang in $TESSDATA_LANGS; do \
        if [ "$lang" != "eng" ]; then \
            apt-get install -y --no-install-recommends "tesseract-ocr-$lang" || true; \
        fi; \
    done \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the source. .dockerignore keeps this minimal.
COPY extracktir ./extracktir
COPY app.py ./app.py
COPY templates ./templates
COPY README.md ./README.md

# Run as non-root.
RUN useradd --create-home --uid 10001 extracktir \
 && chown -R extracktir:extracktir /app
USER extracktir

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

CMD ["sh", "-c", "exec uvicorn extracktir.web:app --host 0.0.0.0 --port ${PORT}"]
