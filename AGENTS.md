# Ballad — 项目工程铁律 (Engineering Constitution)

> 本文件是 ballad 项目的最高工程契约。所有 `src/` 下的代码在编写、审查、重构时，
> 裁决优先级高于个人习惯。违反任意一条即视为不可合并。
>
> **功能需求细节**见 [`specs/`](./specs/)（agent-中立的纯 Markdown 规格）。
> 裁决链：**本文件（铁律） > specs/*.spec.md（功能需求） > 代码**。
> 改需求先改 spec，再改代码与测试；测试是 spec 的可执行证明。

## 铁律 0 —— 脑口分离 (Brain / Mouth Separation)

- `src/core/`（大脑）：100% 纯逻辑与计算。**禁止** import 任何与终端、颜色、
  光标、Ink、React 渲染相关的依赖。
- `src/platforms/`（嘴巴）：多端表现层。**禁止** 包含任何大模型调用与状态图
  重试逻辑。
- 两层唯一通信媒介：`src/core/contract.ts` 中用 Zod 定义的结构化事件。

## 铁律 1 —— 严格禁止 AnyScript（No `any`）

- **严禁** 使用 `any` 类型。类型不明时用 `unknown` 并做收窄，或用泛型、
  联合类型、Zod schema 推导（`z.infer`）表达。
- 严禁用 `as any`、`@ts-ignore`、`@ts-expect-error` 绕过类型系统；确需忽略
  必须写明原因并经审查。
- 所有跨层数据（大脑 → 嘴巴的事件）类型必须由 Zod schema 推导，单一事实来源。
- tsconfig 保持 `strict: true`，且开启 `noUncheckedIndexedAccess`
  `noUnusedLocals` `noUnusedParameters`，`tsc --noEmit` 必须零报错。

## 铁律 2 —— 职责单一 (Single Responsibility)

- 一个模块 / 一个函数 / 一个 React 组件只做一件事，只有一个变更理由。
- 文件按职责命名与拆分：契约、大脑编排、模型实例、索引引擎各自独立成文件。
- 组件不得同时承担「数据获取 + 状态管理 + 渲染」；渲染组件保持无副作用，
  副作用集中在入口 / hook。

## 铁律 3 —— 低耦合高内聚 (Low Coupling, High Cohesion)

- 依赖方向单向：`platforms/` → `core/contract.ts`，禁止反向依赖。
- 强相关的逻辑与类型放在同一模块内聚；跨模块只通过明确的导出接口通信，
  不透传内部实现细节。
- 优先依赖抽象（事件 schema、接口）而非具体实现；替换某一端（如 TUI → Web）
  时 `core/` 应一行不改。
