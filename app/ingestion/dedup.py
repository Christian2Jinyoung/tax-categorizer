from typing import Optional

from sqlmodel import Session, select

from app.models import SourceFile


def find_previous_ingestion(session: Session, original_filename: str, exclude_batch_id: int) -> Optional[SourceFile]:
    """Returns a previously successfully-ingested SourceFile with the same original
    filename from a different batch, if any.

    Costco's exported receipt filenames encode a unique receipt id
    ("Costco_MM-DD_<receipt id>.pdf"), so the same filename showing up again means
    the same purchase - this lets folder re-ingestion (and accidental re-uploads) be
    idempotent instead of double-counting line items.
    """
    return session.exec(
        select(SourceFile).where(
            SourceFile.original_filename == original_filename,
            SourceFile.extraction_status == "done",
            SourceFile.batch_id != exclude_batch_id,
        )
    ).first()
