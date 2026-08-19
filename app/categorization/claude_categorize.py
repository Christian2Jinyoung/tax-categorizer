from typing import Optional

from pydantic import BaseModel, Field

from app.categorization.ruleset_schema import Ruleset
from app.config import settings
from app.llm.client import get_anthropic_client

# web_search is a server-side tool - Claude searches and reads results within the same
# API call (no client-side loop needed). Capped at 2 uses per item since a receipt-code
# lookup rarely needs more than that, to keep cost/latency bounded across a whole batch.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}


class CategorizationResult(BaseModel):
    category_id: str
    category_label: str
    deductible: bool
    deduction_pct: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    rationale: str
    needs_human_review: bool
    resolved_item_name: Optional[str] = Field(
        default=None,
        description=(
            "The actual product name/description, if identified (directly or via web "
            "search) beyond a cryptic receipt code or abbreviation. Null if the original "
            "description was already a clear product name."
        ),
    )


def _render_categories(ruleset: Ruleset) -> str:
    lines = []
    for category in ruleset.categories:
        schedule = f" ({category.schedule_line})" if category.schedule_line else ""
        review_note = " [always requires human review]" if category.requires_manual_review else ""
        lines.append(
            f"- id={category.id!r} \"{category.label}\"{schedule}: "
            f"deductible={category.deductible}, deduction_pct={category.deduction_pct}{review_note}"
        )
    return "\n".join(lines)


def categorize_with_claude(vendor: str | None, description: str | None, amount: float | None, ruleset: Ruleset) -> CategorizationResult:
    system_prompt = (
        f"{ruleset.fallback.claude_context}\n\n"
        f"Available categories for this ruleset ({ruleset.name}):\n"
        f"{_render_categories(ruleset)}\n\n"
        "Receipt line items are often just a cryptic vendor code or abbreviation (e.g. a "
        "Costco line like '1193179 KS SMALL **'), not a real product description. Before "
        "categorizing, work out what the item actually is:\n"
        "- Start with general knowledge and common vendor abbreviation conventions (e.g. "
        "Costco's 'KS' = Kirkland Signature, a leading letter like 'E' = a tax-category code).\n"
        "- If that's not enough to confidently tell what the product is, use the web_search "
        "tool to look it up (e.g. the vendor name plus the item number or code) rather than "
        "guessing from the abbreviation alone.\n"
        "- If you identify the actual product, put its real name in resolved_item_name - this "
        "replaces the cryptic code in the record so the user doesn't see raw abbreviations.\n\n"
        "Pick the single best-fitting category_id from that exact list (or the closest one if "
        "nothing fits perfectly), and cite the category's schedule line in your rationale.\n\n"
        "Only set needs_human_review to true when the deductibility is genuinely ambiguous "
        "once you know what the item actually is - e.g. it could plausibly be either business "
        "or personal use and nothing on the receipt settles it. Do NOT flag for review just "
        "because the receipt text was hard to read: if you were able to identify the item "
        "(directly or via search), categorize it confidently based on what it actually is."
    )
    user_message = (
        f"Vendor: {vendor or 'unknown'}\n"
        f"Description: {description or 'unknown'}\n"
        f"Amount: {amount if amount is not None else 'unknown'}\n\n"
        "Categorize this transaction."
    )

    client = get_anthropic_client()
    response = client.messages.parse(
        model=settings.claude_model_categorize,
        # 1024 was too tight once web_search actually fires: search queries + result
        # blocks can eat most of the budget, leaving too little for the final JSON
        # block and producing either no text block at all or a truncated one - both
        # surfaced as "Categorization error" on the item instead of a real result.
        max_tokens=4096,
        system=system_prompt,
        tools=[WEB_SEARCH_TOOL],
        messages=[{"role": "user", "content": user_message}],
        output_format=CategorizationResult,
    )
    result = response.parsed_output
    if result is None:
        raise RuntimeError(
            f"Claude did not return a parsed categorization result (stop_reason={response.stop_reason!r})"
        )
    return result
