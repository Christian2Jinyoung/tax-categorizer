from app.ingestion.normalize import normalize_row
from app.ingestion.pdf_digital import extract_pdf_pages_text, has_text_layer
from app.ingestion.receipt_parser import parse_receipt_text
from app.ingestion.spreadsheet import guess_column_mapping, read_spreadsheet
from app.models import LineItem


def extract_spreadsheet_line_items(path: str, file_type: str, batch_id: int, source_file_id: int) -> list[LineItem]:
    """CSV/XLSX -> normalized, uncategorized LineItem rows (Phase 1 path).

    PDF (pdf_digital.py) and OCR (ocr.py / claude_repair.py) paths plug into this
    same pipeline in later phases; this function only covers the spreadsheet path.
    """
    df = read_spreadsheet(path, file_type)
    mapping = guess_column_mapping(df)

    extraction_method = "csv_direct" if file_type == "csv" else "xlsx_direct"

    items: list[LineItem] = []
    for row_index, row in enumerate(df.to_dict(orient="records")):
        fields = normalize_row(row, mapping)
        items.append(
            LineItem(
                batch_id=batch_id,
                source_file_id=source_file_id,
                row_index=row_index,
                raw_text=fields.raw_text,
                extraction_method=extraction_method,
                extraction_confidence=1.0,
                date=fields.date,
                vendor=fields.vendor,
                description=fields.description,
                amount=fields.amount,
                quantity=fields.quantity,
            )
        )
    return items


def extract_pdf_line_items(path: str, batch_id: int, source_file_id: int) -> list[LineItem]:
    """Digital-PDF path (Phase 5): text-layer extraction + generic receipt parsing.

    Text-layer pages are concatenated into one document before parsing, since a single
    receipt is often split across multiple print pages (e.g. a browser "print to PDF" of
    a Costco order-history page) - parsing page-by-page would re-detect the vendor/date
    per page and spuriously flag trailing footer-only pages as "no items found".

    Scanned pages with no text layer are recorded as needs_review placeholders rather
    than dropped - OCR (ocr.py / claude_repair.py) plugs in here in a later phase.
    """
    items: list[LineItem] = []
    pages_text = extract_pdf_pages_text(path)

    text_pages = []
    for page_num, text in enumerate(pages_text):
        if has_text_layer(text):
            text_pages.append(text)
        elif not text.strip():
            # Genuinely blank page (e.g. a trailing page-break artifact from a browser
            # "print to PDF") - nothing was lost, so skip it rather than flagging for review.
            continue
        else:
            items.append(
                LineItem(
                    batch_id=batch_id,
                    source_file_id=source_file_id,
                    row_index=page_num,
                    raw_text=None,
                    extraction_method="pdf_text_layer",
                    extraction_confidence=0.0,
                    review_status="needs_review",
                    rationale=(
                        "Page has no extractable text layer (likely scanned) - "
                        "OCR ingestion isn't implemented yet."
                    ),
                )
            )

    if text_pages:
        combined_text = "\n".join(text_pages)
        _vendor, _date, parsed_items = parse_receipt_text(combined_text)

        if not parsed_items:
            items.append(
                LineItem(
                    batch_id=batch_id,
                    source_file_id=source_file_id,
                    row_index=0,
                    raw_text=combined_text[:2000],
                    extraction_method="pdf_text_layer",
                    extraction_confidence=0.3,
                    review_status="needs_review",
                    rationale="Could not identify individual line items in this document; raw text captured for manual review.",
                )
            )
        else:
            for item_index, fields in enumerate(parsed_items):
                items.append(
                    LineItem(
                        batch_id=batch_id,
                        source_file_id=source_file_id,
                        row_index=item_index,
                        raw_text=fields.raw_text,
                        extraction_method="pdf_text_layer",
                        extraction_confidence=0.8,
                        date=fields.date,
                        vendor=fields.vendor,
                        description=fields.description,
                        amount=fields.amount,
                        quantity=fields.quantity,
                    )
                )

    return items
