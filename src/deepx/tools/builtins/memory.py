"""Memory tool — cross-session search in workspace conversation history."""
from __future__ import annotations

import re
from pathlib import Path

from deepx.tools.base import Tool


class Memory(Tool):
    """
    Search the workspace conversation history (all past sessions) for relevant context.

    Uses the daily JSONL log files in ~/.deepx/sessions/{workspace_hash}/ to find
    relevant past conversations. Simple keyword + regex matching for now.
    Returns matching entries with session context.
    """

    name = "Memory"
    description = "Search the workspace conversation history (all past sessions) for relevant context. Use this when the user asks about something that might have been discussed before, or to recall decisions made in previous sessions."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query to find relevant historical context.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching entries to return. Default 5.",
            },
            "workspace": {
                "type": "string",
                "description": "Workspace path to search history for. Defaults to current workspace.",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        max_results: int = 5,
        workspace: str | None = None,
        **kwargs,
    ) -> str:
        import hashlib
        from deepx.config.settings import get_settings

        settings = get_settings()
        workspace_path = Path(workspace or ".").resolve()
        workspace_hash = hashlib.sha1(str(workspace_path).encode()).hexdigest()[:16]
        session_dir = settings.session_dir / workspace_hash / "conversations"

        if not session_dir.exists():
            return f"No conversation history found for this workspace."

        # Build search patterns
        query_lower = query.lower()
        patterns = [re.escape(q.strip()) for q in query.split() if q.strip()]
        if not patterns:
            return "No search terms provided."

        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]

        def matches(text: str) -> bool:
            """Check if all query terms match."""
            text_lower = text.lower()
            return all(p.search(text_lower) for p in compiled_patterns)

        matches_found: list[tuple[str, str, str]] = []  # (conv_id, date, content)

        # Search all jsonl files
        for conv_dir in sorted(session_dir.iterdir()):
            if not conv_dir.is_dir():
                continue
            conv_id = conv_dir.name

            # Search date-based jsonl files
            for jsonl_file in sorted(conv_dir.glob("*.jsonl")):
                date = jsonl_file.stem  # e.g. "2026-06-03"
                try:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            if matches(line):
                                matches_found.append((conv_id, date, line[:200]))
                                if len(matches_found) >= max_results * 3:  # collect more for deduplication
                                    break
                except (OSError, ValueError):
                    continue

            if len(matches_found) >= max_results * 3:
                break

        if not matches_found:
            return f"No history found matching: {query}"

        # Deduplicate and format results
        seen = set()
        results: list[str] = []
        for conv_id, date, content in matches_found:
            key = content[:100]
            if key in seen:
                continue
            seen.add(key)
            results.append(f"[{date}] {content}")
            if len(results) >= max_results:
                break

        header = f"[Memory: {len(results)} matches for '{query}']\n"
        return header + "\n\n".join(results)