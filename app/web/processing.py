from pathlib import Path

from sqlmodel import select

from app.categorization.pipeline import categorize_as_gas_purchase, categorize_line_item
from app.categorization.ruleset_loader import load_ruleset
from app.db import get_session
from app.ingestion.costco_filename import parse_costco_filename
from app.ingestion.dedup import find_previous_ingestion
from app.ingestion.item_uid import assign_item_uid
from app.ingestion.pipeline import extract_pdf_line_items, extract_spreadsheet_line_items
from app.models import LineItem, SourceFile, UploadBatch


def _extract_items(source_file: SourceFile, batch_id: int) -> list[LineItem]:
    if source_file.file_type in ("csv", "xlsx"):
        return extract_spreadsheet_line_items(
            source_file.stored_path, source_file.file_type, batch_id, source_file.id
        )
    if source_file.file_type == "pdf":
        return extract_pdf_line_items(source_file.stored_path, batch_id, source_file.id)
    if source_file.file_type == "image":
        raise NotImplementedError(
            "Image OCR isn't implemented yet - please upload a PDF or CSV/XLSX file instead."
        )
    raise ValueError(f"Unsupported file type: {source_file.file_type}")


def process_batch(batch_id: int) -> None:
    """Runs as a FastAPI BackgroundTask after /upload: extract -> categorize every
    source file in the batch, then mark it complete. Per-file and per-item failures
    are captured on the row rather than aborting the whole batch, mirroring the CLI
    smoke-test scripts' behavior.
    """
    with get_session() as session:
        batch = session.get(UploadBatch, batch_id)
        if batch is None:
            return

        ruleset = load_ruleset(batch.ruleset_name)
        batch.status = "processing"
        session.add(batch)
        session.commit()

        any_file_errors = False
        source_files = session.exec(select(SourceFile).where(SourceFile.batch_id == batch_id)).all()

        for source_file in source_files:
            duplicate_of = find_previous_ingestion(session, source_file.original_filename, batch_id)
            if duplicate_of is not None:
                source_file.extraction_status = "skipped_duplicate"
                source_file.error_message = (
                    f"Already ingested in batch #{duplicate_of.batch_id} (source file #{duplicate_of.id})"
                )
                session.add(source_file)
                session.commit()
                continue

            try:
                items = _extract_items(source_file, batch_id)
            except Exception as exc:  # noqa: BLE001 - surfaced on the file row, batch continues
                source_file.extraction_status = "error"
                source_file.error_message = str(exc)
                any_file_errors = True
                session.add(source_file)
                session.commit()
                continue

            filename_info = parse_costco_filename(Path(source_file.original_filename).name)
            is_gas_purchase = bool(filename_info and filename_info["is_gas_purchase"])

            for item in items:
                if item.vendor is None and item.amount is None:
                    # extraction-stage placeholder (no text layer / no parsed items)
                    session.add(item)
                    continue

                item.abbreviated_description = item.description
                session.add(item)
                assign_item_uid(session, item)

                try:
                    if is_gas_purchase:
                        categorize_as_gas_purchase(item, ruleset)
                    else:
                        categorize_line_item(item, ruleset)
                except Exception as exc:  # noqa: BLE001 - keep the row, flag it for review
                    item.review_status = "needs_review"
                    item.rationale = f"Categorization error: {exc}"
                session.add(item)

            source_file.extraction_status = "done"
            session.add(source_file)
            session.commit()

        batch.status = "error" if any_file_errors else "complete"
        session.add(batch)
        session.commit()
