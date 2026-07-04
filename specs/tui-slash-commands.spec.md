# Spec: Slash Command 与上拉选择框（tui-slash-commands）

## 背景

对齐 Claude Code / reasonix 的 `/` 命令体验：输入框以 `/` 开头即在其**上方**浮出一个上拉
选择框，随键入前缀实时过滤命令；↑/↓ 移动高亮（最多 8 行可见，超出滚动），Enter 选中执行，
Esc 关闭。这个上拉框是**可复用组件**——后续 MCP list、@文件引用等复用同一"呼出-过滤-选中-退出"
形态。第一个落地命令是 `/exit`（退出 ballad）。

裁决链：`AGENTS.md`（铁律）> 本 spec > 代码。本功能属 TUI 层，**不进 core**
（命令注册、菜单、退出都是嘴巴层概念）。

## 分层与状态模型

- `logic/selectMenu.ts`——泛型菜单状态机（纯函数，无 React/Ink，可脱终端单测）。
- `logic/slashCommands.ts`——命令注册表与 `/` 判定。
- `components/SelectMenu.tsx`——纯渲染上拉框（不含 useInput，键盘由上层驱动）。
- `index.tsx`（App）——编排：持有输入镜像与菜单状态，计算命令模式、过滤、执行命令。

菜单状态：
- `selected: number`——过滤后列表的高亮下标（0-based）。
- `offset: number`——8 行可见窗口的起始下标（滚动）。

菜单项：`{ value, label, hint? }`。命令项：`value='exit'`、`label='/exit'`、`hint='退出 ballad'`。

## 需求

### REQ-CMD-1 命令模式判定
输入框文本以 `/` 开头、且不含空格/换行时进入命令模式。非 `/` 开头，或含空格/换行，均非命令模式。
仅当命令模式**且过滤结果非空**时才渲染菜单。

### REQ-CMD-2 前缀实时过滤
过滤时去掉查询的前导 `/`，对命令的 `value`/`label` 做前缀匹配。`/` → 全部命令；
`/ex` → 仅 `/exit`；`/zz` → 空（不渲染菜单）。键入/退格实时更新过滤结果。

### REQ-CMD-3 高亮移动与窗口滚动
↑/↓ 使 `selected` 在 `[0, n-1]` 钳制（不回绕）。可见窗口最多 `MENU_WINDOW=8` 行：
`selected < offset` → `offset=selected`；`selected >= offset+8` → `offset=selected-7`。
`visibleWindow` 返回当前窗口的项切片，并标记每项是否高亮（active）。

### REQ-CMD-4 选中与关闭
- Enter：选中当前高亮项，执行其命令。
- Esc：**关闭菜单**（菜单从屏幕消失），回到普通输入，**保留已输入文本**。
  关闭是一个独立于输入内容的"已手动关闭"意图：即便文本仍以 `/` 开头，菜单也必须隐藏。
- Esc 关闭后**再次改动输入**（打字或删字，只要文本仍构成命令查询）：菜单重新弹出
  （"已手动关闭"意图在下一次输入变化时清除）。
- 退格删掉开头的 `/`（文本不再以 `/` 开头）：退出命令模式、菜单消失。

### REQ-CMD-5 命令模式下按键让渡
命令模式下，↑/↓/Enter/Esc 的语义由"历史翻阅/提交"切换为"菜单导航/选中/关闭"：
- ↑/↓ 不触发历史翻阅，而是移动菜单高亮；
- Enter 不提交给大脑，而是选中命令；
- 文本编辑（打字、退格）仍照常改写输入 → 驱动过滤。
命令被选中执行后清空输入，且**不进入大脑对话流**。

### REQ-CMD-6 /exit 执行
选中 `/exit` → 调用 app 退出（Ink `useApp().exit()`）。执行路径可被测试注入的 spy 观测。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-CMD-1 | `slashCommands.test.ts`：isCommandQuery 对 `/`、`/exit`、`/e x`、`ab`、``、`/a\n` 的判定 |
| REQ-CMD-2 | `selectMenu.test.ts`：filterItems 前缀过滤（`/`→全部、`/ex`→仅 exit、`/zz`→空） |
| REQ-CMD-3 | `selectMenu.test.ts`：moveSelection 边界钳制；构造 >8 项验证 offset 滚动；visibleWindow 切片+active |
| REQ-CMD-4 | `DynamicInput.test.tsx`：Esc 走 onCancel；退格删掉 `/` 退出命令模式。`App.integration.test.tsx`：Esc 后菜单从帧消失且文本保留；关闭后再打字菜单重弹 |
| REQ-CMD-5 | `DynamicInput.test.tsx`：命令模式 ↑/↓ 走 onNavigate 不走历史；Enter 走 onAccept 不 onSubmit |
| REQ-CMD-6 | `App.integration.test.tsx`：输入 `/` 弹菜单含 /exit；`/ex` 过滤；选中 /exit 触发 exit spy |

## 关联实现

- `src/platforms/tui/logic/selectMenu.ts`（`filterItems`/`moveSelection`/`visibleWindow`/`idleMenuState`）
- `src/platforms/tui/logic/slashCommands.ts`（`SLASH_COMMANDS`/`isCommandQuery`）
- `src/platforms/tui/components/SelectMenu.tsx`（纯渲染上拉框）
- `src/platforms/tui/components/DynamicInput.tsx`（命令模式让渡导航键）
- `src/platforms/tui/index.tsx`（App 编排、命令分发、/exit → 退出）
- `src/platforms/tui/theme.ts`（`selected` 选中行色）
