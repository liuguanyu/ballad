# Spec: 真实模型接入层（core-provider）

## 背景

phase1 大脑是 `createMockBrain`（`src/core/agent.ts`）——自编回复逐字吐 token，不碰真实模型。
phase2 的目标是接真实模型，但模型协议是浮动的：同一供应商可能说不同协议（OpenAI 官方 v1/v2 并存，
多数内网网关是 OpenAI v1 兼容，Anthropic 是第三套事件模型）。故本规格定义一层**按 wire protocol
分适配器**的接入层，让品牌差异退化为同协议下的配置差异（base_url / apiKey / model / headers），
并支持多模型注册表、运行时切换。

本阶段为 **Phase 2a**：只做"真实模型接入 + 多模型可切换"，**不碰** LangGraph、tool-call、
Self-correction（那是 Phase 2b）。大脑仍是**无状态 AsyncGenerator**。

裁决链：`AGENTS.md`（铁律）> 本 spec > 代码。本功能属 core 层（模型调用、协议适配是大脑职责），
**不进 platforms**。守 `tests/arch/redlines.test.ts` 三条红线（core 不碰终端、core 不反向依赖
platforms、全源码无 any）。

## 关键区分（易混点）

- **协议（wire protocol）**：模型流式响应的事件形态。本规格分四种：`anthropic`（/v1/messages）、
  `openai-v1`（/v1/chat/completions）、`openai-v2`（/v1/responses）、`mock`（离线）。
  **路由按协议，不按品牌**——内网网关只要实现 OpenAI v1 兼容，就用 `openai-v1` 适配器 + 自定义
  base_url，零代码接入。
- **适配器（adapter）**：每个协议一个，职责单一——把该协议的原始流式 chunk 收敛成统一 `AgentEvent`
  （`message_start`/`thinking`/`token`/`message_end`/`error`）。不持有状态、不读 env。
- **模型实例（model config）**：注册表里的一条记录，声明 name + protocol + base_url + apiKey +
  model + headers。同一个 `openai-v1` 协议下可以有多个实例（官方 GPT、内网网关、自建 vLLM）。
- **路由（selectBrain）**：纯函数，按激活实例的 protocol 选适配器，注入 SDK client，返回 `Brain`。
  不读 env、不 new client（client 由 `index.ts` 通过依赖注入传入，便于单测注入 mock client）。

## 分层

```
src/core/
├── contract.ts              # 不变（Brain / AgentEvent 已就位）
├── agent.ts                 # 保留 createMockBrain（被 mock 适配器复用）
├── provider.ts              # 协议枚举 + ModelConfig + ProviderRegistry + AdapterDeps + selectBrain
└── providers/               # 每协议一文件（铁律 2 职责单一）
    ├── mock.ts              # 委托 createMockBrain（无 key 离线 fallback）
    ├── anthropic.ts         # /v1/messages 流 → AgentEvent
    ├── openaiChat.ts        # /v1/chat/completions 流 → AgentEvent
    └── openaiResponses.ts   # /v1/responses 流 → AgentEvent
src/index.ts                 # 读 env → 构造 registry → selectBrain → 注入 App（唯一副作用聚集处）
```

## 需求

### REQ-PROV-1 按 wire protocol 路由
`selectBrain(registry, deps)` 按 `registry.active` 指向实例的 `protocol` 字段分发到对应适配器。
路由只认 protocol，不认品牌。同协议下的品牌差异（base_url / model / headers）仅由 `ModelConfig`
表达，适配器代码不分支。`protocol` 由 Zod 枚举 `['anthropic','openai-v1','openai-v2','mock']` 约束。

### REQ-PROV-2 多模型注册表
`ProviderRegistry` 持有 `models: ModelConfig[]` 与 `active: string`（激活实例 name）。
运行时按 name 切换激活项即换模型，无需重启进程（本阶段切换由接线层在启动时定；运行中热切的交互
留待后续）。`ModelConfig` 由 Zod schema 推导（单一事实来源）。

