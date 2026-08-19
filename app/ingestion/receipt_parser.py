import re
from datetime import date as date_type
from typing import Optional

from app.ingestion.normalize import NormalizedFields, parse_amount, parse_date

# Trailing "-" is a common POS/accounting negative notation (e.g. Costco discounts: "4.00-").
AMOUNT_PATTERN = re.compile(r"-?\$?\d{1,3}(?:,\d{3})*\.\d{2}-?")
DATE_PATTERN = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")

# Lines containing these are receipt totals/tender/boilerplate, not purchased items.
NON_ITEM_KEYWORDS = [
    "subtotal", "sub total", "sub-total", "tax", "total", "balance due", "amount due",
    "amount:", "change due", "cash tendered", "cash back", "visa", "mastercard", "debit",
    "credit card", "tender", "member", "thank you", "receipt", "www.", "http",
    "customer copy", "approval", "approved", "auth code", "sequence", "terminal",
    "card #", "account #", "items sold", "instant savings",
]

# A browser "print to PDF" of a web page (e.g. costco.com/myaccount order history)
# stamps every page with a date/time header and a URL footer - neither is receipt
# content, and the header's print timestamp would otherwise get mistaken for the
# purchase date or the vendor name.
BOILERPLATE_LINE_PATTERNS = [
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}\s*(AM|PM)", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
]

# Browser print headers commonly follow "<Page Title> | <Site Name>" (from the page's
# <title> tag) - e.g. "Orders & Purchases | Costco". That site name is a much more
# reliable vendor signal than guessing from the first content line, which for a printed
# web receipt is often just a store/warehouse code (e.g. "W KATY #1167").
PRINT_HEADER_SITE_NAME_PATTERN = re.compile(
    r"\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}\s*(AM|PM).*\|\s*(?P<site>[A-Za-z0-9&.,'\- ]+?)\s*$",
    re.IGNORECASE,
)

# Coupon/instant-savings adjustment lines reference another item's code rather than
# describing a purchase, e.g. "370328 / 993467  3.10-" or "366876 /BRUSHHEADS  15.00-"
# (the second form uses a text label instead of a code, so it isn't caught by a
# no-letters-in-description check alone). The structural tell is a line that *starts*
# with digits immediately followed by a "/".
ADJUSTMENT_LINE_PATTERN = re.compile(r"^\d+\s*/\s*\S")

# Costco's per-transaction tax-category summary/legend line, e.g. "(A) A  7.99".
TAX_CATEGORY_SUMMARY_PATTERN = re.compile(r"^\([A-Z]\)\s+[A-Z]\b")

# Payment-tender / rewards lines, e.g. "SHOP CARD 97.38", "CASH 231.97-", "2% REBATE
# 279.70" - structural match (tender-name then amount, nothing else) rather than a loose
# keyword, since a bare "cash" keyword would false-positive on a real item like "KS
# CASHEWS". "visa"/"debit" tender lines are already caught by NON_ITEM_KEYWORDS.
TENDER_LINE_PATTERN = re.compile(
    r"^(cash|shop card|2% rebate|change)\s+[\d,]+\.\d{2}-?$", re.IGNORECASE
)

# A lone all-caps word with no digits/amount, used to reconstruct an item description
# that got word-wrapped around its code+price line (see _backfill_wrapped_description).
ORPHAN_TEXT_LINE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s]*$")

# An item description that's just its product code with nothing descriptive, e.g.
# "E 1048072" or "F 1532504" (the leading letter is a taxability/department code).
CODE_ONLY_DESCRIPTION_PATTERN = re.compile(r"^([A-Z]\s*)?\d+$")

# Costco prints a "<qty> @ <unit price>" line immediately BEFORE an item line when more
# than one unit was bought, e.g. "2 @ 10.49" followed by "393914 KS VIT D3 20.98N" - the
# item's own printed amount is the extended total (2 x 10.49 = 20.98), not a unit price.
QUANTITY_MODIFIER_PATTERN = re.compile(r"^(?P<qty>\d+)\s*@\s*\d")

# Fallback vendor signal for receipts with no browser print-header (e.g. Costco's
# dedicated gas-station receipt template just says "Gas Station Receipt" / "Visit
# Costco.com" - no "Page Title | Site" line to pull a vendor from).
KNOWN_VENDOR_HINTS = ["costco"]


def _is_boilerplate_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in BOILERPLATE_LINE_PATTERNS)


