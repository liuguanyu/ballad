# Spec: 状态管理决策（state-management）

## 背景

TUI 状态从少起步（终端尺寸、会话、流式缓冲、busy、Token、输入框历史翻阅），
随功能增长必然要回答"状态放哪、用什么管"。本规格记录**当前决策与触发线**，
避免每次重新论证，并守住脑口分离。

## 关键区分（易混点）

- **LangGraph.js**：Agent 控制流编排（节点/边、状态机推进、检查点回放、
  多 Agent 调度、自愈重试）。属大脑内部"怎么运转"。
- **zustand / useReducer**：UI 状态存取与订阅。属表现层"渲染数据放哪"。
- 两者不在同一层面，不互斥。LangGraph 的 graph state 是编排副产品，
  不供 UI 组件订阅。

## 决策

### REQ-STATE-1 当前不引入任何状态管理库
状态点少（个位数）、全在 `platforms/tui/` 一层、App→直接子组件深度为 1，
无 prop drilling、无跨远房组件共享。用 `useState` + 纯函数状态机（如
`inputModel.stepHistory`）已是干净解法。

### REQ-STATE-2 触发线一：先上 useReducer（零依赖）
当 App 的会话状态（messages/streaming/busy/usage）更新逻辑变复杂、
互相耦合（如一个流式事件要同时改多个 state）时，先用 React 内置 `useReducer`，
不引入第三方库。

### REQ-STATE-3 触发线二：才引入 view store（zustand 是合理选型）
当出现下列之一时，引入一层 framework-agnostic 的 view store（zustand 可）：
- TUI 与 Web 双端共享同一份渲染状态；
- 深层组件（如未来 TreeView、Diff 面板）要读写会话状态且传参路径长。

### REQ-STATE-4 view store 的位置（守住脑口分离）
view store 不得塞进 `platforms/tui/`；应放在 TUI 与 Web 可共享的位置
（贴近 core 或独立一层），作为**大脑事件流的订阅端 / 投影**。
数据的真相在大脑输出的 `AgentEvent`，view store 只把事件累积成可渲染形状。
这样 Phase 4 换表现层时状态层不动，守得住"换嘴巴 core 不动"。

## 验收

非代码约束，以"未引入 zustand 且状态层未下沉到 tui 专属"为现状核验：
- `package.json` 依赖无 zustand 等状态库；
- `src/platforms/tui/` 不出现被 Web 层复用的状态持有逻辑。

## 关联

- 铁律 0 脑口分离、铁律 3 低耦合高内聚（见 `../AGENTS.md`）
- 事件契约 `src/core/contract.ts`
