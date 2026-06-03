"""Token usage tracking and cost calculation."""
from __future__ import annotations

import tiktoken
from pydantic import BaseModel, Field


# Singleton encoder — loaded once
_encoder = tiktoken.get_encoding("o200k_base")


def count_tokens(text: str) -> int:
    """Count tokens in a single text string using o200k_base."""
    return len(_encoder.encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """Count total tokens for a list of OpenAI-format messages."""
    # System message
    system_tokens = 0
    for m in messages:
        if m.get("role") == "system":
            system_tokens = count_tokens(m.get("content", ""))
            break

    total = system_tokens
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        # role token + newline + content
        total += count_tokens(f"{role}\n{content}")
        if tool_calls := m.get("tool_calls"):
            for tc in tool_calls:
                args = tc.get("function", {}).get("arguments", "")
                total += count_tokens(f"tool_call\n{args}")

    return total


class UsageInfo(BaseModel):
    """Aggregated usage information for a response."""

    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    prompt_cache_hit_tokens: int = Field(default=0)
    prompt_cache_miss_tokens: int = Field(default=0)

    @property
    def cache_hit_tokens(self) -> int:
        """Alias for prompt_cache_hit_tokens (DeepSeek format)."""
        return self.prompt_cache_hit_tokens

    def cache_hit_rate(self) -> float:
        """Return cache hit rate as a percentage (0-100)."""
        if self.prompt_tokens == 0:
            return 0.0
        return self.prompt_cache_hit_tokens / self.prompt_tokens * 100

    def total_cost(self, input_price: float, output_price: float) -> float:
        """Calculate total cost in USD."""
        uncached = self.prompt_tokens - self.prompt_cache_hit_tokens
        return (
            uncached * input_price
            + self.prompt_cache_hit_tokens * input_price * 0.1
            + self.completion_tokens * output_price
        ) / 1_000_000

    def merge(self, other: UsageInfo) -> UsageInfo:
        """Merge another UsageInfo into this one (for batch updates)."""
        return UsageInfo(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            prompt_cache_hit_tokens=(
                self.prompt_cache_hit_tokens + other.prompt_cache_hit_tokens
            ),
            prompt_cache_miss_tokens=(
                self.prompt_cache_miss_tokens + other.prompt_cache_miss_tokens
            ),
        )