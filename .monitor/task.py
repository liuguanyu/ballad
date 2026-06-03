#!/usr/bin/env python3
"""deepx-python 进度监控任务。"""
import subprocess
import os
from pathlib import Path

PROJECT = Path.home() / "devspace" / "deepx-python"
OUT_DIR = PROJECT / ".monitor"
OUT_DIR.mkdir(exist_ok=True)
OUT = OUT_DIR / "latest.md"
PREV = OUT_DIR / "prev.md"
from datetime import datetime

date = datetime.now().strftime("%Y-%m-%d %H:%M")

report = f"""# deepx-python 监控报告 — {date}

## 关键模块状态

"""

checks = [
    ("codegraph/index.py", "CodeGraph 两阶段索引"),
    ("mcp/client.py", "MCP Client"),
    ("ocr/engine.py", "OCR Engine"),
    ("graph/nodes.py", "LangGraph Nodes"),
    ("graph/edges.py", "LangGraph Edges"),
    ("tui/app.py", "TUI App"),
    ("agent/compress.py", "Context Compress"),
    ("agent/prefix_cache.py", "Prefix Cache"),
    ("session/manager.py", "Session Manager"),
    ("skill/loader.py", "Skill Loader"),
]

for rel, desc in checks:
    fpath = PROJECT / "src" / "deepx" / rel
    skill_path = PROJECT / "src" / "deepx" / "skill"
    if skill_path.exists():
        report += f"- [✅] Skill 系统 (skill/ 已存在)\n"
        break
else:
    if not (PROJECT / "src" / "deepx" / "skill").exists():
        report += f"- [❌] Skill 系统 (skill/ 不存在)\n"

for rel, desc in checks:
    fpath = PROJECT / "src" / "deepx" / rel
    if fpath.exists():
        lines = fpath.read_text().count("\n")
        stubs = fpath.read_text().count("TODO") + fpath.read_text().count("stub") + fpath.read_text().count("NotImplementedError") + fpath.read_text().count("pass  #")
        report += f"- [{'⚠️' if stubs > 3 else '✅'}] {desc} ({rel}, {lines}行, ~{stubs}处TODO/stub)\n"
    else:
        report += f"- [❌] {desc} ({rel} 不存在)\n"

report += "\n## 对比上次报告\n"

prev = PROJECT / ".monitor" / "prev.md"
latest_content = report
if prev.exists():
    prev_content = prev.read_text()
    # 简单对比
    import difflib
    diff = list(difflib.unified_diff(
        prev_content.splitlines(keepends=True),
        latest_content.splitlines(keepends=True),
        fromfile="prev", tofile="latest"
    ))
    if diff:
        report += "\n```diff\n" + "".join(diff[:30]) + "```\n"
    else:
        report += "_无变更_\n"
else:
    report += "_首次记录_\n"

OUT.write_text(latest_content)
prev.write_text(latest_content)

print(f"✅ 报告已生成: {OUT}")