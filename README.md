# Extracktir

Extract values, tables, and text from PDF files into a single Excel workbook.

Extracktir handles the PDFs that show up in real work — invoices, statements,
forms, receipts — and turns them into a structured `.xlsx` you can open in
Excel or analyze in pandas. It works on digital PDFs out of the box, falls
back to OCR for scans, and lets you pin down exact fields with optional
YAML/JSON templates.

## What you get back

For every PDF, Extracktir produces a multi-sheet workbook:

| Sheet         | Contents                                                                 |
| ------------- | ------------------------------------------------------------------------ |
| `Summary`     | One row per input PDF (pages, fields, tables, OCR used, template name).  |
| `Template`    | Deterministic fields from your template (only when a template is used).  |
| `Key-Values`  | Heuristic-detected labeled fields like `Invoice No: 12345`, with page.   |
| `<src>_pN_tM` | One sheet per detected table, headers preserved when present.            |
| `Text`        | Raw text per page, so nothing is lost.                                   |

## Quick start

### With Docker (recommended — OCR included)

```bash
docker compose up --build
# then open http://localhost:8000
```

This bundles `ocrmypdf` + `tesseract` + `ghostscript`, so scanned PDFs work
out of the box. To add more OCR languages, edit `docker-compose.yml`:

```yaml
build:
  args:
    TESSDATA_LANGS: "eng deu fra spa"
```

### Without Docker

```bash
pip install -r requirements.txt
uvicorn extracktir.web:app --reload --port 8000
```

