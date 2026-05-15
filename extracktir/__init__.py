"""Extracktir: extract structured values from PDFs into Excel."""
from .extractor import extract_pdf, extract_to_excel, ExtractionResult
from .templates import Template, load_template
from .ocr import maybe_ocr, run_ocr, is_available as ocr_available

__all__ = [
    "extract_pdf",
    "extract_to_excel",
    "ExtractionResult",
    "Template",
    "load_template",
    "maybe_ocr",
    "run_ocr",
    "ocr_available",
]
__version__ = "0.2.0"
