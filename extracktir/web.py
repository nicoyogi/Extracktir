"""FastAPI web app for Extracktir.

Run with:
    uvicorn extracktir.web:app --reload --port 8000

Endpoints
---------
GET  /                  -> Single-page UI (HTML)
POST /api/extract       -> Multipart form (files=<pdf>..., template?, ocr?, ocr_language?).
                           Returns JSON preview of extracted content.
POST /api/extract.xlsx  -> Same form. Returns an Excel workbook download.
GET  /api/health        -> Liveness probe + capability flags.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import __version__
from .extractor import extract_pdf, extract_to_excel
from .ocr import is_available as ocr_available
from .templates import Template, load_template


app = FastAPI(
    title="Extracktir",
    description="Extract values, tables, and text from PDFs into Excel.",
    version=__version__,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _df_to_records(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "page": df.attrs.get("page"),
        "index": df.attrs.get("index"),
        "columns": [str(c) for c in df.columns],
        "rows": df.fillna("").astype(str).values.tolist(),
    }


async def _read_uploads(files: list[UploadFile]) -> list[tuple[str, io.BytesIO]]:
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    out: list[tuple[str, io.BytesIO]] = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"Only .pdf files are supported (got {f.filename!r}).",
            )
        data = await f.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"{f.filename} is empty.")
        buf = io.BytesIO(data)
        buf.name = f.filename  # type: ignore[attr-defined]
        out.append((f.filename, buf))
    return out


async def _resolve_template(
    template_text: Optional[str],
    template_file: Optional[UploadFile],
) -> Optional[Template]:
    """Build a Template from inline text or an uploaded file. None if neither."""
    raw: Optional[str] = None
    if template_file is not None and template_file.filename:
        raw = (await template_file.read()).decode("utf-8")
    elif template_text and template_text.strip():
        raw = template_text
    if not raw:
        return None
    try:
        return load_template(raw)
    except Exception as e:  # noqa: BLE001 - return user-facing error
        raise HTTPException(status_code=400, detail=f"Invalid template: {e}") from e


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "ocr_available": ocr_available(),
    }


@app.post("/api/extract")
async def extract(
    files: list[UploadFile] = File(...),
    template: Optional[str] = Form(default=None),
    template_file: Optional[UploadFile] = File(default=None),
    ocr: bool = Form(default=False),
    ocr_language: str = Form(default="eng"),
) -> JSONResponse:
    uploads = await _read_uploads(files)
    tpl = await _resolve_template(template, template_file)

    if ocr and not ocr_available():
        raise HTTPException(
            status_code=400,
            detail="OCR was requested but ocrmypdf is not installed in this environment.",
        )

    payload: list[dict[str, Any]] = []
    for name, buf in uploads:
        buf.seek(0)
        result = extract_pdf(buf, template=tpl, ocr=ocr, ocr_language=ocr_language)
        payload.append(
            {
                "source": name,
                "pages": result.page_count,
                "key_values": result.key_values,
                "template_fields": result.template_fields,
                "template_name": result.template_name,
                "ocr_used": bool(result.ocr and result.ocr.used_ocr),
                "ocr_reason": result.ocr.reason if result.ocr else None,
                "tables": [_df_to_records(t) for t in result.tables],
                "page_texts": result.page_texts,
            }
        )

    summary = [
        {
            "source": p["source"],
            "pages": p["pages"],
            "key_value_count": len(p["key_values"]),
            "template_field_count": len(p["template_fields"]),
            "table_count": len(p["tables"]),
            "ocr_used": p["ocr_used"],
            "template": p["template_name"] or "",
        }
        for p in payload
    ]
    return JSONResponse(
        {
            "summary": summary,
            "results": payload,
            "ocr_available": ocr_available(),
        }
    )


@app.post("/api/extract.xlsx")
async def extract_excel(
    files: list[UploadFile] = File(...),
    template: Optional[str] = Form(default=None),
    template_file: Optional[UploadFile] = File(default=None),
    ocr: bool = Form(default=False),
    ocr_language: str = Form(default="eng"),
) -> StreamingResponse:
    uploads = await _read_uploads(files)
    tpl = await _resolve_template(template, template_file)

    if ocr and not ocr_available():
        raise HTTPException(
            status_code=400,
            detail="OCR was requested but ocrmypdf is not installed in this environment.",
        )

    sources = []
    for _name, buf in uploads:
        buf.seek(0)
        sources.append(buf)

    out = io.BytesIO()
    extract_to_excel(sources, out, template=tpl, ocr=ocr, ocr_language=ocr_language)
    out.seek(0)

    if len(uploads) == 1:
        filename = Path(uploads[0][0]).stem + ".xlsx"
    else:
        filename = "extracktir_output.xlsx"

    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
