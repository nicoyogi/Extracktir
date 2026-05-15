"""Extracktir: extract structured values from PDFs into Excel."""
from .extractor import extract_pdf, extract_to_excel, ExtractionResult

__all__ = ["extract_pdf", "extract_to_excel", "ExtractionResult"]
__version__ = "0.1.0"
