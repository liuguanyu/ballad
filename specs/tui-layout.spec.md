# Spec: TUI 布局（tui-layout）

## 背景

对齐 Claude Code 的经典 TUI 布局：整屏铺满，上方滚动区、下方固定输入区。
本规格约束整体骨架与三大区域的位置关系。

## 需求

### REQ-LAYOUT-1 全屏占满
TUI 启动后占满整个终端窗口（宽 = 终端列数，高 = 终端行数），随终端 resize 自适应。

### REQ-LAYOUT-2 固定骨架（自上而下）
1. **Header**（固定高）：标题 `▓▓ ballad`、副标题、当前工作目录。
2. **滚动区（LogViewer）**：占据中间**全部剩余高度**（`flexGrow`），只渲染会话历史、工具事件与流式正文。
3. **思考提示（ThinkingBar）**（条件固定高）：仅 busy 且正文未开始时出现，贴在输入框上横线正上方。
4. **输入区（DynamicInput）**（固定高）：靠近底部，详见 tui-input.spec.md。
5. **状态栏（StatusBar）**（固定高）：位于输入区下方，展示运行状态（ready / thinking）+ 累计 Token。

### REQ-LAYOUT-3 用户消息整行反白
滚动区中，用户消息以**整行反白**（inverse，前景/背景反转）显示：反白背景必须从终端第 1 列贯通到当前列宽末尾，而不是只包住消息文本；助手消息常规色；系统/错误消息黄色告警色。
> 注：反白转义 `ESC[7m` 仅在真实 TTY 出现；测试环境（ink-testing-library）因
> chalk 非 TTY 降级不输出颜色码，故反白只在真终端或纯函数层验证行宽 padding。

### REQ-LAYOUT-4 备用屏（alt-screen）
真实 TTY 下启动时进入终端 alternate screen（`ESC[?1049h`），退出时恢复
（`ESC[?1049l`）——占满全屏且退出后不污染原终端内容。非 TTY 环境跳过。

### REQ-LAYOUT-5 超屏尾部锚定（滚动不错乱）
会话内容超过滚动区可用高度时，滚动区**永远锚定最新内容**（显示尾部，
裁掉顶部旧消息），流式生成中的文本必须始终可见。实现约束：

1. **不得依赖 Ink 的 `overflow=hidden` 做主裁剪**——Yoga 裁的是内容底部
   （显示头部），超屏时最新消息反而被裁掉，与终端自身滚动叠加产生行序错乱。
2. 滚动区渲染前须把消息流按终端列宽**预折行**为显示行（CJK 按 2 列计宽），
   再按可用高度预算截取**最后 N 行**——每帧输出行数恒定（抗闪）且尾部锚定。
3. 可用高度预算 = 终端行数 − 所有固定块（Header / 详情 / 菜单 / 输入框 /
   状态栏）的实际占高，由 App 计算后传入滚动区；如果剩余高度小于 0，滚动区必须渲染 0 行，不能把历史内容挤到输入框/状态栏之外。

### REQ-LAYOUT-6 思考提示贴近输入区
忙碌且尚未吐出正文时，思考提示不属于历史消息流，而属于底部运行提示：它必须固定渲染在输入框**上横线的正上方**，与输入框保持贴近。思考持续一段时间后，提示文案应显示经过秒数（如 `thinking… 3s`）。收到首个正文 token 后思考提示消失，状态栏仍显示 busy/token 信息。

## 验收标准

| 需求 | 验证 |
| :-- | :-- |
| REQ-LAYOUT-1/2 | `tests/tui/app.test.tsx`：启动帧含 Header 文本；滚动区在中间；状态栏与输入区在底部 |
| REQ-LAYOUT-3 | `tests/tui/logLines.test.ts`：用户消息显示行 padding 到列宽；真 pty 验证整行反白 |
| REQ-LAYOUT-4 | 入口逻辑：`isTTY` 时写入 alt-screen 进/出转义 |
| REQ-LAYOUT-5 | `tests/tui/logLines.test.ts`：超预算时尾部切片含最新消息、不含最旧消息；流式文本恒在尾部；CJK 宽度折行正确；0 高度返回空 |
| REQ-LAYOUT-6 | `tests/tui/App.integration.test.tsx`：thinking 行位于输入框上横线正上方；持续后显示 elapsed 秒数；首个正文 token 后消失 |

## 关联实现

- `src/platforms/tui/index.tsx`（App、useTerminalSize、logHeight 预算）
- `src/platforms/tui/components/Header.tsx`、`LogViewer.tsx`、`StatusBar.tsx`
- `src/platforms/tui/logic/logLines.ts`（预折行 + 尾部切片纯逻辑）
- `src/index.ts`（alt-screen 进出）
