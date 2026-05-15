"""Core PDF-to-Excel extraction logic.

Strategy
--------
For each PDF page we extract three layers of information:

1. **Tables** - via pdfplumber's table detection, returned as DataFrames.
2. **Key-value pairs** - lines like ``Label: value`` or ``Label    value``
   where the label looks like a field name. These are often the most
   useful "values" in invoices, forms, receipts, statements.
3. **Raw text** - the full text of the page, kept as a fallback so the
   user can verify nothing was lost.

Everything is then written to a multi-sheet ``.xlsx`` workbook.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber


# -- Key/value heuristics ---------------------------------------------------

# Line shapes we treat as a labeled value:
#   "Invoice Number: 12345"
#   "Total Amount  $1,234.56"
#   "Date - 2026-05-15"
# Label = up to ~6 capitalized/Title-case words, value = remainder.
_KV_PATTERNS = [
    re.compile(r"^\s*(?P<key>[A-Z][\w &/().#-]{1,60}?)\s*[:\-]\s+(?P<value>\S.*?)\s*$"),
    re.compile(
        r"^\s*(?P<key>[A-Z][\w &/().#-]{1,60}?)\s{2,}(?P<value>\S.*?)\s*$"
    ),
]

# Lines that look more like prose than fields - skip these.
_SKIP_LINE = re.compile(r"^\s*[a-z]")


def _looks_like_label(label: str) -> bool:
    """Reject obvious sentences masquerading as labels."""
    label = label.strip()
    if len(label) < 2 or len(label) > 60:
        return False
    if label.endswith("."):
        return False
    # Must contain at least one letter; avoid "1234" being seen as a label.
    if not re.search(r"[A-Za-z]", label):
        return False
    # Reject labels that are mostly lowercase prose.
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
    tables: list[pd.DataFrame] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "pages": self.page_count,
            "key_value_count": len(self.key_values),
            "table_count": len(self.tables),
        }


# -- Public API -------------------------------------------------------------


def _table_to_df(rows: list[list[str | None]]) -> pd.DataFrame | None:
    """Convert a raw pdfplumber table into a DataFrame, using row 0 as header
    when it looks like one."""
    if not rows:
        return None
    cleaned = [[(c or "").strip() for c in row] for row in rows]
    # Drop fully empty rows.
    cleaned = [r for r in cleaned if any(c for c in r)]
    if not cleaned:
        return None

    header, *body = cleaned
    header_looks_real = all(h for h in header) and any(
        not h.replace(",", "").replace(".", "").replace("-", "").isdigit()
        for h in header
    )
    if header_looks_real and body:
        # De-duplicate header names.
        counts: dict[str, int] = {}
        unique_header = []
        for h in header:
            counts[h] = counts.get(h, 0) + 1
            unique_header.append(h if counts[h] == 1 else f"{h}_{counts[h]}")
        df = pd.DataFrame(body, columns=unique_header)
    else:
        df = pd.DataFrame(cleaned)
    return df


def extract_pdf(source: str | Path | io.IOBase) -> ExtractionResult:
    """Extract tables, key-values, and text from a PDF.

    ``source`` may be a path or any binary file-like object (e.g. an
    uploaded file from Streamlit).
    """
    if isinstance(source, (str, Path)):
        name = str(source)
        opener = pdfplumber.open(source)
    else:
        name = getattr(source, "name", "uploaded.pdf")
        opener = pdfplumber.open(source)

    key_values: list[dict[str, Any]] = []
    tables: list[pd.DataFrame] = []
    page_texts: list[str] = []

    with opener as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            page_texts.append(text)

            for kv in _extract_kv_from_text(text):
                kv["Page"] = page_idx
                key_values.append(kv)

            for tbl_idx, raw in enumerate(page.extract_tables() or [], start=1):
                df = _table_to_df(raw)
                if df is None or df.empty:
                    continue
                df.attrs["page"] = page_idx
                df.attrs["index"] = tbl_idx
                tables.append(df)

        page_count = len(pdf.pages)

    return ExtractionResult(
        source=name,
        page_count=page_count,
        key_values=key_values,
        tables=tables,
        page_texts=page_texts,
    )


def _safe_sheet_name(name: str, used: set[str]) -> str:
    """Excel sheet names: <=31 chars, no : \\ / ? * [ ]"""
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
) -> list[ExtractionResult]:
    """Extract one or more PDFs into a single Excel workbook.

    Sheets per workbook:
      * **Summary** - one row per input PDF.
      * **Key-Values** - all labeled fields from all PDFs.
      * **Table_<n>** - one sheet per detected table.
      * **Text** - raw text per page (for verification).
    """
    results = [extract_pdf(s) for s in sources]

    summary_rows = [r.summary() for r in results]
    kv_rows: list[dict[str, Any]] = []
    text_rows: list[dict[str, Any]] = []
    table_entries: list[tuple[str, pd.DataFrame]] = []

    used_sheets: set[str] = {"Summary", "Key-Values", "Text"}

    for r in results:
        src_name = Path(r.source).name
        for kv in r.key_values:
            kv_rows.append({"Source": src_name, **kv})
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

        if kv_rows:
            pd.DataFrame(kv_rows, columns=["Source", "Page", "Field", "Value"]).to_excel(
                writer, sheet_name="Key-Values", index=False
            )
        else:
            pd.DataFrame(columns=["Source", "Page", "Field", "Value"]).to_excel(
                writer, sheet_name="Key-Values", index=False
            )

        for sheet, tbl in table_entries:
            tbl.to_excel(writer, sheet_name=sheet, index=False)

        pd.DataFrame(text_rows, columns=["Source", "Page", "Text"]).to_excel(
            writer, sheet_name="Text", index=False
        )

    return results