def _detect_vendor_from_known_hints(lines: list[str]) -> Optional[str]:
    for line in lines:
        lowered = line.lower()
        for hint in KNOWN_VENDOR_HINTS:
            if hint in lowered:
                return hint.capitalize()
    return None


def _is_adjustment_line(line: str) -> bool:
    return bool(ADJUSTMENT_LINE_PATTERN.match(line))


def _is_orphan_text_line(line: str) -> bool:
    if len(line) > 24 or not ORPHAN_TEXT_LINE_PATTERN.match(line):
        return False
    lowered = line.lower()
    return not any(kw in lowered for kw in NON_ITEM_KEYWORDS)


def _detect_vendor_from_print_header(lines: list[str]) -> Optional[str]:
    for line in lines:
        match = PRINT_HEADER_SITE_NAME_PATTERN.search(line)
        if match:
            site = match.group("site").strip()
            if site:
                return site
    return None


def _looks_like_item_line(line: str) -> bool:
    if _is_adjustment_line(line) or TAX_CATEGORY_SUMMARY_PATTERN.match(line) or TENDER_LINE_PATTERN.match(line):
        return False
    lowered = line.lower()
    if any(kw in lowered for kw in NON_ITEM_KEYWORDS):
        return False
    return bool(AMOUNT_PATTERN.search(line))


def _find_receipt_date(lines: list[str]) -> Optional[date_type]:
    for line in lines:
        match = DATE_PATTERN.search(line)
        if match:
            parsed = parse_date(match.group())
            if parsed:
                return parsed
    return None


def _extract_amount(raw_match: str) -> Optional[float]:
    text = raw_match.strip()
    trailing_negative = text.endswith("-")
    if trailing_negative:
        text = text[:-1]
    value = parse_amount(text)
    if value is None:
        return None
    return -abs(value) if trailing_negative else value


def parse_receipt_text(text: str) -> tuple[Optional[str], Optional[date_type], list[NormalizedFields]]:
    """Best-effort generic receipt/invoice parser: first non-boilerplate line is treated
    as the vendor, any date-shaped token as the receipt date, and any remaining line that
    contains a dollar amount and isn't a subtotal/tax/tender/adjustment line becomes a
    line item.

    This is a heuristic, not a guaranteed-correct parser - it works reasonably across
    varied receipt layouts (Costco, generic invoices, etc.) but will occasionally miss
    or misfire on unusual formats. Those cases surface as items with rationale-worthy
    ambiguity for the categorization step, or empty results the pipeline flags for
    manual review.
    """
    all_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in all_lines if not _is_boilerplate_line(line)]
    if not lines:
        return None, None, []

    vendor = (
        _detect_vendor_from_print_header(all_lines)
        or _detect_vendor_from_known_hints(all_lines)
        or lines[0]
    )
    receipt_date = _find_receipt_date(lines)

    items: list[NormalizedFields] = []
    for idx, line in enumerate(lines):
        if not _looks_like_item_line(line):
            continue
        match = AMOUNT_PATTERN.search(line)
        if not match:
            continue
        description = line[: match.start()].strip(" .-\t")
        if not description or not re.search(r"[A-Za-z]", description):
            # No letters in the description means this is a reference/adjustment code
            # line (e.g. Costco's "368941 /1736931 4.00-" instant-savings coupon line
            # tied to another item), not an actual purchased item.
            continue

        if CODE_ONLY_DESCRIPTION_PATTERN.match(description):
            # Some receipts word-wrap a long description around the code+price line,
            # e.g. "GREEK" / "E 1048072  6.99 N" / "YOGURT". Pull in adjacent orphan
            # text-only lines so the description isn't just the bare item code.
            before = lines[idx - 1] if idx > 0 else None
            after = lines[idx + 1] if idx + 1 < len(lines) else None
            wrap_parts = [p for p in (before, after) if p and _is_orphan_text_line(p)]
            if wrap_parts:
                description = f"{' '.join(wrap_parts)} ({description})"

        quantity = 1
        if idx > 0:
            qty_match = QUANTITY_MODIFIER_PATTERN.match(lines[idx - 1])
            if qty_match:
                quantity = int(qty_match.group("qty"))

        items.append(
            NormalizedFields(
                date=receipt_date,
                vendor=vendor,
                description=description,
                amount=_extract_amount(match.group()),
                raw_text=line,
                quantity=quantity,
            )
        )
    return vendor, receipt_date, items
