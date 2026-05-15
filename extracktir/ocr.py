"""OCR fallback for image-only PDFs.

Strategy: if a PDF has effectively no extractable text, run ``ocrmypdf``
to bake a text layer in, then return the OCR'd file. This is invoked
*before* extraction so the rest of the pipeline doesn't need to know.

ocrmypdf is an external tool that wraps tesseract + ghostscript. We do
not call tesseract directly because ocrmypdf handles the corner cases
(rotation, language, output layout) much better.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass
class OcrResult:
    used_ocr: bool
    reason: str
    out_path: Path | None
    log: str = ""


def _has_text(pdf_path: str | Path, min_chars: int = 20) -> bool:
    """Return True if any page has at least ``min_chars`` of extractable text."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = (page.extract_text() or "").strip()
                if len(text) >= min_chars:
                    return True
    except Exception:
        # If we can't read it at all, treat as needing OCR.
        return False
    return False


def is_available() -> bool:
    """True if ``ocrmypdf`` is installed and on PATH."""
    return shutil.which("ocrmypdf") is not None


def run_ocr(
    src: str | Path,
    dest: str | Path,
    *,
    language: str = "eng",
    extra_args: list[str] | None = None,
) -> OcrResult:
    """Force-run ocrmypdf on ``src`` and write to ``dest``."""
    if not is_available():
        return OcrResult(False, "ocrmypdf is not installed", None)

    cmd = [
        "ocrmypdf",
        "--skip-text",  # don't touch pages that already have text
        "--language",
        language,
        "--output-type",
        "pdf",
        "--quiet",
        str(src),
        str(dest),
    ]
    if extra_args:
        cmd[1:1] = extra_args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return OcrResult(
            False,
            f"ocrmypdf failed (exit {proc.returncode})",
            None,
            log=proc.stderr or proc.stdout,
        )
    return OcrResult(True, "ocr applied", Path(dest), log=proc.stdout)


def maybe_ocr(
    source: str | Path | io.IOBase,
    *,
    workdir: str | Path | None = None,
    force: bool = False,
    language: str = "eng",
) -> tuple[Path, OcrResult]:
    """If the PDF has no extractable text, run OCR and return the new path.

    Returns ``(path_to_pdf, ocr_result)``. The returned path may be the
    original file (if no OCR was needed/possible) or a freshly OCR'd file
    inside ``workdir``.

    ``source`` may be a path or a binary file-like object; in the latter
    case it is staged to a temp file first.
    """
    workdir = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="extracktir_"))
    workdir.mkdir(parents=True, exist_ok=True)

    # Stage file-like sources.
    if hasattr(source, "read"):
        staged = workdir / getattr(source, "name", "input.pdf")
        staged = Path(staged.name) if staged.is_absolute() else workdir / Path(staged).name
        source.seek(0)  # type: ignore[union-attr]
        staged.write_bytes(source.read())  # type: ignore[union-attr]
        src_path = staged
    else:
        src_path = Path(source)

    if not force and _has_text(src_path):
        return src_path, OcrResult(False, "pdf already has text", None)

    if not is_available():
        return src_path, OcrResult(False, "ocrmypdf is not installed", None)

    out_path = workdir / (src_path.stem + ".ocr.pdf")
    result = run_ocr(src_path, out_path, language=language)
    if result.used_ocr and result.out_path:
        return result.out_path, result
    return src_path, result
