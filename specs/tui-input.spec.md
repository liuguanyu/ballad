# Spec: TUI 输入区（tui-input）

## 背景

底部固定输入区，对齐 Claude Code：一条 History 顶线 + 裸输入行 + 一条底部横线，
支持动态高度与多行编辑。视觉细节以真实 cc 截图为准。

## 需求

### REQ-INPUT-1 动态高度（1–5 行）
输入框高度随文本换行数在 **1 到 5 行**之间伸缩；超过 5 行保持 5 行，
内部向上滚动只显示尾部 5 行。

### REQ-INPUT-2 视觉：上下横线夹裸输入行（无左右竖线）
- **顶线**：一条 `─ History n/n ─────` 分隔线，文字**嵌在横线里**（压线），
  横线补足到终端整行宽度。仅在历史翻阅态显示（见 tui-history.spec.md）。
- **中间**：输入行 `> <文本>▋`，仅提示符 `> ` + 文本 + 光标块。
  **不得有左右竖线 `│`，不得有圆角边框 `╰╯`。**
- **底线**：一条纯横线 `─────`（铺满整行宽度，无圆角、无竖线）。

### REQ-INPUT-3 编辑键
- 普通字符：追加到当前文本。
- **退格**：删除末字符。
- **回车（非 Shift）**：内容非空则提交并清空；纯空白不提交。
- **Shift+Enter**：插入换行（不提交）。

### REQ-INPUT-4 提交契约
提交时调用 `onSubmit(value)`，传入原始文本（含换行），随后清空输入框并重置历史翻阅态。

### REQ-INPUT-5 禁用态
`disabled=true`（大脑忙）时忽略一切按键输入。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-INPUT-1 | `tests/tui/logic/inputModel.test.ts` → `computeRows` 边界（0/1/3/超5） |
| REQ-INPUT-2 顶线压线 | `tests/tui/DynamicInput.test.tsx` → 顶边匹配 `/─ History n\/n ─+/` |
| REQ-INPUT-2 无竖线 | 同上 → 输入行不含 `│` |
| REQ-INPUT-2 底线 | 同上 → 末行匹配 `/^─+$/`，不含 `╰` |
| REQ-INPUT-3 | 同上 → 键入回显 / 退格 / 回车提交清空 / 空回车不提交 |
| REQ-INPUT-4 | 同上 → `onSubmit` 被以原文调用一次 |
| REQ-INPUT-5 | 同上 → disabled 时键入无回显 |

## 关联实现

- `src/platforms/tui/components/DynamicInput.tsx`（渲染 + 事件分发）
- `src/platforms/tui/logic/inputModel.ts`（`computeRows` / `visibleLines` / `buildHistoryBorder`）
