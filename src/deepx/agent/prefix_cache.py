"""Prefix cache management — maximize DeepSeek cache hit rate."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from deepx.config.settings import get_settings


@dataclass
class PrefixSnapshot:
    """A snapshot of the prefix sent to the LLM."""

    sig: str
    model: str
    system_prompt: str
    tool_specs_json: str
    mcp_config_hash: str = ""
    saved_at: float = 0.0

    @property
    def is_warm(self) -> bool:
        """Check if this snapshot is within the warm window."""
        settings = get_settings()
        age = time.time() - self.saved_at
        return age < settings.cache_warm_window_seconds

    @property
    def prefix_signature(self) -> str:
        """The SHA256 hash that identifies this prefix."""
        return self.sig


class PrefixCache:
    """
    Manages DeepSeek API prefix caching.

    DeepSeek caches prefixes that are identical across requests.
    To maximize cache hit rate:
    1. Save the EXACT system prompt + tool specs sent to the LLM
    2. On restart/compression, reconstruct the EXACT same message sequence
    3. Use SHA256 signature to detect when prefix actually changed
    """

    def __init__(self, workspace: Path | str):
        self.settings = get_settings()
        self.workspace = workspace if isinstance(workspace, Path) else Path(workspace)
        # In-memory snapshot (loaded from session store on init)
        self._snapshot: PrefixSnapshot | None = None

    @staticmethod
    def compute_sig(system_prompt: str, tool_specs: str, mcp_config: str = "") -> str:
        """Compute SHA256 signature for the current prefix."""
        data = f"{system_prompt}\x00{tool_specs}\x00{mcp_config}".encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:32]

    def compute_and_save_snapshot(
        self,
        system_prompt: str,
        tool_specs_json: str,
        model: str,
        mcp_config: str = "",
    ) -> PrefixSnapshot:
        """Save the prefix snapshot for future cache-friendly compression."""
        sig = self.compute_sig(system_prompt, tool_specs_json, mcp_config)
        snapshot = PrefixSnapshot(
            sig=sig,
            model=model,
            system_prompt=system_prompt,
            tool_specs_json=tool_specs_json,
            mcp_config_hash=hashlib.sha256(mcp_config.encode()).hexdigest()[:16],
            saved_at=time.time(),
        )
        self._snapshot = snapshot
        return snapshot

    def load_snapshot(
        self,
    ) -> tuple[str | None, str | None, str | None]:
        """
        Load the last saved snapshot from session store.

        Returns (sig, system_prompt, tool_specs_json).
        """
        # TODO: load from SessionStore
        # This is called by the TUI on startup to enable warm restart compression
        return None, None, None

    def get_snapshot(self) -> PrefixSnapshot | None:
        return self._snapshot

    def should_use_warm_path(self, new_sig: str) -> bool:
        """
        Determine if we should use warm path (old prefix) for compression.

        Warm path: use the OLD prefix to reconstruct the prefix that was cached.
        This is used when the prefix changed but we're within the warm window.
        """
        if self._snapshot is None:
            return False
        return self._snapshot.is_warm and self._snapshot.sig != new_sig