from sqlmodel import Session, select

from app.models import LineItem


def assign_item_uid(session: Session, item: LineItem) -> None:
    """Assigns a stable, human-readable id "{date}_{n}", unique across the whole
    database (not just this batch), so the same purchase re-ingested in a later
    batch is easy to spot in the export spreadsheet and same-day items get distinct
    rows.

    Must be called after `item.date` is set and after `session.add(item)` - the
    count query below relies on autoflush to see items already staged earlier in
    this same batch.
    """
    date_key = item.date.isoformat() if item.date else "unknown"
    prefix = f"{date_key}_"
    existing = session.exec(select(LineItem.item_uid).where(LineItem.item_uid.like(f"{prefix}%"))).all()
    item.item_uid = f"{prefix}{len(existing) + 1}"
