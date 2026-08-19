from functools import lru_cache

import yaml

from app.categorization.ruleset_schema import Ruleset
from app.config import settings


@lru_cache
def load_ruleset(name: str) -> Ruleset:
    path = settings.rulesets_dir_abs / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Ruleset '{name}' not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Ruleset.model_validate(raw)


def list_rulesets() -> list[str]:
    return sorted(p.stem for p in settings.rulesets_dir_abs.glob("*.yaml"))
