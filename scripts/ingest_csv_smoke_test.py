"""Phase 1/2 smoke test: CSV ingestion -> rule engine -> Claude fallback, no web UI.

Usage:
    python scripts/ingest_csv_smoke_test.py [path/to/file.csv] [ruleset_name]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.categorization.pipeline import categorize_line_item
from app.categorization.ruleset_loader import load_ruleset
from app.db import get_session, init_db
from app.ingestion.pipeline import extract_spreadsheet_line_items
from app.models import SourceFile, UploadBatch


def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sample_transactions.csv"
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
            original_filename=Path(csv_path).name,
            stored_path=csv_path,
            file_type="csv",
        )
        session.add(source_file)
        session.commit()
        session.refresh(source_file)

        items = extract_spreadsheet_line_items(csv_path, "csv", batch.id, source_file.id)

        print(f"Batch {batch.id} | ruleset={ruleset_name} | {len(items)} line items")
        print("-" * 100)

        rule_matches = 0
        claude_calls = 0
        errors = 0
        for item in items:
            try:
                categorize_line_item(item, ruleset)
            except Exception as exc:  # noqa: BLE001 - smoke test surfaces any failure per row
                errors += 1
                print(f"[{item.date}] {item.vendor!r:30} ${item.amount:<10} -> ERROR: {exc}")
                session.add(item)
                continue

            if item.categorization_method == "rule_match":
                rule_matches += 1
            elif item.categorization_method == "claude":
                claude_calls += 1

            flag = " <- NEEDS REVIEW" if item.review_status == "needs_review" else ""
            print(
                f"[{item.date}] {item.vendor!r:30} ${item.amount:<10} "
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
        print(f"rule_match: {rule_matches}   claude: {claude_calls}   errors: {errors}")


if __name__ == "__main__":
    main()
