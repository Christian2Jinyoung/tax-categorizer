"""Phase 5 smoke test: digital-PDF ingestion -> rule engine -> Claude fallback.

Usage:
    python scripts/ingest_pdf_smoke_test.py [path/to/receipt.pdf] [ruleset_name]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.categorization.pipeline import categorize_as_gas_purchase, categorize_line_item
from app.categorization.ruleset_loader import load_ruleset
from app.db import get_session, init_db
from app.ingestion.costco_filename import parse_costco_filename
from app.ingestion.pipeline import extract_pdf_line_items
from app.models import SourceFile, UploadBatch


def main() -> None:
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_receipt.pdf"
    ruleset_name = sys.argv[2] if len(sys.argv) > 2 else "us_self_employed_schedule_c"

    init_db()
    ruleset = load_ruleset(ruleset_name)

    with get_session() as session:
        batch = UploadBatch(ruleset_name=ruleset_name, status="processing")
        session.add(batch)
        session.commit()
        session.refresh(batch)

        source_file = SourceFile(
            batch_id=batch.id,
            original_filename=Path(pdf_path).name,
            stored_path=pdf_path,
            file_type="pdf",
        )
        session.add(source_file)
        session.commit()
        session.refresh(source_file)

        items = extract_pdf_line_items(pdf_path, batch.id, source_file.id)
        filename_info = parse_costco_filename(Path(pdf_path).name)
        is_gas_purchase = bool(filename_info and filename_info["is_gas_purchase"])

        print(f"Batch {batch.id} | ruleset={ruleset_name} | {len(items)} line items extracted from {pdf_path}")
        if is_gas_purchase:
            print("(filename indicates a gas-station receipt - categorization will be overridden)")
        print("-" * 100)

        rule_matches = 0
        claude_calls = 0
        filename_overrides = 0
        errors = 0
        needs_review_extraction = 0
        for item in items:
            if item.vendor is None and item.amount is None:
                # extraction-stage placeholder (no text layer / no parsed items) - nothing to categorize
                needs_review_extraction += 1
                print(f"[page {item.row_index}] EXTRACTION ISSUE: {item.rationale}")
                session.add(item)
                continue

            try:
                if is_gas_purchase:
                    categorize_as_gas_purchase(item, ruleset)
                else:
                    categorize_line_item(item, ruleset)
            except Exception as exc:  # noqa: BLE001 - smoke test surfaces any failure per row
                errors += 1
                print(f"{item.vendor!r:20} | {item.description!r:35} ${item.amount:<10} -> ERROR: {exc}")
                session.add(item)
                continue

            if item.categorization_method == "rule_match":
                rule_matches += 1
            elif item.categorization_method == "claude":
                claude_calls += 1
            elif item.categorization_method == "filename_override":
                filename_overrides += 1

            flag = " <- NEEDS REVIEW" if item.review_status == "needs_review" else ""
            print(
                f"{item.description!r:35} ${item.amount:<10} "
                f"-> {item.category_label} (deductible={item.deductible}, pct={item.deduction_pct}, "
                f"method={item.categorization_method}, conf={item.categorization_confidence}){flag}"
            )
            print(f"    rationale: {item.rationale}")
            session.add(item)

        source_file.extraction_status = "done"
        batch.status = "complete" if errors == 0 else "error"
        session.add(source_file)
        session.add(batch)
        session.commit()

        print("-" * 100)
        print(
            f"rule_match: {rule_matches}   claude: {claude_calls}   filename_override: {filename_overrides}   "
            f"errors: {errors}   extraction_issues: {needs_review_extraction}"
        )


if __name__ == "__main__":
    main()
