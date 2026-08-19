import io

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl.utils import get_column_letter
from sqlmodel import select

from app.config import PROJECT_ROOT
from app.db import get_session
from app.models import LineItem, SourceFile, UploadBatch

router = APIRouter()

# Per-column Excel number formats, applied wherever a sheet has one of these headers.
COLUMN_NUMBER_FORMATS = {
    "Date": "mm/dd/yyyy",
    "Price": '"$"#,##0.00',
    "Deduction %": "0%",
}
MAX_COLUMN_WIDTH = 60


def _write_sheet(writer, df: pd.DataFrame, sheet_name: str) -> None:
    """Writes df to the workbook, then widens every column to fit its content and
    applies currency/date/percent formatting to columns named in COLUMN_NUMBER_FORMATS.
    """
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    worksheet = writer.sheets[sheet_name]

    for col_idx, column_name in enumerate(df.columns, start=1):
        col_letter = get_column_letter(col_idx)
        cell_lengths = [len(str(v)) for v in df[column_name]] if len(df) else []
        width = max([len(str(column_name)), *cell_lengths]) + 2
        worksheet.column_dimensions[col_letter].width = min(width, MAX_COLUMN_WIDTH)

        number_format = COLUMN_NUMBER_FORMATS.get(column_name)
        if number_format:
            for row_idx in range(2, len(df) + 2):  # row 1 is the header
                worksheet.cell(row=row_idx, column=col_idx).number_format = number_format

# Every export is also written here as a standing copy on disk, in addition to the
# browser download - contains real purchase data, so it's gitignored (see .gitignore).
EXPORT_DIR = PROJECT_ROOT / "app" / "export"


def _save_export_copy(buffer: io.BytesIO, filename: str) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPORT_DIR / filename).write_bytes(buffer.getvalue())


def _source_filenames(session, items: list[LineItem]) -> dict[int, str]:
    source_file_ids = {item.source_file_id for item in items}
    if not source_file_ids:
        return {}
    rows = session.exec(
        select(SourceFile.id, SourceFile.original_filename).where(SourceFile.id.in_(source_file_ids))
    ).all()
    return dict(rows)


@router.get("/export/{batch_id}.csv")
def export_csv(batch_id: int):
    with get_session() as session:
        batch = session.get(UploadBatch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        items = session.exec(
            select(LineItem).where(LineItem.batch_id == batch_id).order_by(LineItem.id)
        ).all()

    rows = [
        {
            "Date": item.date,
            "Vendor": item.vendor,
            "Description": item.description,
            "Amount": item.amount,
            "Category": item.category_label,
            "Deductible": item.deductible,
            "Deduction %": item.deduction_pct,
            "Deductible Amount": (item.amount or 0) * (item.deduction_pct or 0) if item.deductible else 0,
            "Method": item.categorization_method,
            "Confidence": item.categorization_confidence,
            "Rationale": item.rationale,
            "Review Status": item.review_status,
        }
        for item in items
    ]
    df = pd.DataFrame(rows)
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)

    filename = f"tax_categorizer_batch_{batch_id}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# The primary sheet for manual review: every real line item, regardless of what (if
# anything) the categorizer decided about deductibility - the point is the user checks
# each one themselves rather than trusting an auto-generated Deductible/Not-Deductible split.
ALL_ITEMS_COLUMNS = [
    "Item UID", "Date", "Full Name", "Abbreviated Name (Receipt)", "Quantity", "Price", "Source File",
]


def _all_items_row(item: LineItem, source_filenames: dict[int, str]) -> dict:
    return {
        "Item UID": item.item_uid,
        "Date": item.date,
        "Full Name": item.description,
        "Abbreviated Name (Receipt)": item.abbreviated_description,
        "Quantity": item.quantity or 1,
        "Price": item.amount,
        "Source File": source_filenames.get(item.source_file_id),
    }


def _all_items_sheet(items: list[LineItem], source_filenames: dict[int, str]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=ALL_ITEMS_COLUMNS)
    return pd.DataFrame([_all_items_row(item, source_filenames) for item in items], columns=ALL_ITEMS_COLUMNS)


SPREADSHEET_COLUMNS = [
    "Item UID", "Date", "Full Name", "Abbreviated Name (Receipt)", "Quantity", "Price", "Vendor",
    "Category", "Deduction %", "Needs Review", "Method", "Rationale", "Source File",
]


