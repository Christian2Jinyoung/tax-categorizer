import re
from dataclasses import dataclass
from datetime import date as date_type
from typing import Optional

from dateutil import parser as dateutil_parser


@dataclass
class NormalizedFields:
    date: Optional[date_type]
    vendor: Optional[str]
    description: Optional[str]
    amount: Optional[float]
    raw_text: str
    quantity: int = 1


def parse_date(raw: Optional[str]) -> Optional[date_type]:
    if not raw or not str(raw).strip():
        return None
    try:
        return dateutil_parser.parse(str(raw), fuzzy=True).date()
    except (ValueError, OverflowError):
        return None


def parse_amount(raw: Optional[str]) -> Optional[float]:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text or text in {"-", "."}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return -abs(value) if negative else value


def parse_quantity(raw: Optional[str]) -> int:
    if not raw or not str(raw).strip():
        return 1
    match = re.search(r"\d+", str(raw))
    if not match:
        return 1
    return int(match.group())


def normalize_row(row: dict, mapping: dict[str, str | None]) -> NormalizedFields:
    def get(field: str) -> Optional[str]:
        col = mapping.get(field)
        return row.get(col) if col else None

    raw_text = ", ".join(f"{k}={v}" for k, v in row.items())

    return NormalizedFields(
        date=parse_date(get("date")),
        vendor=(get("vendor") or "").strip() or None,
        description=(get("description") or "").strip() or None,
        amount=parse_amount(get("amount")),
        raw_text=raw_text,
        quantity=parse_quantity(get("quantity")),
    )
