from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select

from app.categorization.ruleset_loader import list_rulesets
from app.config import PROJECT_ROOT, settings
from app.db import get_session
from app.ingestion.detect import detect_file_type
from app.models import LineItem, SourceFile, UploadBatch
from app.web.processing import process_batch

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

INGESTIBLE_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf"}


@router.get("/")
def upload_form(request: Request, error: Optional[str] = None):
    with get_session() as session:
        recent_batches = session.exec(
            select(UploadBatch).order_by(UploadBatch.created_at.desc()).limit(10)
        ).all()
        total_items = session.exec(
            select(LineItem.id).where(LineItem.vendor.is_not(None), LineItem.amount.is_not(None))
        ).all()
    return templates.TemplateResponse(
        request,
        "upload.html",
        {
            "rulesets": list_rulesets(),
            "default_ruleset": settings.default_ruleset,
            "recent_batches": recent_batches,
            "default_folder": "Costco_Receipts",
            "total_item_count": len(total_items),
            "error": error,
        },
    )


@router.post("/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    ruleset_name: str = Form(...),
    files: list[UploadFile] = File(...),
):
    with get_session() as session:
        batch = UploadBatch(ruleset_name=ruleset_name, status="pending")
        session.add(batch)
        session.commit()
        session.refresh(batch)

        batch_dir = settings.upload_dir_abs / str(batch.id)
        batch_dir.mkdir(parents=True, exist_ok=True)

        for upload_file in files:
            if not upload_file.filename:
                continue
            try:
                file_type = detect_file_type(upload_file.filename)
            except ValueError:
                file_type = "unsupported"

            dest_path = batch_dir / upload_file.filename
            contents = await upload_file.read()
            dest_path.write_bytes(contents)

            session.add(
                SourceFile(
                    batch_id=batch.id,
                    original_filename=upload_file.filename,
                    stored_path=str(dest_path),
                    file_type=file_type,
                )
            )
        session.commit()
        batch_id = batch.id

    background_tasks.add_task(process_batch, batch_id)
    return RedirectResponse(url=f"/status/{batch_id}", status_code=303)


@router.post("/ingest-folder")
def ingest_folder(
    background_tasks: BackgroundTasks,
    ruleset_name: str = Form(...),
    folder_path: str = Form(...),
):
    """Points at a folder already on disk (e.g. where you saved a batch of Costco
    receipt PDFs) and processes every file in it directly, in place - no browser
    file picker needed. Already-ingested files (same filename as a prior batch) are
    skipped automatically by process_batch()'s dedup check, so re-running this on a
    folder you keep adding new receipts to only processes what's new.
    """
    folder = Path(folder_path)
    if not folder.is_absolute():
        folder = PROJECT_ROOT / folder

    if not folder.is_dir():
        return RedirectResponse(url=f"/?error=Folder not found: {folder}", status_code=303)

    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in INGESTIBLE_EXTENSIONS)
    if not paths:
        return RedirectResponse(url=f"/?error=No CSV/XLSX/PDF files found in {folder}", status_code=303)

    with get_session() as session:
        batch = UploadBatch(ruleset_name=ruleset_name, status="pending")
        session.add(batch)
        session.commit()
        session.refresh(batch)

        for path in paths:
            session.add(
                SourceFile(
                    batch_id=batch.id,
                    original_filename=path.name,
                    stored_path=str(path.resolve()),
                    file_type=detect_file_type(path.name),
                )
            )
        session.commit()
        batch_id = batch.id

    background_tasks.add_task(process_batch, batch_id)
    return RedirectResponse(url=f"/status/{batch_id}", status_code=303)