def _spreadsheet_row(item: LineItem, source_filenames: dict[int, str]) -> dict:
    return {
        "Item UID": item.item_uid,
        "Date": item.date,
        "Full Name": item.description,
        "Abbreviated Name (Receipt)": item.abbreviated_description,
        "Quantity": item.quantity or 1,
        "Price": item.amount,
        "Vendor": item.vendor,
        "Category": item.category_label,
        "Deduction %": item.deduction_pct,
        "Needs Review": item.review_status == "needs_review",
        "Method": item.categorization_method,
        "Rationale": item.rationale,
        "Source File": source_filenames.get(item.source_file_id),
    }


def _spreadsheet_sheet(items: list[LineItem], source_filenames: dict[int, str]) -> pd.DataFrame:
    if not items:
        return pd.DataFrame(columns=SPREADSHEET_COLUMNS)
    return pd.DataFrame([_spreadsheet_row(item, source_filenames) for item in items], columns=SPREADSHEET_COLUMNS)


def _build_workbook(items: list[LineItem], source_filenames: dict[int, str]) -> io.BytesIO:
    """The final spreadsheet. Leads with "All Items" - every real line item with its full
    resolved name, its original receipt abbreviation, quantity, price, date, and source
    receipt file, with no deductible/not-deductible judgment baked in, for manual review.
    The categorizer's own Tax Deductible / Not Deductible / Uncategorized split follows for
    reference.
    """
    all_items = [item for item in items if not (item.vendor is None and item.amount is None)]
    deductible = [item for item in items if item.deductible is True]
    non_deductible = [item for item in items if item.deductible is False]
    uncategorized = [item for item in items if item.deductible is None]
    deductible_total = sum((item.amount or 0) * (item.deduction_pct or 0) for item in deductible)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _write_sheet(writer, _all_items_sheet(all_items, source_filenames), "All Items")
        _write_sheet(
            writer,
            pd.DataFrame(
                [
                    {"Metric": "Total line items", "Value": len(all_items)},
                    {"Metric": "Deductible line items (per agent)", "Value": len(deductible)},
                    {"Metric": "Non-deductible line items (per agent)", "Value": len(non_deductible)},
                    {"Metric": "Uncategorized / extraction issues", "Value": len(uncategorized)},
                    {"Metric": "Estimated deductible total (per agent)", "Value": round(deductible_total, 2)},
                ]
            ),
            "Summary",
        )
        _write_sheet(writer, _spreadsheet_sheet(deductible, source_filenames), "Tax Deductible")
        _write_sheet(writer, _spreadsheet_sheet(non_deductible, source_filenames), "Not Deductible")
        if uncategorized:
            _write_sheet(writer, _spreadsheet_sheet(uncategorized, source_filenames), "Uncategorized")
    buffer.seek(0)
    return buffer


@router.get("/export/all.xlsx")
def export_all_xlsx():
    """Spans every batch ever ingested, not just one run. Ingestion already dedups by
    filename (a receipt already processed in an earlier batch is skipped, not reprocessed),
    so every real item exists exactly once in the database - this just stops the export
    from being limited to whichever single batch you happen to be looking at.

    Registered before the /export/{batch_id}.xlsx route below: FastAPI matches path
    routes in registration order, and "all" isn't a valid int batch_id, so this specific
    route must come first or every request here 422s trying to parse "all" as an int.
    """
    with get_session() as session:
        items = session.exec(select(LineItem).order_by(LineItem.date, LineItem.item_uid)).all()
        source_filenames = _source_filenames(session, items)

    buffer = _build_workbook(items, source_filenames)
    _save_export_copy(buffer, "tax_categorizer_all_items.xlsx")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tax_categorizer_all_items.xlsx"'},
    )


@router.get("/export/{batch_id}.xlsx")
def export_xlsx(batch_id: int):
    with get_session() as session:
        batch = session.get(UploadBatch, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Batch not found")
        items = session.exec(
            select(LineItem).where(LineItem.batch_id == batch_id).order_by(LineItem.id)
        ).all()
        source_filenames = _source_filenames(session, items)

    buffer = _build_workbook(items, source_filenames)
    filename = f"tax_categorizer_batch_{batch_id}.xlsx"
    _save_export_copy(buffer, filename)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
