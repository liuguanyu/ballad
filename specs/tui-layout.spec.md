# Spec: TUI 布局（tui-layout）

## 背景

对齐 Claude Code 的经典 TUI 布局：整屏铺满，上方滚动区、下方固定输入区。
本规格约束整体骨架与三大区域的位置关系。

## 需求

### REQ-LAYOUT-1 全屏占满
TUI 启动后占满整个终端窗口（宽 = 终端列数，高 = 终端行数），随终端 resize 自适应。

### REQ-LAYOUT-2 三段式结构（自上而下）
1. **Header**（固定高）：标题 `▓▓ ballad`、副标题、当前工作目录。
2. **滚动区（LogViewer）**：占据中间**全部剩余高度**（`flexGrow`），渲染会话历史。
3. **状态栏（StatusBar）**（固定高）：运行状态（ready / thinking）+ 累计 Token。
4. **输入区（DynamicInput）**（固定高）：钉在**最底部**，详见 tui-input.spec.md。

### REQ-LAYOUT-3 用户消息反白
滚动区中，用户消息以**反白**（inverse，前景/背景反转）显示；助手消息常规色；
系统/错误消息黄色告警色。
> 注：反白转义 `ESC[7m` 仅在真实 TTY 出现；测试环境（ink-testing-library）因
> chalk 非 TTY 降级不输出颜色码，故反白只在真终端或纯函数层验证。

### REQ-LAYOUT-4 备用屏（alt-screen）
真实 TTY 下启动时进入终端 alternate screen（`ESC[?1049h`），退出时恢复
（`ESC[?1049l`）——占满全屏且退出后不污染原终端内容。非 TTY 环境跳过。

## 验收标准

| 需求 | 验证 |
| :-- | :-- |
| REQ-LAYOUT-1/2 | `tests/tui/app.test.tsx`：启动帧含 Header 文本；滚动区在中间；状态栏与输入区在底部 |
| REQ-LAYOUT-3 | 纯函数/真 pty 验证反白；测试环境断言消息文本存在于滚动区 |
| REQ-LAYOUT-4 | 入口逻辑：`isTTY` 时写入 alt-screen 进/出转义 |

## 关联实现

- `src/platforms/tui/index.tsx`（App、useTerminalSize）
- `src/platforms/tui/components/Header.tsx`、`LogViewer.tsx`、`StatusBar.tsx`
- `src/index.ts`（alt-screen 进出）
