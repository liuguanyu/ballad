# Spec: Agent 内核（core-agent · Phase 2b）

## 背景

Phase 2a 的"真实模型接入层"已让大脑能用真模型流式对话，但大脑仍是**无状态 AsyncGenerator**
——只会"线性对话"，不会调工具、不会自我纠错、不能回放。Phase 2b 引入 LangGraph 图状态机，
把大脑升级为"可观察、可纠错、可回放"的内核。

白皮书 Phase 2 的内核是四件**绑在一起**的能力：LangGraph 图状态机（控制流）+ tool-call（工具
节点）+ Self-correction（坏 JSON 重试边）+ Time-Travel（检查点回放）。它们互为依赖：tool-call
的"调用→执行→回喂→续跑"是图循环；Self-correction 是图的重试边；Time-Travel 是图的检查点回放。

裁决链：`AGENTS.md`（铁律）> 本 spec > 代码。本功能属 core 层（图编排、工具是大脑职责），
不进 platforms。守 `tests/arch/redlines.test.ts` 三条红线。`state-management.spec.md` 已界定
LangGraph 属大脑控制流（本阶段引入，符合规划）。

## 关键区分（易混点）

- **LangGraph 图（编排层）**：取代 2a 的线性 selectBrain，是大脑的"控制流层"。图状态对上层
  可见，使 Time-Travel 自然。**不是**藏在适配器里的内部细节（那会让回放难做）。
- **协议适配器（2a，不动）**：降级为图里的"模型节点"——reason 节点调 selectBrain 取模型流。
- **工具（tool）**：图的 execute 节点调用的具体能力（read/write/bash/query），参数经 Zod 校验。
- **Self-correction**：工具参数解析失败不抛错，吐 `tool_result(ok=false)` 回喂模型重试。
- **Time-Travel**：图的检查点回放。2b 用 MemorySaver 跑通回放逻辑；bun:sqlite 落盘标"后续"。
- **tool 嘴巴表现（档 2）**：契约加 `tool_call`/`tool_result` 事件，TUI 加工具气泡（动作+摘要）。
  **不做 diff 渲染**（留 2c），但事件设计为 2c 留口子。

## 分层

```
src/core/
├── contract.ts          # 扩：加 tool_call / tool_result 事件（向后兼容）
├── graph/               # 新增：LangGraph 编排层
│   ├── state.ts         # 图状态：messages + pendingToolCalls + lastToolResults + step
│   ├── graph.ts         # 图构建：reason → route(tools? → execute → reason | end)
│   ├── nodes.ts         # reason 节点（调适配器）、execute 节点（调工具）
│   ├── checkpointer.ts  # MemorySaver 检查点（Time-Travel 底座）
│   └── selfcorrect.ts   # 坏参数重试边 + 上限防死循环
├── tools/               # 新增：工具实现（首批 4 类）
│   ├── registry.ts      # Tool 接口 + 注册表（Zod 校验参数）
│   ├── read.ts          # read_file(path)
│   ├── write.ts         # write_file / edit_file
│   ├── bash.ts          # run_shell(cmd) 白名单 + 超时
│   └── query.ts         # ls / grep（只读）
├── providers/           # 不变（2a 适配器作为图里模型节点）
└── agent.ts             # 不变（createMockBrain 保留）
src/index.ts             # 改：selectBrain → buildGraph
src/platforms/tui/components/LogViewer.tsx  # 改：工具气泡（档 2）
```

## 需求

### REQ-GRAPH-1 图结构与循环
图结构：`reason → route(tools? → execute → reason | end)`。reason 节点调 2a 协议适配器取模型流；
模型若决定调工具（吐 tool_call），进 execute 节点执行工具、回喂结果、回 reason；模型无 tool_call
时 → message_end 结束。设最大步数兜底防死循环。

### REQ-GRAPH-2 tool 事件经契约透传
`tool_call`（模型决定调工具，带 tool 名 + args + callId）与 `tool_result`（执行完，带 ok + summary）
作为 AgentEvent 经 Brain 流吐出，TUI 可观察。`summary` 是摘要（如"读取 foo.ts 120 行"），
**不带完整 diff**（2c 加 diff 视图时可扩字段，不破坏契约）。真实 provider 必须把 `ToolRegistry`
里的工具 schema 注入模型请求，并把 provider 原生工具调用（OpenAI `tool_calls` / Anthropic `tool_use`）
解析为统一 `tool_call` 事件；不得只依赖 mock 模型手写 `tool_call`。

