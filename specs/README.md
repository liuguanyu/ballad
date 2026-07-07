# Ballad 需求规格（Specs）

> 本目录是 ballad 的**功能需求事实来源**（source of truth）。
> 纯 Markdown、不依赖任何工具或 CLI——任何 Coding Agent（Claude Code、Cursor、
> Codex、Aider、Copilot…）或人类都能直接读懂并据此实现、审查、回归。

## 定位与裁决链

- **架构铁律**看 `../AGENTS.md`（脑口分离 / 无 any / 职责单一 / 低耦合）——最高约束。
- **功能需求细节**看本目录的 `*.spec.md`。
- **产品愿景**看 `../coding Agent tui需求.md`（白皮书，愿景层，不逐条约束实现）。

裁决优先级（冲突时以左为准）：

```
AGENTS.md（铁律） > specs/*.spec.md（功能需求） > 代码
```

## 规格清单

| 规格 | 覆盖范围 |
| :-- | :-- |
| [tui-layout.spec.md](./tui-layout.spec.md) | 全屏布局、Header、滚动区、状态栏、alt-screen |
| [tui-input.spec.md](./tui-input.spec.md) | 输入区：动态高度、History 压线、上下横线、编辑键 |
| [tui-history.spec.md](./tui-history.spec.md) | 历史翻阅状态机：进出翻阅、多行光标、退出触发 |
| [tui-slash-commands.spec.md](./tui-slash-commands.spec.md) | Slash 命令与可复用上拉选择框：呼出、前缀过滤、选中、退出；/exit |
| [tui-hotkeys.spec.md](./tui-hotkeys.spec.md) | 全局快捷键与面板切换：Ctrl+O 切换详情面板，且不干扰大脑流式 |
| [tui-clipboard.spec.md](./tui-clipboard.spec.md) | 剪贴板粘贴：Ctrl+V 文本/图片，跨平台 CLI 桥接，图片写 .agent/temp/ |
| [tui-shimmer.spec.md](./tui-shimmer.spec.md) | 流光文字：微光扫过文字（cc 思考态呼吸感）+ 可选 spinner；组件/hook/纯逻辑三层 |
| [state-management.spec.md](./state-management.spec.md) | 状态管理决策：当前不引库，useReducer / view store 的触发线 |
| [core-provider.spec.md](./core-provider.spec.md) | 真实模型接入层：按 wire protocol 分适配器（anthropic/openai-v1/openai-v2/mock）、多模型注册表、配置路由、无 key 回落 mock |
| [core-agent.spec.md](./core-agent.spec.md) | Agent 内核：LangGraph 图状态机 + tool-call（read/write/bash/query）+ Self-correction + Time-Travel；契约加 tool_call/tool_result 事件，Brain 签名不变 |

## 编写约定

每份 spec 用统一结构，使规则可被机器和人对齐到测试：

- **背景**：为什么有这条需求。
- **需求（REQ-xxx）**：每条编号，一句话可判定。
- **验收标准**：可对应到具体测试用例（给出测试文件与用例名）。
- **关联实现**：对应的源码文件。

改需求：**先改 spec，再改代码与测试**。测试是 spec 的可执行证明。
