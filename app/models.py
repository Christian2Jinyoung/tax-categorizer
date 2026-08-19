from __future__ import annotations

from datetime import datetime, date as date_type
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.utcnow()


class UploadBatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    ruleset_name: str
    status: str = Field(default="pending")  # pending | processing | complete | error
    error_message: Optional[str] = None


class SourceFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="uploadbatch.id")
    original_filename: str
    stored_path: str
    file_type: str  # csv | xlsx | pdf | image
    extraction_status: str = Field(default="pending")  # pending | done | error | skipped_duplicate
    error_message: Optional[str] = None


class LineItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Lineage
    batch_id: int = Field(foreign_key="uploadbatch.id")
    source_file_id: int = Field(foreign_key="sourcefile.id")
    row_index: Optional[int] = None
    raw_text: Optional[str] = None

    # Extraction
    extraction_method: str  # csv_direct | xlsx_direct | pdf_text_layer | ocr_tesseract | claude_repair
    extraction_confidence: Optional[float] = None

    # Parsed fields
    date: Optional[date_type] = None
    vendor: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    currency: str = Field(default="USD")
    quantity: Optional[int] = None

    # The description exactly as printed/parsed from the receipt (e.g. "1193179 KS SMALL
    # **"), captured before categorization may overwrite `description` with a Claude-resolved
    # full product name. Lets the export show both side by side.
    abbreviated_description: Optional[str] = None

    # Human-readable unique id, "{date}_{n}", assigned globally (across all batches)
    # so the same purchase re-ingested twice is easy to spot and the export spreadsheet
    # has a stable per-row identifier.
    item_uid: Optional[str] = Field(default=None, index=True)

    # Categorization
    category: Optional[str] = None
    category_label: Optional[str] = None
    deductible: Optional[bool] = None
    deduction_pct: Optional[float] = None
    categorization_method: Optional[str] = None  # rule_match | claude | manual_override
    categorization_confidence: Optional[float] = None
    rationale: Optional[str] = None
    matched_rule_id: Optional[str] = None

    # Review workflow
    review_status: str = Field(default="auto_ok")  # auto_ok | needs_review | reviewed_confirmed | reviewed_overridden
    reviewed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
