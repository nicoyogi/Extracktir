"""Core PDF-to-Excel extraction logic.

Strategy
--------
For each PDF page we extract three layers of information:

1. **Tables** - via pdfplumber's table detection, returned as DataFrames.
2. **Key-value pairs** - lines like ``Label: value`` or ``Label    value``
   where the label looks like a field name.
3. **Raw text** - the full text of the page, kept as a fallback so the
   user can verify nothing was lost.

Optional layers:

* **Template fields** - if a :class:`Template` is supplied, its
  deterministic rules (regex / after_label) run as well, and the resulting
  fields land on a dedicated ``Template`` sheet.
* **OCR fallback** - if the PDF has no extractable text and ``ocr=True``,
  we run ``ocrmypdf`` first.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber

from .ocr import OcrResult, maybe_ocr
from .templates import Template, load_template


# -- Key/value heuristics ---------------------------------------------------

_KV_PATTERNS = [
    re.compile(r"^\s*(?P<key>[A-Z][\w &/().#-]{1,60}?)\s*[:\-]\s+(?P<value>\S.*?)\s*$"),
    re.compile(r"^\s*(?P<key>[A-Z][\w &/().#-]{1,60}?)\s{2,}(?P<value>\S.*?)\s*$"),
]
_SKIP_LINE = re.compile(r"^\s*[a-z]")


def _looks_like_label(label: str) -> bool:
    label = label.strip()
    if len(label) < 2 or len(label) > 60:
        return False
    if label.endswith("."):
        return False
    if not re.search(r"[A-Za-z]", label):
        return False
    words = label.split()
    if len(words) > 6:
        return False
    upper_starts = sum(1 for w in words if w[:1].isupper())
    return upper_starts >= max(1, len(words) - 1)


def _extract_kv_from_text(text: str) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or _SKIP_LINE.match(line):
            continue
        for pat in _KV_PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            key = m.group("key").strip().rstrip(":").strip()
            value = m.group("value").strip()
            if not _looks_like_label(key) or not value:
                continue
            sig = (key.lower(), value)
            if sig in seen:
                continue
            seen.add(sig)
            pairs.append({"Field": key, "Value": value})
            break
    return pairs


# -- Result container -------------------------------------------------------


@dataclass
class ExtractionResult:
    """Structured output of a single PDF extraction."""

    source: str
    page_count: int
    key_values: list[dict[str, Any]] = field(default_factory=list)
    template_fields: list[dict[str, Any]] = field(default_factory=list)
    tables: list[pd.DataFrame] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)
    template_name: str | None = None
    ocr: OcrResult | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pages": self.page_count,
            "key_value_count": len(self.key_values),
            "template_field_count": len(self.template_fields),
            "table_count": len(self.tables),
            "ocr_used": bool(self.ocr and self.ocr.used_ocr),
            "template": self.template_name or "",
        }


# -- Helpers ----------------------------------------------------------------


def _table_to_df(rows: list[list[str | None]]) -> pd.DataFrame | None:
    if not rows:
        return None
    cleaned = [[(c or "").strip() for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(c for c in r)]
    if not cleaned:
        return None

    header, *body = cleaned
    header_looks_real = all(h for h in header) and any(
        not h.replace(",", "").replace(".", "").replace("-", "").isdigit()
        for h in header
    )
    if header_looks_real and body:
        counts: dict[str, int] = {}
        unique_header = []
        for h in header:
            counts[h] = counts.get(h, 0) + 1
            unique_header.append(h if counts[h] == 1 else f"{h}_{counts[h]}")
        df = pd.DataFrame(body, columns=unique_header)
    else:
        df = pd.DataFrame(cleaned)
    return df


# -- Public API -------------------------------------------------------------


def extract_pdf(
    source: str | Path | io.IOBase,
    *,
    template: Template | str | Path | dict[str, Any] | None = None,
    ocr: bool = False,
    ocr_language: str = "eng",
) -> ExtractionResult:
    """Extract tables, key-values, and (optionally) template fields from a PDF.

    Parameters
    ----------
    source
        Path or binary file-like object.
    template
        Optional :class:`Template`, path, dict, or inline YAML/JSON text.
    ocr
        If True and the PDF has no extractable text, run ``ocrmypdf`` first.
    ocr_language
        Tesseract language code(s), e.g. ``"eng"`` or ``"eng+deu"``.
    """
    tpl = load_template(template) if template is not None else None

    # OCR fallback (no-op if PDF already has text or ocrmypdf isn't installed).
    ocr_result: OcrResult | None = None
    if ocr:
        path, ocr_result = maybe_ocr(source, language=ocr_language)
        opener_source: Any = path
        name = (
            getattr(source, "name", str(path))
            if hasattr(source, "read")
            else str(source)
        )
    elif isinstance(source, (str, Path)):
        opener_source = source
        name = str(source)
    else:
        opener_source = source
        name = getattr(source, "name", "uploaded.pdf")
        if hasattr(source, "seek"):
            source.seek(0)

    key_values: list[dict[str, Any]] = []
    tables: list[pd.DataFrame] = []
    page_texts: list[str] = []

    with pdfplumber.open(opener_source) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(text)

            for kv in _extract_kv_from_text(text):
                kv["Page"] = page_idx
                kv["Source"] = "heuristic"
                key_values.append(kv)

            for tbl_idx, raw in enumerate(page.extract_tables() or [], start=1):
                df = _table_to_df(raw)
                if df is None or df.empty:
                    continue
                df.attrs["page"] = page_idx
                df.attrs["index"] = tbl_idx
                tables.append(df)

        page_count = len(pdf.pages)

    template_fields: list[dict[str, Any]] = []
    template_name: str | None = None
    if tpl is not None:
        full_text = "\n".join(page_texts)
        if tpl.matches(full_text):
            template_fields = tpl.apply(page_texts)
            template_name = tpl.name

    return ExtractionResult(
        source=name,
        page_count=page_count,
        key_values=key_values,
        template_fields=template_fields,
        tables=tables,
        page_texts=page_texts,
        template_name=template_name,
        ocr=ocr_result,
    )


def _safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = re.sub(r"[:\\/?*\[\]]", "_", name)[:31] or "Sheet"
    candidate = cleaned
    n = 2
    while candidate in used:
        suffix = f"_{n}"
        candidate = (cleaned[: 31 - len(suffix)] + suffix)
        n += 1
    used.add(candidate)
    return candidate


def extract_to_excel(
    sources: Iterable[str | Path | io.IOBase],
    output: str | Path | io.IOBase,
    *,
    template: Template | str | Path | dict[str, Any] | None = None,
    ocr: bool = False,
    ocr_language: str = "eng",
) -> list[ExtractionResult]:
    """Extract one or more PDFs into a single Excel workbook.

    Sheets per workbook:
      * **Summary** - one row per input PDF.
      * **Template** - structured fields from the template (if supplied).
      * **Key-Values** - heuristic-detected labeled fields.
      * **<source>_pN_tM** - one sheet per detected table.
      * **Text** - raw text per page.
    """
    tpl = load_template(template) if template is not None else None
    results = [
        extract_pdf(s, template=tpl, ocr=ocr, ocr_language=ocr_language)
        for s in sources
    ]

    summary_rows = [r.summary() for r in results]
    kv_rows: list[dict[str, Any]] = []
    template_rows: list[dict[str, Any]] = []
    text_rows: list[dict[str, Any]] = []
    table_entries: list[tuple[str, pd.DataFrame]] = []

    used_sheets: set[str] = {"Summary", "Template", "Key-Values", "Text"}

    for r in results:
        src_name = Path(r.source).name
        for kv in r.key_values:
            kv_rows.append({"Source_File": src_name, **kv})
        for tf in r.template_fields:
            template_rows.append({"Source_File": src_name, "Template": r.template_name, **tf})
        for page_idx, text in enumerate(r.page_texts, start=1):
            text_rows.append({"Source": src_name, "Page": page_idx, "Text": text})
        for tbl in r.tables:
            page = tbl.attrs.get("page", "?")
            idx = tbl.attrs.get("index", "?")
            base = f"{Path(r.source).stem}_p{page}_t{idx}"
            sheet = _safe_sheet_name(base, used_sheets)
            table_entries.append((sheet, tbl))

    if isinstance(output, (str, Path)):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        target: Any = output
    else:
        target = output

    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

        if tpl is not None:
            tpl_cols = ["Source_File", "Template", "Field", "Value", "Page", "Source"]
            (
                pd.DataFrame(template_rows, columns=tpl_cols)
                if template_rows
                else pd.DataFrame(columns=tpl_cols)
            ).to_excel(writer, sheet_name="Template", index=False)

        kv_cols = ["Source_File", "Page", "Field", "Value", "Source"]
        (
            pd.DataFrame(kv_rows, columns=kv_cols)
            if kv_rows
            else pd.DataFrame(columns=kv_cols)
        ).to_excel(writer, sheet_name="Key-Values", index=False)

        for sheet, tbl in table_entries:
            tbl.to_excel(writer, sheet_name=sheet, index=False)

        pd.DataFrame(text_rows, columns=["Source", "Page", "Text"]).to_excel(
            writer, sheet_name="Text", index=False
        )

    return results
