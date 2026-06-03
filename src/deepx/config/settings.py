"""Application settings."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from deepx.config.models import (
    DEFAULT_MODELS, ModelConfig, load_all_models, load_current_slots,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DEEPX_", extra="ignore")

    # ── Models ──────────────────────────────────────────────────────────────
    # Lazily populated from ~/.deepx/model.yaml on first access
    _all_models: dict[str, ModelConfig] = {}
    _flash_slot: str = "deepseek-flash"
    _pro_slot: str = "deepseek-reasoner"

    # ── Session ────────────────────────────────────────────────────────────
    session_dir: Path = Field(
        default_factory=lambda: Path.home() / ".deepx" / "sessions",
    )

    # ── Agent ───────────────────────────────────────────────────────────────
    max_rounds: int = Field(default=100)
    context_window: int = Field(default=200_000)
    keep_recent_turns: int = Field(default=5)
    compress_threshold: float = Field(default=0.4)
    cache_warm_window_seconds: int = Field(default=3600)
    default_mode: Literal["auto", "review", "plan"] = Field(default="review")

    # ── Code Analysis ──────────────────────────────────────────────────────
    codegraph_max_files: int = Field(default=50_000)
    codegraph_max_mb: int = Field(default=512)
    codegraph_timeout_seconds: int = Field(default=60)

    # ── OCR ───────────────────────────────────────────────────────────────
    ocr_engine: Literal["paddleocr", "easyocr", "tesseract"] = Field(
        default="tesseract"
    )

    # ── Web ───────────────────────────────────────────────────────────────
    web_enabled: bool = Field(default=True)
    web_port: int = Field(default=0)

    @field_validator("session_dir", mode="before")
    @classmethod
    def _ensure_session_dir(cls, v: Path | str) -> Path:
        p = Path(v) if isinstance(v, str) else v
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _ensure_models(self) -> None:
        """Load from YAML on first use."""
        if self._all_models:
            return
        self._all_models = load_all_models()
        self._flash_slot, self._pro_slot = load_current_slots()

    def current_model(self) -> str | None:
        """Return the key of the current flash (default) model."""
        return self._flash_slot or None

    def default_model(self) -> str | None:
        """Return the default model key (flash slot)."""
        return self._flash_slot or None

    def all_models(self) -> dict[str, ModelConfig]:
        self._ensure_models()
        return {**DEFAULT_MODELS, **self._all_models}

    def model(self, name: str) -> ModelConfig:
        """Get model by name, with fallback to defaults."""
        self._ensure_models()
        return self.all_models().get(name, DEFAULT_MODELS.get(name))

    def flash_model(self) -> ModelConfig:
        self._ensure_models()
        return self.model(self._flash_slot)

    def pro_model(self) -> ModelConfig:
        self._ensure_models()
        return self.model(self._pro_slot)

    def model_for(self, name: Literal["flash", "pro"]) -> ModelConfig:
        """Alias for template literals."""
        return self.flash_model() if name == "flash" else self.pro_model()

    def setup(self) -> None:
        """Called once at startup."""
        self._ensure_models()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.setup()
    return _settings


def create_config_template() -> Path:
    """Copy config.example.yaml to ~/.deepx/model.yaml if absent."""
    src = Path(__file__).parent.parent.parent / "config.example.yaml"
    dst = _cfg_path()
    if not dst.exists() and src.exists():
        shutil.copy(src, dst)
    return dst


def _cfg_path() -> Path:
    return Path.home() / ".deepx" / "model.yaml"