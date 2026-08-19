from datetime import datetime

from app.categorization.claude_categorize import categorize_with_claude
from app.categorization.rule_engine import match_line_item
from app.categorization.ruleset_schema import Ruleset
from app.config import settings
from app.models import LineItem


def categorize_line_item(item: LineItem, ruleset: Ruleset) -> None:
    """Mutates `item` in place with category/deductible/review fields.

    Rule engine runs first; only unmatched or requires-manual-review items reach Claude,
    which can itself flag needs_human_review instead of forcing a guess.
    """
    rule_match = match_line_item(item.vendor, item.description, ruleset)

    if rule_match is not None:
        category = rule_match.category
        item.category = category.id
        item.category_label = category.label
        item.deductible = category.deductible
        item.deduction_pct = category.deduction_pct
        item.categorization_method = "rule_match"
        item.categorization_confidence = 1.0
        item.matched_rule_id = category.id
        item.rationale = (
            f"Matched rule '{category.label}' on {rule_match.matched_field} keyword "
            f"'{rule_match.matched_keyword}'."
        )
        item.review_status = "auto_ok"
        item.updated_at = datetime.utcnow()
        return

    result = categorize_with_claude(item.vendor, item.description, item.amount, ruleset)

    if result.resolved_item_name:
        # Claude identified the real product behind a cryptic receipt code (directly or via
        # web search) - replace the abbreviation so the user sees the actual item, not
        # "1193179 KS SMALL **". The original stays in raw_text for reference.
        item.description = result.resolved_item_name

    item.category = result.category_id
    item.category_label = result.category_label
    item.deductible = result.deductible
    item.deduction_pct = result.deduction_pct
    item.categorization_method = "claude"
    item.categorization_confidence = result.confidence
    item.matched_rule_id = None
    item.rationale = result.rationale

    needs_review = result.needs_human_review or result.confidence < settings.categorization_confidence_threshold
    item.review_status = "needs_review" if needs_review else "auto_ok"
    item.updated_at = datetime.utcnow()


def categorize_as_gas_purchase(item: LineItem, ruleset: Ruleset) -> None:
    """Force-categorizes a line item as deductible vehicle fuel, bypassing the rule
    engine / Claude entirely.

    Used when an out-of-band signal (the Costco receipt filename's single-digit id)
    identifies the PDF as a gas-station receipt - the receipt content itself is just
    "Regular $23.15" with no useful description to categorize from, so the filename is
    the only reliable signal here.
    """
    category = ruleset.find_category("vehicle_fuel")

    item.category = category.id if category else "vehicle_fuel"
    item.category_label = category.label if category else "Vehicle Fuel (Business Use)"
    item.deductible = True
    item.deduction_pct = category.deduction_pct if category else 1.0
    item.categorization_method = "filename_override"
    item.categorization_confidence = 1.0
    item.matched_rule_id = category.id if category else None
    item.rationale = (
        "Costco gas-station receipt identified by filename (single-digit receipt id); "
        "treated as deductible vehicle fuel per user direction."
    )
    item.review_status = "auto_ok"
    item.updated_at = datetime.utcnow()