### REQ-PROV-3 协议流式响应映射为 AgentEvent
各适配器把对应协议的原始流式响应正确收敛为 `AgentEvent`：
- **anthropic**：`message_start` → message_start；`content_block_delta`（text）→ token；
  thinking delta → thinking；`message_delta.usage` → message_end.usage。
- **openai-v1**：首个 chunk 触发 message_start；`choices[].delta.content` → token；
  流末 usage（开 `stream_options.include_usage`）→ message_end.usage；该协议无原生 thinking。
- **openai-v2**：`response.created` → message_start；`response.output_text.delta` → token；
  reasoning delta → thinking；`response.completed.usage` → message_end.usage。
- **mock**：委托 `createMockBrain`，事件序列与现有 mock 一致。
任一适配器出错（网络/解析）→ 吐 `error` 事件而非抛异常中断流。

### REQ-PROV-4 无真实 key 回落 mock
启动时若没有任何真实协议的 key（ANTHROPIC_API_KEY / OPENAI_API_KEY / INTRANET_*），registry 仅含
mock 实例，`active=mock`。保证开箱即跑、CI 无 key 也能测。该回落逻辑在 `index.ts`，不在 core。

### REQ-PROV-5 零 any（红线守护）
SDK 原始 chunk 一律先按 `unknown` 收窄或经 Zod schema 解析后再取字段，**禁止** `any`/`as any`/
`@ts-ignore`/`@ts-expect-error`。由 `tests/arch/redlines.test.ts` 静态扫描强制。

### REQ-PROV-6 副作用边界：core 不读 env
`src/core/` 内任何文件不得读取 `process.env`。env 读取与 registry 构造只在 `src/index.ts`
（接线点）。`selectBrain` 是纯函数，`AdapterDeps`（SDK client 工厂）由 `index.ts` 注入。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-PROV-1 | `tests/core/provider.test.ts`：selectBrain 按 protocol 分发到四个适配器；非法 protocol 抛错 |
| REQ-PROV-2 | `tests/core/provider.test.ts`：ModelConfig Zod 校验（缺 name/model 拒绝）；active 按 name 选中正确实例 |
| REQ-PROV-3 | `anthropic.test.ts`/`openaiChat.test.ts`/`openaiResponses.test.ts`/`mock.test.ts`：各喂 mock 流式输入，断言吐出 AgentEvent 序列（含 thinking/usage）；流中出错吐 error 不中断 |
| REQ-PROV-4 | `index.ts` 行为由 `provider.test.ts` 间接覆盖（无 key → registry 仅 mock）；真实启动冒烟由用户实机 |
| REQ-PROV-5 | `tests/arch/redlines.test.ts`：新 core 文件扫描无 any/as any/@ts-ignore（现有测试自动覆盖新文件） |
| REQ-PROV-6 | `tests/arch/redlines.test.ts` 或 `provider.test.ts`：core 源码无 `process.env`（视实现可补一条静态断言） |

## 关联实现

- `src/core/contract.ts`（`Brain` / `AgentEvent`——本层不改，只复用）
- `src/core/provider.ts`（`WireProtocolSchema`/`ModelConfigSchema`/`ProviderRegistry`/`AdapterDeps`/`selectBrain`）
- `src/core/providers/mock.ts`（委托 `createMockBrain`）
- `src/core/providers/anthropic.ts`、`openaiChat.ts`、`openaiResponses.ts`（协议适配器）
- `src/core/agent.ts`（保留 `createMockBrain`，被 mock 适配器复用）
- `src/index.ts`（读 env → registry → selectBrain → App）
- `.env.example`（各协议环境变量样例）

## 关联

- 铁律 0 脑口分离、铁律 1 No Any、铁律 2 职责单一、铁律 3 低耦合（见 `../AGENTS.md`）
- 事件契约 `src/core/contract.ts`
- 状态管理决策 `state-management.spec.md`（已界定 LangGraph 属 2b，本轮不引入）
- 产品愿景 `../coding Agent tui需求.md`（白皮书 Phase 2 拆分：2a 接入层 / 2b LangGraph+tool / 2c 工程）