For OCR support, also install `ocrmypdf` ([install
guide](https://ocrmypdf.readthedocs.io/en/latest/installation.html)). The
app will auto-detect it and gray out the OCR toggle if it's missing.

### Deploy online

The app is stateless, listens on `$PORT`, and has a `/api/health` probe,
so it deploys to any container host. See [DEPLOY.md](./DEPLOY.md) for
copy-paste recipes:

| Target              | Free? | One command / click                              |
| ------------------- | ----- | ------------------------------------------------ |
| Hugging Face Spaces | Yes   | Push the repo, add a YAML header to README       |
| Render              | Yes   | [One-click deploy](https://render.com/deploy?repo=https://github.com/nicoyogi/Extracktir) (uses `render.yaml`) |
| Fly.io              | ~$3   | `fly launch --copy-config --no-deploy && fly deploy` (uses `fly.toml`) |
| Google Cloud Run    | Yes   | `gcloud run deploy extracktir --source . --port 8000`        |
| Any VPS             | $5+   | `docker compose up -d --build`                   |

## Use it

### Web UI

Open `/` in your browser. Drag in PDFs, optionally:
- Upload a template (YAML/JSON) or paste one inline.
- Toggle OCR for scanned PDFs.

Then preview the results and download the Excel file.

### HTTP API

| Route                    | What it does                                          |
| ------------------------ | ----------------------------------------------------- |
| `GET  /`                 | Single-page UI                                        |
| `POST /api/extract`      | Multipart upload, JSON preview                        |
| `POST /api/extract.xlsx` | Multipart upload, returns the `.xlsx` workbook        |
| `GET  /api/health`       | Liveness probe + `{ocr_available: bool}` capability   |
| `GET  /docs`             | Auto-generated OpenAPI docs                           |

Multipart form fields for the `extract` endpoints:

| Field           | Type         | Description                                  |
| --------------- | ------------ | -------------------------------------------- |
| `files`         | file (multi) | One or more `.pdf` files.                    |
| `template_file` | file         | Optional YAML/JSON template file.            |
| `template`      | string       | Optional inline template text (alternative). |
| `ocr`           | bool         | Run OCR if a PDF has no extractable text.    |
| `ocr_language`  | string       | Tesseract language code (default `eng`).     |

```bash
# Plain extraction
curl -F "files=@invoice.pdf" -o out.xlsx http://localhost:8000/api/extract.xlsx

# With a template
curl -F "files=@invoice.pdf" \
     -F "template_file=@templates/acme-invoice.yaml" \
     -o invoice.xlsx \
     http://localhost:8000/api/extract.xlsx

# With OCR for a scanned PDF
curl -F "files=@scan.pdf" -F "ocr=true" -F "ocr_language=eng" \
     -o scan.xlsx \
     http://localhost:8000/api/extract.xlsx
```

### Command line

```bash
python -m extracktir invoice.pdf -o invoice.xlsx
python -m extracktir ./statements -o statements.xlsx
python -m extracktir invoice.pdf -o invoice.xlsx --template templates/acme-invoice.yaml
python -m extracktir scan.pdf -o scan.xlsx --ocr --ocr-language eng
python -m extracktir "invoices/*.pdf" -o all.xlsx --template tpl.yaml
```

### Streamlit UI (alternative)

```bash
streamlit run app.py
```

### As a library

```python
from extracktir import extract_pdf, extract_to_excel, load_template

tpl = load_template("templates/acme-invoice.yaml")

# Inspect a single PDF
result = extract_pdf("invoice.pdf", template=tpl, ocr=True)
for f in result.template_fields:
    print(f["Field"], "->", f["Value"])
print(result.summary())

# Write a workbook for many PDFs at once
extract_to_excel(
    ["a.pdf", "b.pdf"],
    "out.xlsx",
    template=tpl,
    ocr=True,
)
```

## Templates

A *template* is a small YAML or JSON document that pins down the fields
you care about for a specific PDF layout (an invoice format, a bank
statement layout, a tax form). When a template is provided, its rules run
**alongside** the generic key-value heuristic — you get both the
deterministic named fields and anything else the heuristic catches.

```yaml
name: acme-invoice
description: ACME Corp invoices, 2026 layout

# Optional: only apply this template if all `match` patterns appear
# somewhere in the document.
match:
  - "ACME Corp"
  - "Invoice"

fields:
  - name: invoice_number
    type: regex
    pattern: 'Invoice Number:\s*(?P<value>\S+)'

  - name: total_amount
    type: regex
    pattern: 'Total Amount:\s*\$?(?P<value>[\d,.]+)'
    cast: number

  - name: bill_to
    type: after_label
    label: "Bill To"

  - name: due_date
    type: after_label
    label: "Due Date"
    cast: date
```

**Rule types:**
- `regex` — a Python regex applied to the document text. The value is the
  named group `value` if present, else group 1, else the whole match.
- `after_label` — find the line containing `label` and take whatever
  follows it (after `:` or 2+ spaces). If the label line is bare, the next
  non-empty line is used.

**Casts:** `string` (default), `number`, `date`.

A working sample template lives at
[`templates/acme-invoice.yaml`](templates/acme-invoice.yaml).

## How extraction works

- **Tables** come from
  [pdfplumber](https://github.com/jsvine/pdfplumber). When the first row
  looks like a real header (non-empty, non-numeric), it's used as the
  column header; otherwise rows are returned positionally.
- **Heuristic key-values** are pulled from text lines matching either
  `Label: value` or `Label   value` (2+ spaces). Labels are filtered to
  look like field names rather than prose.
- **Template fields** apply user-supplied rules deterministically and
  attach the page number for traceability.
- **OCR fallback** runs `ocrmypdf` (with `--skip-text`) when a PDF has no
  extractable text. Results carry an `ocr_used: true` flag and the rest of
  the pipeline runs unchanged.

## Project layout

```
Extracktir/
├── app.py                      # Streamlit UI
├── Dockerfile                  # python:3.11-slim + ocrmypdf + tesseract
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
├── templates/
│   └── acme-invoice.yaml       # sample template
├── sample/
│   └── invoice.pdf             # sample PDF for smoke tests
├── scripts/
│   └── make_sample_pdf.py
└── extracktir/
    ├── __init__.py             # public API
    ├── __main__.py             # python -m extracktir
    ├── cli.py                  # batch CLI (--template, --ocr, ...)
    ├── extractor.py            # core extraction
    ├── templates.py            # YAML/JSON template engine
    ├── ocr.py                  # ocrmypdf integration
    ├── web.py                  # FastAPI app
    └── static/
        └── index.html          # web UI
```
