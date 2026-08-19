from functools import lru_cache

import anthropic

from app.config import settings


@lru_cache
def get_anthropic_client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key "
            "before running anything that needs Claude (categorization fallback or OCR repair)."
        )
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)
