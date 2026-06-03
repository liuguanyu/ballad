#!/bin/bash
# 检查 deepx-python 项目完成情况，对比 deepx-code 父项目
# 生成状态报告

PROJECT_DIR="$HOME/devspace/deepx-python"
OUT="$HOME/devspace/deepx-python/.monitor/latest.md"
PREV="$HOME/devspace/deepx-python/.monitor/prev.md"
DATE=$(date '+%Y-%m-%d %H:%M')

echo "# deepx-python 监控报告 — $DATE" > "$OUT"
echo "" >> "$OUT"

# 检查关键文件是否存在
echo "## 关键模块状态" >> "$OUT"
echo "" >> "$OUT"

check() {
  local file=$1
  local desc=$2
  if [ -f "$PROJECT_DIR/src/deepx/$file" ]; then
    # 检查是否基本为空或全是stub
    lines=$(wc -l < "$PROJECT_DIR/src/deepx/$file")
    stubs=$(grep -c "TODO\|stub\|pass\|NotImplementedError" "$PROJECT_DIR/src/deepx/$file" 2>/dev/null || echo 0)
    echo "- [✅] $desc ($file, ${lines}行, ~${stubs}处TODO/stub)" >> "$OUT"
  else
    echo "- [❌] $desc ($file 不存在)" >> "$OUT"
  fi
}

check "codegraph/index.py" "CodeGraph 两阶段索引"
check "skill/__init__.py" "Skill 系统"
check "mcp/client.py" "MCP Client"
check "ocr/engine.py" "OCR Engine"
check "graph/nodes.py" "LangGraph Nodes"
check "graph/edges.py" "LangGraph Edges"
check "tui/app.py" "TUI App"
check "tools/builtins/codegraph_tool.py" "CodeGraph Tool"

echo "" >> "$OUT"
echo "## Git 变更" >> "$OUT"
echo "" >> "$OUT"
(cd "$PROJECT_DIR" && git log --oneline -5 2>/dev/null | head -5) >> "$OUT" 2>&1
echo "" >> "$OUT"

# 对比上次报告
if [ -f "$PREV" ]; then
  echo "## 变更摘要" >> "$OUT"
  echo "" >> "$OUT"
  echo '```diff' >> "$OUT"
  diff -u "$PREV" "$OUT" | grep "^[+-]" | grep -v "^[+-]{3}" | head -20 >> "$OUT" 2>&1
  echo '```' >> "$OUT"
fi

cp "$OUT" "$PREV"
echo "报告已生成: $OUT"