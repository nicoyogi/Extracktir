# Extracktir

Extract values, tables, and text from PDF files into a single Excel workbook.

Extracktir handles the PDFs that show up in real work — invoices, statements,
forms, receipts — and turns them into a structured `.xlsx` you can open in
Excel or analyze in pandas.

## What it pulls out

For every PDF, Extracktir produces:

| Sheet         | Contents                                                                 |
| ------------- | ------------------------------------------------------------------------ |
| `Summary`     | One row per input PDF (page count, fields found, tables found).          |
| `Key-Values`  | Labeled fields like `Invoice No: 12345`, `Total  $1,234.56`, with page.  |
| `Table_<n>`   | One sheet per detected table, headers preserved when present.            |
| `Text`        | Raw text per page, so nothing is lost.                                   |

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.10+.

## Use it

### Web app (FastAPI)

A self-contained web app with drag-and-drop, JSON preview, and Excel
download:

```bash
uvicorn extracktir.web:app --reload --port 8000
```

Then open http://localhost:8000.

| Route                  | What it does                                       |
| ---------------------- | -------------------------------------------------- |
| `GET  /`               | Single-page UI                                     |
| `POST /api/extract`    | Multipart upload, JSON preview of fields & tables  |
| `POST /api/extract.xlsx` | Multipart upload, returns the `.xlsx` workbook   |
| `GET  /api/health`     | Liveness probe                                     |
| `GET  /docs`           | Auto-generated OpenAPI docs                        |

Example via `curl`:

```bash
curl -F "files=@invoice.pdf" -o out.xlsx http://localhost:8000/api/extract.xlsx
```

### Streamlit UI (alternative)

```bash
streamlit run app.py
```

### Command line

```bash
# Single file
python -m extracktir invoice.pdf -o invoice.xlsx

# Multiple files / globs / directories
python -m extracktir ./statements -o statements.xlsx
python -m extracktir "invoices/*.pdf" -o all_invoices.xlsx
```

### As a library

```python
from extracktir import extract_pdf, extract_to_excel

# Inspect a single PDF
result = extract_pdf("invoice.pdf")
print(result.summary())
for kv in result.key_values:
    print(kv)

# Write one or more PDFs to Excel
extract_to_excel(["a.pdf", "b.pdf"], "out.xlsx")
```

## How the extraction works

- **Tables** are detected with [pdfplumber](https://github.com/jsvine/pdfplumber).
  When the first row looks like a real header (non-empty, non-numeric), it is
  used as the column header.
- **Key-values** are pulled from text lines that match either
  `Label: value` or `Label   value` (two-or-more spaces between label and
  value). Labels are filtered to look like field names rather than prose.
- **Text** is kept verbatim per page as a fallback.

This works well for digital PDFs. Scanned/image-only PDFs need OCR first
(e.g. `ocrmypdf input.pdf output.pdf`) before passing them to Extracktir.

## Project layout

```
Extracktir/
├── app.py                      # Streamlit UI
├── requirements.txt
└── extracktir/
    ├── __init__.py             # public API: extract_pdf, extract_to_excel
    ├── __main__.py             # python -m extracktir
    ├── cli.py                  # batch CLI
    ├── extractor.py            # core extraction logic
    ├── web.py                  # FastAPI app (uvicorn extracktir.web:app)
    └── static/
        └── index.html          # web UI
```
