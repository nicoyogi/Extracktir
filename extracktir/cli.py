"""Command-line entrypoint for batch PDF -> Excel extraction.

Usage:
    python -m extracktir.cli file1.pdf file2.pdf -o out.xlsx
    python -m extracktir.cli ./invoices/*.pdf -o invoices.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .extractor import extract_to_excel


def _expand(paths: list[str]) -> list[Path]:
    """Expand globs and validate paths."""
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
    parser.add_argument(
        "inputs",
        nargs="+",
        help="PDF files, directories, or glob patterns.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="extracktir_output.xlsx",
        help="Output .xlsx path (default: extracktir_output.xlsx).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress per-file summaries.",
    )
    args = parser.parse_args(argv)

    files = _expand(args.inputs)
    if not files:
        print("error: no input PDFs provided", file=sys.stderr)
        return 2

    out_path = Path(args.output)
    results = extract_to_excel(files, out_path)

    if not args.quiet:
        for r in results:
            s = r.summary()
            print(
                f"  {Path(s['source']).name}: {s['pages']} page(s), "
                f"{s['key_value_count']} fields, {s['table_count']} table(s)"
            )
    print(f"Wrote {out_path} ({len(results)} PDF(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
