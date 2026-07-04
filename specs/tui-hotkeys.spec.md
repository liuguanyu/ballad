# Spec: 全局快捷键与面板切换（tui-hotkeys）

## 背景

白皮书 Phase 1 施工项 2 后半句：「配合全局 useInput 捕获 **Ctrl+O**，触发 React
侧边栏/详情面板的展开与隐藏」，需求矩阵「全局快捷键掌控」：按下后动态切换表现层布局状态
（如全屏展开/收起 Agent 思考细节面板），**不影响后台大脑运转**。

Phase 1 只做**骨架**：一个可由 Ctrl+O 切换显隐的「详情面板」，面板内容先放最小占位
（如提示文本 + 当前会话计数），关键在于**切换机制正确**且**与大脑流式完全解耦**
（切换纯是渲染层状态，不触碰 messages/streaming/busy，不打断正在进行的流式消费）。

裁决链：`AGENTS.md`（铁律）> 本 spec > 代码。快捷键与面板是纯表现层关注点，**不进 core**。

## 需求

### REQ-HOTKEY-1 Ctrl+O 切换面板显隐
全局捕获 `Ctrl+O`：每按一次，翻转「详情面板」的显隐状态（show ⇄ hide），初始隐藏。

### REQ-HOTKEY-2 面板不干扰大脑
面板显隐是纯渲染层状态（`useState<boolean>`）：
- 切换时**不改**会话状态（messages / streaming / busy / usage）；
- 大脑正在流式吐字时切换面板，流式**不中断、不丢字**（消费循环与面板状态无耦合）；
- 面板打开时输入区仍可用（除非 busy 本身禁用）。

### REQ-HOTKEY-3 面板位置与内容（Phase 1 占位）
面板出现在滚动区与输入区之间（不遮挡输入区），Phase 1 内容为最小占位：
标题「Details」+ 至少一项可观测运行信息（如累计消息条数 / token）。
后续 Phase 2/3 再填思考细节、Diff 视图等。

### REQ-HOTKEY-4 与命令菜单互不冲突
命令菜单（slash）打开时，Ctrl+O 仍可切换详情面板；两者是独立的浮层状态，
互不关闭对方（除非产品后续另有约定）。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-HOTKEY-1 | `App.integration.test.tsx`：初始无面板标记；Ctrl+O 后出现「Details」；再 Ctrl+O 消失 |
| REQ-HOTKEY-2 | 同上：流式进行中按 Ctrl+O，助手回复仍完整落库（不丢字） |
| REQ-HOTKEY-3 | 同上：面板内含标题「Details」与一项运行信息 |

## 关联实现

- `src/platforms/tui/index.tsx`（App：`Ctrl+O` 捕获、`detailsOpen` 状态、条件渲染面板）
- `src/platforms/tui/components/DetailsPanel.tsx`（纯渲染占位面板）
