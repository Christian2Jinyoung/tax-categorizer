import pandas as pd

DATE_HEADER_HINTS = ["date", "transaction date", "posted"]
VENDOR_HEADER_HINTS = ["vendor", "merchant", "payee", "name"]
DESCRIPTION_HEADER_HINTS = ["description", "memo", "details", "notes"]
AMOUNT_HEADER_HINTS = ["amount", "total", "price", "debit", "cost"]
QUANTITY_HEADER_HINTS = ["quantity", "qty", "units", "count"]


def _best_column(columns: list[str], hints: list[str]) -> str | None:
    lowered = {c: c.strip().lower() for c in columns}
    for hint in hints:
        for col, low in lowered.items():
            if low == hint:
                return col
    for hint in hints:
        for col, low in lowered.items():
            if hint in low:
                return col
    return None


def read_spreadsheet(path: str, file_type: str) -> pd.DataFrame:
    if file_type == "csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    if file_type == "xlsx":
        return pd.read_excel(path, dtype=str)
    raise ValueError(f"read_spreadsheet does not support file_type={file_type!r}")


def guess_column_mapping(df: pd.DataFrame) -> dict[str, str | None]:
    columns = list(df.columns)
    return {
        "date": _best_column(columns, DATE_HEADER_HINTS),
        "vendor": _best_column(columns, VENDOR_HEADER_HINTS),
        "description": _best_column(columns, DESCRIPTION_HEADER_HINTS),
        "amount": _best_column(columns, AMOUNT_HEADER_HINTS),
        "quantity": _best_column(columns, QUANTITY_HEADER_HINTS),
    }
