"""Model configuration — multi-provider, multi-model, switchable."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


def _expand_env(value: str) -> str:
    """Expand ${VAR} and $VAR in string."""
    def repl(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        return os.environ.get(name, m.group(0))
    return re.sub(r'\$\{(\w+)\}|\$(\w+)', repl, value)


class ModelConfig(BaseModel):
    """Configuration for a single model endpoint."""

    name: str = Field(description="Display name")
    model: str = Field(description="API model ID")
    base_url: str = Field(description="API base URL")
    api_key: str | None = Field(default=None, description="API key")
    api_type: Literal["openai", "anthropic"] = Field(
        default="openai",
        description='"openai" (POST /chat/completions) or "anthropic" (POST /messages)',
    )
    context_window: int = Field(default=200_000, description="Max context tokens")
    max_tokens: int = Field(default=8192, description="Max output tokens")
    reasoning_effort: str | None = Field(
        default=None, description="low/medium/high (DeepSeek reasoning)"
    )
    thinking: bool = Field(default=False, description="Enable thinking (Anthropic)")
    input_price: float | None = Field(default=None)
    output_price: float | None = Field(default=None)
    cache_discount: float = Field(default=0.1)

    @property
    def is_reasoning(self) -> bool:
        return self.reasoning_effort is not None

    def input_cost(self, tokens: int, cached: int = 0) -> float:
        if self.input_price is None:
            return 0.0
        uncached = max(0, tokens - cached)
        return (uncached * self.input_price + cached * self.input_price * self.cache_discount) / 1_000_000

    def output_cost(self, tokens: int) -> float:
        if self.output_price is None:
            return 0.0
        return tokens * self.output_price / 1_000_000


# ── YAML config loader ────────────────────────────────────────────────────────

def _cfg_path() -> Path:
    p = Path.home() / ".deepx" / "model.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _read_yaml() -> dict:
    p = _cfg_path()
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # Expand env vars in all string values
    def walk(d):
        if isinstance(d, dict):
            return {k: walk(v) for k, v in d.items()}
        if isinstance(d, str):
            return _expand_env(d)
        return d
    return walk(raw)


def load_all_models() -> dict[str, ModelConfig]:
    """Load all named models from ~/.deepx/model.yaml."""
    data = _read_yaml()
    models = {}
    for name, cfg in data.get("models", {}).items():
        if not cfg:
            continue
        # Allow "model" or "model_id" for the API model ID
        model_id = cfg.get("model") or cfg.get("model_id") or ""
        models[name] = ModelConfig(
            name=cfg.get("name", name),
            model=model_id,
            base_url=cfg.get("base_url", ""),
            api_key=cfg.get("api_key"),
            api_type=cfg.get("api_type", "openai"),
            context_window=int(cfg.get("context_window", 200_000)),
            max_tokens=int(cfg.get("max_tokens", 8192)),
            reasoning_effort=cfg.get("reasoning_effort"),
            thinking=bool(cfg.get("thinking", False)),
            input_price=cfg.get("input_price"),
            output_price=cfg.get("output_price"),
            cache_discount=float(cfg.get("cache_discount", 0.1)),
        )
    return models


def load_current_slots() -> tuple[str, str]:
    """Return (flash_model_name, pro_model_name) from config."""
    data = _read_yaml()
    current = data.get("current", {})
    return (
        current.get("flash", "deepseek-flash"),
        current.get("pro", "deepseek-reasoner"),
    )


# ── Default fallback (when no config file exists) ────────────────────────────

DEFAULT_MODELS: dict[str, ModelConfig] = {
    "deepseek-flash": ModelConfig(
        name="DeepSeek Flash",
        model="deepseek-chat-v3-20250314",
        base_url="https://api.deepseek.com",
        api_type="openai",
        context_window=1_000_000,
        input_price=0.27,
        output_price=1.1,
    ),
    "deepseek-pro": ModelConfig(
        name="DeepSeek Pro",
        model="deepseek-reasoner-v2-20250601",
        base_url="https://api.deepseek.com",
        api_type="openai",
        context_window=1_000_000,
        reasoning_effort="medium",
        input_price=0.27,
        output_price=1.1,
    ),
}