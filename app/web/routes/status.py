from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import select

from app.db import get_session
from app.models import LineItem, SourceFile, UploadBatch

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _batch_context(batch_id: int) -> Optional[dict]:
    with get_session() as session:
        batch = session.get(UploadBatch, batch_id)
        if batch is None:
            return None
        source_files = session.exec(select(SourceFile).where(SourceFile.batch_id == batch_id)).all()
        item_count = len(session.exec(select(LineItem.id).where(LineItem.batch_id == batch_id)).all())
        needs_review_count = len(
            session.exec(
                select(LineItem.id).where(
                    LineItem.batch_id == batch_id, LineItem.review_status == "needs_review"
                )
            ).all()
        )
    return {
        "batch": batch,
        "source_files": source_files,
        "item_count": item_count,
        "needs_review_count": needs_review_count,
    }


@router.get("/status/{batch_id}")
def status_page(request: Request, batch_id: int):
    ctx = _batch_context(batch_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return templates.TemplateResponse(request, "status.html", ctx)


@router.get("/status/{batch_id}/partial")
def status_partial(request: Request, batch_id: int):
    ctx = _batch_context(batch_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return templates.TemplateResponse(request, "partials/status_partial.html", ctx)
