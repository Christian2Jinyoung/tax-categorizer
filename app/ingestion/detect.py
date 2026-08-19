from pathlib import Path

CSV_EXTENSIONS = {".csv"}
XLSX_EXTENSIONS = {".xlsx", ".xls"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in CSV_EXTENSIONS:
        return "csv"
    if ext in XLSX_EXTENSIONS:
        return "xlsx"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    raise ValueError(f"Unsupported file type: {filename!r}")
