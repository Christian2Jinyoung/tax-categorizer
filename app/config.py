from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""

    claude_model_extraction: str = "claude-sonnet-5"
    claude_model_categorize: str = "claude-sonnet-5"

    database_path: str = "data/tax_categorizer.db"
    upload_dir: str = "data/uploads"
    rulesets_dir: str = "config/rulesets"
    default_ruleset: str = "us_self_employed_schedule_c"

    ocr_confidence_threshold: float = 60
    categorization_confidence_threshold: float = 0.7

    tesseract_cmd: str = ""

    @property
    def database_path_abs(self) -> Path:
        return PROJECT_ROOT / self.database_path

    @property
    def upload_dir_abs(self) -> Path:
        return PROJECT_ROOT / self.upload_dir

    @property
    def rulesets_dir_abs(self) -> Path:
        return PROJECT_ROOT / self.rulesets_dir


settings = Settings()
