"""Zero-token model routing — pure local string matching."""
from __future__ import annotations

import re

# Complex keywords that indicate a hard task — route to pro
_COMPLEX_KEYWORDS = {
    # English
    "refactor", "rearchitect", "redesign", "debug", "profile",
    "optimize", "performance", "security", "architecture",
    "migration", "benchmark", "concurrent", "parallel",
    "refactor", "restructure", "reorganize", "partition",
    "race condition", "deadlock", "memory leak", "stack overflow",
    "benchmark", "profiling", "performance tuning",
    # Chinese
    "重构", "重设计", "架构", "调试", "性能优化", "内存泄漏",
    "并发", "并行", "迁移", "安全漏洞", "死锁", "竞态条件",
    "基准测试", "堆栈溢出", "性能分析", "优化",
    # Japanese
    "リファクタ", "アーキテクチャ", "デバッグ", "最適化",
    # Korean
    "리팩토링", "아키텍처", "디버그", "최적화",
}

# Learning query patterns — even with complex keywords, use flash
_LEARNING_PATTERNS = [
    re.compile(r"^(what is|what's|how does|how do|why does|why is|how to|how can|can i|is it|what are|who is|who are)", re.I),
    re.compile(r"^(什么是|怎么|如何|为什么|是什么|请问|问一下)"),
    re.compile(r"^(何|どう|なぜ|どのように)"),
    re.compile(r"^(무엇|어떻게|왜)"),
]


def _is_learning_query(msg: str) -> bool:
    """Detect FAQ-style learning queries — downgrade to flash."""
    lower = msg.lower().strip()
    for pattern in _LEARNING_PATTERNS:
        if pattern.match(lower):
            return True
    return False


def _rune_count(s: str) -> int:
    """Count runes (Unicode code points), not bytes."""
    return len(s.encode("utf-8")) // 4 + len([c for c in s if ord(c) < 128])


def route_model(user_msg: str) -> str:
    """
    Route to flash or pro using pure local rules.

    Returns "flash" or "pro". Zero LLM calls, zero latency.

    Rules:
    1. If message contains a complex keyword:
       - If it's a learning query → flash
       - Otherwise → pro
    2. If message is short (< 100 chars) → flash
    3. If message is long (> 500 chars) → pro
    4. Otherwise → flash
    """
    if not user_msg:
        return "flash"

    lower = user_msg.lower().strip() if user_msg else ""

    # Check for complex keywords
    for kw in _COMPLEX_KEYWORDS:
        if kw in lower:
            if _is_learning_query(user_msg):
                return "flash"
            return "pro"

    # Fallback by length
    rune_count = _rune_count(user_msg)
    if rune_count < 100:
        return "flash"
    if rune_count > 500:
        return "pro"
    return "flash"