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

### Web UI (recommended)

```bash
streamlit run app.py
```

Then drop one or more PDFs onto the page, preview what was found, and
download the Excel file.

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
├── app.py                 # Streamlit UI
├── requirements.txt
└── extracktir/
    ├── __init__.py        # public API: extract_pdf, extract_to_excel
    ├── __main__.py        # python -m extracktir
    ├── cli.py             # batch CLI
    └── extractor.py       # core extraction logic
```
