"""FastAPI web app for Extracktir.

Run with:
    uvicorn extracktir.web:app --reload --port 8000

Endpoints
---------
GET  /                  -> Single-page UI (HTML)
POST /api/extract       -> Multipart form with one or more PDF files.
                           Returns JSON preview of extracted content.
POST /api/extract.xlsx  -> Multipart form with one or more PDF files.
                           Returns an Excel workbook download.
GET  /api/health        -> Liveness probe.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from .extractor import extract_pdf, extract_to_excel


app = FastAPI(
    title="Extracktir",
    description="Extract values, tables, and text from PDFs into Excel.",
    version="0.1.0",
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


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the single-page UI."""
    html_path = _STATIC_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/extract")
async def extract(files: list[UploadFile] = File(...)) -> JSONResponse:
    """Extract one or more PDFs and return a JSON preview."""
    uploads = await _read_uploads(files)

    payload: list[dict[str, Any]] = []
    for name, buf in uploads:
        buf.seek(0)
        result = extract_pdf(buf)
        payload.append(
            {
                "source": name,
                "pages": result.page_count,
                "key_values": result.key_values,
                "tables": [_df_to_records(t) for t in result.tables],
                "page_texts": result.page_texts,
            }
        )

    summary = [
        {
            "source": p["source"],
            "pages": p["pages"],
            "key_value_count": len(p["key_values"]),
            "table_count": len(p["tables"]),
        }
        for p in payload
    ]
    return JSONResponse({"summary": summary, "results": payload})


@app.post("/api/extract.xlsx")
async def extract_excel(files: list[UploadFile] = File(...)) -> StreamingResponse:
    """Extract one or more PDFs and stream back an .xlsx workbook."""
    uploads = await _read_uploads(files)

    sources = []
    for name, buf in uploads:
        buf.seek(0)
        sources.append(buf)

    out = io.BytesIO()
    extract_to_excel(sources, out)
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
