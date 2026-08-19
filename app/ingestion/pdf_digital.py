import pdfplumber

MIN_CHARS_FOR_TEXT_LAYER = 20


def extract_pdf_pages_text(path: str) -> list[str]:
    """One string per page. An empty/near-empty string means no digital text layer
    (likely a scanned page) - that page needs the OCR path (ocr.py), not this one.
    """
    pages_text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
    return pages_text


def has_text_layer(page_text: str) -> bool:
    return len(page_text.strip()) >= MIN_CHARS_FOR_TEXT_LAYER
