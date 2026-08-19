import re
from dataclasses import dataclass
from typing import Optional

from app.categorization.ruleset_schema import Category, Ruleset


@dataclass
class RuleMatchResult:
    category: Category
    matched_keyword: str
    matched_field: str  # "vendor" | "description"


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.lower()
    return re.sub(r"[^a-z0-9\s]", " ", text)


def match_line_item(vendor: Optional[str], description: Optional[str], ruleset: Ruleset) -> Optional[RuleMatchResult]:
    """First-match-wins keyword matching, in ruleset category order.

    A category flagged requires_manual_review never auto-matches here even if its
    keywords hit — it always escalates to the Claude fallback / human review.
    """
    norm_vendor = _normalize(vendor)
    norm_description = _normalize(description)

    for category in ruleset.categories:
        if category.requires_manual_review:
            continue

        for keyword in category.match.vendor_keywords:
            if _normalize(keyword) in norm_vendor:
                return RuleMatchResult(category=category, matched_keyword=keyword, matched_field="vendor")

        for keyword in category.match.description_keywords:
            if _normalize(keyword) in norm_description:
                return RuleMatchResult(category=category, matched_keyword=keyword, matched_field="description")

    return None
