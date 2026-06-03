"""
Context compression — reduce history to 20% budget, keep last N turns.
Supports both warm path (prefix cache hit for ~free summarization)
and cold path (direct LLM call).
"""
from __future__ import annotations

from deepx.agent.prefix_cache import PrefixCache
from deepx.config.settings import get_settings
from deepx.llm.client import Message


_WARM_COMPRESS_INSTRUCTION = """\
The conversation history is very long. Summarize the key points \
of the conversation so far, preserving all important context, \
decisions, and pending tasks. Write the summary in the same \
language as the user's messages. Then output: SUMMARY_END
Now summarize the following conversation:"""

_COLD_COMPRESS_INSTRUCTION = """\
The conversation history is very long. Summarize the key points \
of the conversation so far, preserving all important context, \
decisions, and pending tasks. Write the summary in the same \
language as the user's messages."""


class ContextCompressor:
    """
    Compress conversation history to fit within the context budget.

    Strategy:
    1. Count total tokens in history
    2. If exceeds compress_threshold of context_window:
       - Keep at least keep_recent_turns (never discard recent)
       - Find a cut point that fits in 20% budget
       - Use the LLM to summarize the old portion (warm path if prefix cache available)
    """

    def __init__(self, prefix_cache: PrefixCache | None = None):
        self.settings = get_settings()
        self.prefix_cache = prefix_cache or PrefixCache(workspace=".")

    def should_compress(self, history: list[dict]) -> bool:
        """Check if compression is needed."""
        from deepx.llm.usage import count_messages_tokens
        total_tokens = count_messages_tokens(history)
        threshold = int(self.settings.context_window * self.settings.compress_threshold)
        return total_tokens > threshold

    def find_cut_index(self, history: list[dict]) -> int:
        """
        Find the earliest index to keep, such that:
        - At least keep_recent_turns are preserved
        - Remaining fits in 20% of context_window
        """
        from deepx.llm.usage import count_messages_tokens
        target_tokens = int(self.settings.context_window * 0.2)
        min_turns = self.settings.keep_recent_turns

        for cut in range(len(history) - min_turns):
            kept = history[cut:]
            tokens = count_messages_tokens(kept)
            if tokens <= target_tokens:
                return cut
        return max(0, len(history) - min_turns)

    async def compress(
        self,
        history: list[dict],
        system_prompt: str,
        model: str,
        llm_client,
    ) -> tuple[list[dict], int]:
        """
        Compress history and return the new history.

        Returns (compressed_history, cut_index).
        """
        from deepx.llm.usage import count_messages_tokens

        cut_index = self.find_cut_index(history)
        old_history = history[:cut_index]
        new_history = history[cut_index:]

        # Warm path: use prefix cache to hit DeepSeek cache
        snapshot = self.prefix_cache.get_snapshot()
        use_warm = snapshot and snapshot.is_warm

        # Build messages for summarization
        if use_warm and snapshot:
            compress_messages = [
                Message(role="system", content=snapshot.system_prompt).model_dump(),
                Message(role="user", content=_WARM_COMPRESS_INSTRUCTION).model_dump(),
            ]
        else:
            compress_messages = [
                Message(role="system", content=system_prompt).model_dump(),
                Message(role="user", content=_COLD_COMPRESS_INSTRUCTION).model_dump(),
            ]

        compress_messages.extend(old_history)

        # Call LLM to summarize
        summary_text = await self._summarize(compress_messages, model, llm_client)

        # Build compressed history
        compressed_history = [
            {"role": "system", "content": f"[Earlier conversation summary]\n{summary_text}"},
        ] + new_history

        return compressed_history, cut_index

    async def _summarize(
        self,
        messages: list[dict],
        model: str,
        llm_client,
    ) -> str:
        """Call LLM to generate a summary of old conversation history."""
        summary_parts: list[str] = []
        model_cfg = self.settings.model_for(model)

        try:
            async for chunk in llm_client.chat(
                messages=messages,
                model=model_cfg.model_id,
                tools=None,
                stream=True,
            ):
                if chunk.content:
                    summary_parts.append(chunk.content)
                if chunk.done:
                    break
        except Exception:
            return "[Earlier conversation history — see above for details]"

        text = "".join(summary_parts)
        # Strip SUMMARY_END marker if present
        text = text.replace("SUMMARY_END", "").strip()
        if not text:
            return "[Earlier conversation history — see above for details]"
        return text