from typing import Optional

from pydantic import BaseModel, Field


class CategoryMatch(BaseModel):
    vendor_keywords: list[str] = Field(default_factory=list)
    description_keywords: list[str] = Field(default_factory=list)


class Category(BaseModel):
    id: str
    label: str
    schedule_line: Optional[str] = None
    deductible: bool
    deduction_pct: Optional[float] = None
    requires_manual_review: bool = False
    match: CategoryMatch = Field(default_factory=CategoryMatch)


class Fallback(BaseModel):
    claude_context: str = ""


class Ruleset(BaseModel):
    name: str
    filer_type: str
    categories: list[Category]
    fallback: Fallback = Field(default_factory=Fallback)

    def find_category(self, category_id: str) -> Optional[Category]:
        for category in self.categories:
            if category.id == category_id:
                return category
        return None
