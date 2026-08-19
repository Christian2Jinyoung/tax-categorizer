"""Batch-ingest every PDF receipt in a folder into one UploadBatch: extract -> categorize.

Usage:
    python scripts/ingest_folder.py <folder> [ruleset_name] [--limit N]

Example:
    python scripts/ingest_folder.py Costco_Receipts us_self_employed_schedule_c --limit 5
"""

import argparse
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
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("ruleset_name", nargs="?", default="us_self_employed_schedule_c")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N files (sorted by name)")
    args = parser.parse_args()

    folder = Path(args.folder)
    pdf_paths = sorted(folder.glob("*.pdf"))
    if args.limit:
        pdf_paths = pdf_paths[: args.limit]

    if not pdf_paths:
        print(f"No PDFs found in {folder}")
        return

    init_db()
    ruleset = load_ruleset(args.ruleset_name)

    with get_session() as session:
        batch = UploadBatch(ruleset_name=args.ruleset_name, status="processing")
        session.add(batch)
        session.commit()
        session.refresh(batch)

        totals = {"items": 0, "rule_match": 0, "claude": 0, "errors": 0, "needs_review": 0, "extraction_issues": 0}
        deductible_total = 0.0

        for pdf_path in pdf_paths:
            source_file = SourceFile(
                batch_id=batch.id,
                original_filename=pdf_path.name,
                stored_path=str(pdf_path),
                file_type="pdf",
            )
            session.add(source_file)
            session.commit()
            session.refresh(source_file)

            items = extract_pdf_line_items(str(pdf_path), batch.id, source_file.id)
            filename_info = parse_costco_filename(pdf_path.name)
            is_gas_purchase = bool(filename_info and filename_info["is_gas_purchase"])
            tag = " [GAS - filename override]" if is_gas_purchase else ""
            print(f"\n=== {pdf_path.name} ({len(items)} line items){tag} ===")

            for item in items:
                if item.vendor is None and item.amount is None:
                    totals["extraction_issues"] += 1
                    print(f"  EXTRACTION ISSUE: {item.rationale}")
                    session.add(item)
                    continue

                try:
                    if is_gas_purchase:
                        categorize_as_gas_purchase(item, ruleset)
                    else:
                        categorize_line_item(item, ruleset)
                except Exception as exc:  # noqa: BLE001 - batch run surfaces per-row failures without aborting
                    totals["errors"] += 1
                    print(f"  {item.description!r:35} ${item.amount:<10} -> ERROR: {exc}")
                    session.add(item)
                    continue

                totals["items"] += 1
                totals[item.categorization_method] = totals.get(item.categorization_method, 0) + 1
                if item.review_status == "needs_review":
                    totals["needs_review"] += 1
                if item.deductible and item.amount and item.deduction_pct:
                    deductible_total += item.amount * item.deduction_pct

                flag = " <- NEEDS REVIEW" if item.review_status == "needs_review" else ""
                print(
                    f"  {item.description!r:35} ${item.amount:<10} -> {item.category_label} "
                    f"(deductible={item.deductible}, method={item.categorization_method}){flag}"
                )
                session.add(item)

            source_file.extraction_status = "done"
            session.add(source_file)
            session.commit()

        batch.status = "complete" if totals["errors"] == 0 else "error"
        session.add(batch)
        session.commit()

        print("\n" + "=" * 100)
        print(f"Batch {batch.id} | {len(pdf_paths)} files | {totals['items']} categorized line items")
        print(
            f"rule_match: {totals.get('rule_match', 0)}   claude: {totals.get('claude', 0)}   "
            f"filename_override: {totals.get('filename_override', 0)}   errors: {totals['errors']}   "
            f"needs_review: {totals['needs_review']}   extraction_issues: {totals['extraction_issues']}"
        )
        print(f"Estimated deductible total (auto-categorized, pre-review): ${deductible_total:.2f}")


if __name__ == "__main__":
    main()
