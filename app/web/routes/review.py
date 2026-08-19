from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlmodel import select

from app.categorization.ruleset_loader import load_ruleset
from app.db import get_session
from app.models import LineItem, UploadBatch

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/review/{batch_id}")
def review_page(request: Request, batch_id: int, filter: str = "all"):
    with get_session() as session:
        batch = session.get(UploadBatch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        ruleset = load_ruleset(batch.ruleset_name)
        items = session.exec(
            select(LineItem).where(LineItem.batch_id == batch_id).order_by(LineItem.id)
        ).all()

    if filter == "needs_review":
        items = [item for item in items if item.review_status == "needs_review"]

    deductible_total = sum((item.amount or 0) * (item.deduction_pct or 0) for item in items if item.deductible)

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "batch": batch,
            "items": items,
            "categories": ruleset.categories,
            "filter": filter,
            "deductible_total": deductible_total,
        },
    )


@router.post("/review/item/{item_id}/override")
def override_item(
    request: Request,
    item_id: int,
    category_id: str = Form(...),
    deductible: bool = Form(False),
    deduction_pct: float = Form(0.0),
):
    with get_session() as session:
        item = session.get(LineItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Line item not found")
        batch = session.get(UploadBatch, item.batch_id)
        ruleset = load_ruleset(batch.ruleset_name)
        category = ruleset.find_category(category_id)

        item.category = category_id
        item.category_label = category.label if category else category_id
        item.deductible = deductible
        item.deduction_pct = deduction_pct
        item.categorization_method = "manual_override"
        item.categorization_confidence = 1.0
        item.matched_rule_id = None
        item.rationale = "Manually set by user during review."
        item.review_status = "reviewed_overridden"
        item.reviewed_at = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
        categories = ruleset.categories

    return templates.TemplateResponse(
        request, "partials/review_row.html", {"item": item, "categories": categories}
    )


@router.post("/review/item/{item_id}/confirm")
def confirm_item(request: Request, item_id: int):
    with get_session() as session:
        item = session.get(LineItem, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Line item not found")
        batch = session.get(UploadBatch, item.batch_id)
        ruleset = load_ruleset(batch.ruleset_name)

        item.review_status = "reviewed_confirmed"
        item.reviewed_at = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
        categories = ruleset.categories

    return templates.TemplateResponse(
        request, "partials/review_row.html", {"item": item, "categories": categories}
    )
