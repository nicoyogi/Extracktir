"""Generate a sample invoice PDF for smoke-testing Extracktir."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


def build(path: Path) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    story = []

    story.append(Paragraph("ACME Corp", styles["Title"]))
    story.append(Paragraph("Invoice", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))

    fields = [
        "Invoice Number: INV-2026-00042",
        "Issue Date: 2026-05-15",
        "Due Date: 2026-06-14",
        "Bill To: Globex LLC",
        "Account ID: AC-9931",
        "PO Number: PO-77821",
        "Currency: USD",
        "Total Amount: $4,275.00",
    ]
    for line in fields:
        story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    data = [
        ["Item", "Description", "Qty", "Unit Price", "Line Total"],
        ["A-100", "Widget, small", "10", "$25.00", "$250.00"],
        ["A-200", "Widget, large", "5", "$75.00", "$375.00"],
        ["B-300", "Gadget Pro", "2", "$1,500.00", "$3,000.00"],
        ["S-001", "Shipping & handling", "1", "$650.00", "$650.00"],
    ]
    table = Table(data, hAlign="LEFT", colWidths=[0.9 * inch, 2.6 * inch, 0.6 * inch, 1.1 * inch, 1.1 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph("Subtotal: $4,275.00", styles["Normal"]))
    story.append(Paragraph("Tax: $0.00", styles["Normal"]))
    story.append(Paragraph("Balance Due: $4,275.00", styles["Normal"]))

    doc.build(story)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "sample" / "invoice.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    build(out)
    print(f"Wrote {out}")
