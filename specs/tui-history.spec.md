# Spec: 历史翻阅状态机（tui-history）

## 背景

输入区的历史导航要贴近 Claude Code 的真实手感：默认不打扰（不显示 History），
按 ↑ 才进入翻阅；历史条目可能多行，上下键先在条目内逐行移光标，到边界才切换条目；
在若干明确边界上退出翻阅并恢复用户原本的编辑草稿。

## 状态模型

翻阅状态由以下字段描述：
- `browsing: boolean`——是否处于历史翻阅态，**初始 false**。
- `index: number`——翻阅时定位的历史条目（0-based，最旧→最新）。
- `cursorLine: number`——当前条目内光标所在行（0-based），支撑多行导航。
- `draft: string`——进入翻阅前保存的编辑草稿，退出翻阅时恢复。

## 需求

### REQ-HIST-1 初始非翻阅
启动即非翻阅态。此时**顶部不渲染 History 行**（输入区顶部无线）。

### REQ-HIST-2 非翻阅态按键
- 非翻阅 + ↑：若有历史 → **进入翻阅**，保存当前文本为 `draft`，载入最新一条
  （`index = total-1`），光标置于该条**末行**。若无历史 → 不动。
- 非翻阅 + ↓：不动（下方无更新历史）。

### REQ-HIST-3 翻阅态多行光标
- 翻阅 + ↑ 且 `cursorLine > 0`：`cursorLine -= 1`（条目内上移，不换条目）。
- 翻阅 + ↓ 且 `cursorLine < 末行`：`cursorLine += 1`（条目内下移）。

### REQ-HIST-4 跨条目切换
- 翻阅 + ↑ 且在**首行**且 `index > 0`：切上一条（`index -= 1`），光标置**末行**。
- 翻阅 + ↓ 且在**末行**且 `index < total-1`：切下一条（`index += 1`），光标置**首行**。

### REQ-HIST-5 四个退出翻阅触发（恢复草稿）
退出翻阅 = `browsing=false` 且输入框恢复为 `draft`：
1. **初始**即非翻阅（默认态）。
2. **删字删到空**：退格使文本变空时，若在翻阅态则退出。
3. **全局首行再 ↑**：在首行且 `index === 0` 再按 ↑ → 退出。
4. **全局末行再 ↓**：在末行且 `index === total-1` 再按 ↓ → 退出。

### REQ-HIST-6 键入退出翻阅
翻阅态下键入任意普通字符：先退出翻阅（草稿作废），再把该字符接入当前文本进入编辑。

### REQ-HIST-7 History 行显示条件
`─ History n/n ─` 顶线**仅在 `browsing=true` 时显示**；`n` = `index+1`，
分母 = 历史总条数。非翻阅态不显示该行。

## 验收标准

| 需求 | 测试用例（`tests/tui/logic/inputModel.test.ts` 的 `stepHistory` 组） |
| :-- | :-- |
| REQ-HIST-2 | 非翻阅↑进入翻阅、存草稿、光标末行；非翻阅↓不动 |
| REQ-HIST-3 | 多行条目内↑/↓：cursorLine 变、index 不变 |
| REQ-HIST-4 | 首行↑切上一条到末行；末行↓切下一条到首行 |
| REQ-HIST-5.3 | 首行且 index=0 再↑ → browsing=false、value=draft |
| REQ-HIST-5.4 | 末行且 index=total-1 再↓ → browsing=false、value=draft |
| REQ-HIST-5.2 | 组件测试：翻阅态删到空 → History 行消失 |
| REQ-HIST-6 | 组件测试：翻阅态键入 → History 行消失、字符进入编辑 |
| REQ-HIST-7 | 组件测试：初始无 History 行；↑ 后出现 History n/n |

## 关联实现

- `src/platforms/tui/logic/inputModel.ts`（`stepHistory` 状态转换纯函数、`lastLineIndex`）
- `src/platforms/tui/components/DynamicInput.tsx`（持有状态、调用纯函数、条件渲染 History 行）
