/**
 * 图状态定义（Phase 2b）。
 *
 * LangGraph 的 Annotation.Root 定义图状态。状态对上层可见（方案 B），
 * 是 Time-Travel 回放的对象。
 *
 * - messages：会话消息（含工具调用/结果，喂回模型作上下文）。
 * - pendingToolCall：reason 节点产出的待执行工具调用（null 表示模型无工具调用 → 结束）。
 * - step：图步数，用于最大步数兜底防死循环。
 */
import { Annotation } from '@langchain/langgraph';
import type { ChatMessage } from '../contract.ts';

/** 待执行的工具调用（reason 节点产出，execute 节点消费）。 */
export interface PendingToolCall {
  readonly callId: string;
  readonly tool: string;
  readonly args: Record<string, unknown>;
}

export const GraphState = Annotation.Root({
  messages: Annotation<ChatMessage[]>({
    reducer: (a, b) => [...a, ...b],
    default: () => [],
  }),
  pendingToolCall: Annotation<PendingToolCall | null>({
    reducer: (_a, b) => b, // 后值覆盖
    default: () => null,
  }),
  step: Annotation<number>({
    reducer: (a, b) => a + b,
    default: () => 0,
  }),
});

export type GraphStateType = typeof GraphState.State;
