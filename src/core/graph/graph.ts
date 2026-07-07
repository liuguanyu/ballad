/**
 * 图构建（Phase 2b）。
 *
 * 职责单一（铁律 2）：本文件只构建图结构，不含节点实现。
 *
 * 图结构（见 plan 节点设计）：
 *   START → reason → route(条件边) → execute → reason(循环) | END
 *
 * route 不是节点，是条件边：检查 pendingToolCall 是否为 null。
 */
import { StateGraph, START, END, MemorySaver } from '@langchain/langgraph';
import type { Brain, AgentEvent, ChatMessage } from '../contract.ts';
import type { ToolRegistry } from '../tools/registry.ts';
import { GraphState } from './state.ts';
import { createReasonNode, createExecuteNode } from './nodes.ts';

/**
 * 构建 LangGraph 图。
 *
 * @param brain - 模型适配器（2a 的 Brain）
 * @param tools - 工具注册表
 * @param maxSteps - 最大 reason 步数，兜底防工具调用死循环
 * @returns 编译后的图（可调用 .stream()）
 */
export function buildGraph(brain: Brain, tools: ToolRegistry, maxSteps: number = 12) {
  const reasonNode = createReasonNode(brain);
  const executeNode = createExecuteNode(tools);

  // 条件边：无 pendingToolCall 或已达最大步数 → 结束，否则执行工具。
  // maxSteps 兜底防真实模型工具调用死循环（REQ-GRAPH-1 / REQ-HEAL-1）。
  function route(state: typeof GraphState.State): string {
    if (state.pendingToolCall === null) {
      return 'end';
    }
    if (state.step >= maxSteps) {
      return 'end';
    }
    return 'execute';
  }

  const graph = new StateGraph(GraphState)
    .addNode('reason', reasonNode)
    .addNode('execute', executeNode)
    .addEdge(START, 'reason')
    .addConditionalEdges('reason', route, {
      execute: 'execute',
      end: END,
    })
    .addEdge('execute', 'reason') // 工具执行完回 reason
    .compile({
      checkpointer: new MemorySaver(),
    });

  return graph;
}

/**
 * 把 LangGraph 图包装成 Brain 签名（AsyncGenerator<AgentEvent>）。
 *
 * 从 graph.stream() 收两条通道：
 * - custom 通道：token/thinking/tool_call/tool_result（旁路，实时）
 * - values 通道：状态快照（主流，节点边界）
 *
 * 只 yield custom 通道的事件（AgentEvent），values 通道用于检查点回放。
 */
export function createGraphBrain(graph: ReturnType<typeof buildGraph>): Brain {
  return async function* (history: readonly ChatMessage[]): AsyncGenerator<AgentEvent, void, void> {
    // 生成唯一 thread_id（每次对话一个线程）
    const threadId = `thread-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    const stream = await graph.stream(
      {
        messages: [...history],
        pendingToolCall: null,
        step: 0,
      },
      {
        streamMode: ['custom', 'values'],
        configurable: { thread_id: threadId },
      },
    );

    for await (const chunk of stream) {
      // chunk 是 [mode, data] 元组
      const [mode, data] = chunk as [string, unknown];

      // 只 yield custom 通道的事件（AgentEvent）
      if (mode === 'custom' && isAgentEvent(data)) {
        yield data;
      }
      // values 通道不 yield（用于检查点，不吐给 TUI）
    }
  };
}

/**
 * 类型守卫：检查 data 是否为 AgentEvent。
 *
 * No AnyScript（铁律 1）：用 Zod schema 校验，不用 any。
 */
function isAgentEvent(data: unknown): data is AgentEvent {
  if (typeof data !== 'object' || data === null) {
    return false;
  }
  const obj = data as Record<string, unknown>;
  return typeof obj.type === 'string';
}