### REQ-TOOL-1 工具参数 Zod 校验
每个工具有 `paramsSchema: ZodSchema`，execute 节点调用前校验。**解析失败不抛错**，吐
`tool_result(ok=false, summary=解析错误)` 回喂模型——这是 Self-correction 的入口。

### REQ-TOOL-2 首批四工具 + 权限边界
- `read_file(path)`：读文件，大文件截断（防 token 爆炸）。
- `write_file(path, content)` / `edit_file(path, oldString, newString)`：写/改文件。
- `run_shell(cmd)`：执行 shell，**白名单**（ls/cat/git status/grep 等只读）+ **超时**；
  危险命令（rm/写/网络）默认拒绝。
- `ls(path)` / `grep(pattern, path)`：只读查询。

### REQ-HEAL-1 Self-correction
工具参数解析失败或执行出错 → `tool_result(ok=false)` → 图回 reason 节点，模型看到错误重试。
设**最大重试次数**（如 3 次），超限则吐 error 事件终止，防死循环。

### REQ-TT-1 Time-Travel 检查点
图每步存检查点（2b 用 MemorySaver，内存）。可回放到任意检查点复现图状态。
bun:sqlite 持久化落盘标"2b 末尾或 2c"——2b 只验回放逻辑可跑通。

### REQ-COMPAT-1 Brain 签名不变 + 2a 不回归
图对外仍暴露 `Brain = (history) => AsyncGenerator<AgentEvent>` 签名。App、所有适配器、
2a 的 218 个测试**零改不回归**。契约加事件是向后兼容（不删现有 6 个）。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-GRAPH-1 | `tests/core/graph/graph.test.ts`：注入 mock 模型（吐固定 tool_call 序列），断言 reason→execute→reason→end 循环 + 最大步数兜底 |
| REQ-GRAPH-2 | `graph.test.ts`：断言流含 tool_call/tool_result 事件且 callId 对应；`providers/*.test.ts`：真实 provider 请求包含工具 schema 且原生 tool call 被映射；`LogViewer.test.tsx`：气泡渲染 |
| REQ-TOOL-1 | `tests/core/tools/*.test.ts`：各工具 happy path；坏参数 → ok=false（不抛错） |
| REQ-TOOL-2 | `bash.test.ts`：白名单放行只读、拒绝 rm/写/网络；超时生效；read/write/query 各自用例 |
| REQ-HEAL-1 | `tests/core/graph/selfcorrect.test.ts`：坏参数→重试→成功；超上限→error 事件终止 |
| REQ-TT-1 | `tests/core/graph/checkpointer.test.ts`：MemorySaver 存检查点 + 回放复现状态 |
| REQ-COMPAT-1 | `tests/core/providers/*`、`tests/tui/App.integration.test.tsx` 全不破坏（2a 回归）；`tests/arch/redlines.test.ts` 覆盖新 core 文件 |

## 关联实现

- `src/core/contract.ts`（加 tool_call/tool_result 事件）
- `src/core/graph/{state,graph,nodes,checkpointer,selfcorrect}.ts`（编排层）
- `src/core/tools/{registry,read,write,bash,query}.ts`（工具层）
- `src/core/providers/*`、`src/core/agent.ts`（2a，不动，作为模型节点被图复用）
- `src/index.ts`（buildGraph 替代 selectBrain）
- `src/platforms/tui/components/LogViewer.tsx`（工具气泡）

## 关联

- 铁律 0/1/2/3（见 `../AGENTS.md`）
- 事件契约 `src/core/contract.ts`（2a 已就位，2b 扩展）
- 状态管理决策 `state-management.spec.md`（已界定 LangGraph 属大脑控制流）
- 真实模型接入 `core-provider.spec.md`（2a，图复用其适配器作为模型节点）
- 产品愿景 `../coding Agent tui需求.md`（白皮书 Phase 2 拆分：2a 接入 / 2b 内核 / 2c 工程）
