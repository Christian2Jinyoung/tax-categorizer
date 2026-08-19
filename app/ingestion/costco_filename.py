import re
from pathlib import Path
from typing import Optional, TypedDict

# "Costco_MM-DD_<receipt id>.pdf" - a 23-digit id is a normal in-warehouse/online
# purchase; a single-digit id (per the user) is a Costco Gas Station purchase.
COSTCO_FILENAME_PATTERN = re.compile(r"^Costco_(?P<month>\d{2})-(?P<day>\d{2})_(?P<receipt_id>\d+)$")


class CostcoFilenameInfo(TypedDict):
    month: int
    day: int
    receipt_id: str
    is_gas_purchase: bool


def parse_costco_filename(filename: str) -> Optional[CostcoFilenameInfo]:
    stem = Path(filename).stem
    match = COSTCO_FILENAME_PATTERN.match(stem)
    if not match:
        return None
    receipt_id = match.group("receipt_id")
    return {
        "month": int(match.group("month")),
        "day": int(match.group("day")),
        "receipt_id": receipt_id,
        "is_gas_purchase": len(receipt_id) == 1,
    }
