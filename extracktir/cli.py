"""Command-line entrypoint for batch PDF -> Excel extraction.

Examples
--------
    python -m extracktir invoice.pdf -o out.xlsx
    python -m extracktir ./invoices -o invoices.xlsx --template tpl.yaml
    python -m extracktir scan.pdf -o scan.xlsx --ocr --ocr-language eng
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractor import extract_to_excel
from .templates import load_template


def _expand(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if any(ch in raw for ch in "*?["):
            matches = sorted(Path().glob(raw))
            if not matches:
                print(f"warning: no files match {raw!r}", file=sys.stderr)
            out.extend(matches)
        elif p.is_dir():
            out.extend(sorted(p.glob("*.pdf")))
        else:
            out.append(p)

    missing = [p for p in out if not p.exists()]
    if missing:
        for p in missing:
            print(f"error: file not found: {p}", file=sys.stderr)
        sys.exit(2)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="extracktir",
        description="Extract values, tables, and text from PDF files into Excel.",
    )
    parser.add_argument("inputs", nargs="+", help="PDF files, directories, or globs.")
    parser.add_argument(
        "-o",
        "--output",
        default="extracktir_output.xlsx",
        help="Output .xlsx path (default: extracktir_output.xlsx).",
    )
    parser.add_argument(
        "-t",
        "--template",
        help="Path to a YAML/JSON template file describing fields to extract.",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Run ocrmypdf on inputs that have no extractable text.",
    )
    parser.add_argument(
        "--ocr-language",
        default="eng",
        help="Tesseract language code(s) for OCR (default: eng).",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress per-file summaries.")
    args = parser.parse_args(argv)

    files = _expand(args.inputs)
    if not files:
        print("error: no input PDFs provided", file=sys.stderr)
        return 2

    template = None
    if args.template:
        try:
            template = load_template(args.template)
        except Exception as e:
            print(f"error: failed to load template: {e}", file=sys.stderr)
            return 2

    out_path = Path(args.output)
    results = extract_to_excel(
        files,
        out_path,
        template=template,
        ocr=args.ocr,
        ocr_language=args.ocr_language,
    )

    if not args.quiet:
        for r in results:
            s = r.summary()
            ocr_tag = " (OCR)" if s["ocr_used"] else ""
            tpl_tag = f" [{s['template']}]" if s["template"] else ""
            extras = []
            if s["template_field_count"]:
                extras.append(f"{s['template_field_count']} template fields")
            extras.append(f"{s['key_value_count']} fields")
            extras.append(f"{s['table_count']} table(s)")
            print(
                f"  {Path(s['source']).name}{ocr_tag}{tpl_tag}: "
                f"{s['pages']} page(s), " + ", ".join(extras)
            )
    print(f"Wrote {out_path} ({len(results)} PDF(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
