/**
 * 图测试（Phase 2b）。
 *
 * 覆盖 REQ-GRAPH-1（图结构）/ REQ-GRAPH-2（tool 事件透传）。
 * 注入 mock 模型节点（吐固定 tool_call 序列），断言图循环 + tool_call/tool_result 事件。
 */
import { test, expect, describe } from 'bun:test';
import { buildGraph, createGraphBrain } from '../../../src/core/graph/graph.ts';
import { ToolRegistry } from '../../../src/core/tools/registry.ts';
import { readTool } from '../../../src/core/tools/read.ts';
import type { Brain, AgentEvent, ChatMessage } from '../../../src/core/contract.ts';

/**
 * 创建 mock 模型：第一次调返回 tool_call，第二次调返回普通文本。
 */
function createMockBrainWithToolCall(): Brain {
  let callCount = 0;
  return async function* (_history: readonly ChatMessage[]): AsyncGenerator<AgentEvent, void, void> {
    callCount++;
    yield { type: 'message_start', role: 'assistant' };

    if (callCount === 1) {
      // 第一次：决定调 read_file
      yield {
        type: 'tool_call',
        tool: 'read_file',
        args: { path: '/tmp/test.txt' },
        callId: 'call-1',
      };
    } else {
      // 第二次：看到工具结果，返回普通文本
      yield { type: 'token', text: '已读取文件' };
    }

    yield { type: 'message_end' };
  };
}

describe('REQ-GRAPH-1 · 图结构：reason→tool?→execute→loop→end', () => {
  test('模型无 tool_call 时直接结束', async () => {
    const mockBrain: Brain = async function* () {
      yield { type: 'message_start', role: 'assistant' };
      yield { type: 'token', text: 'hello' };
      yield { type: 'message_end' };
    };

    const tools = new ToolRegistry();
    const graph = buildGraph(mockBrain, tools);
    const brain = createGraphBrain(graph);

    const events: AgentEvent[] = [];
    for await (const event of brain([{ role: 'user', content: 'hi' }])) {
      events.push(event);
    }

    expect(events.some((e) => e.type === 'token')).toBe(true);
    expect(events.some((e) => e.type === 'tool_call')).toBe(false);
  });

  test('模型调工具 → execute → 结果回喂 → 模型续跑 → 结束', async () => {
    const mockBrain = createMockBrainWithToolCall();
    const tools = new ToolRegistry();
    tools.register(readTool);

    const graph = buildGraph(mockBrain, tools);
    const brain = createGraphBrain(graph);

    const events: AgentEvent[] = [];
    for await (const event of brain([{ role: 'user', content: '读文件' }])) {
      events.push(event);
    }

    // 应该有 tool_call 事件
    const toolCallEvents = events.filter((e) => e.type === 'tool_call');
    expect(toolCallEvents.length).toBe(1);
    if (toolCallEvents[0]?.type === 'tool_call') {
      expect(toolCallEvents[0].tool).toBe('read_file');
    }

    // 应该有 tool_result 事件
    const toolResultEvents = events.filter((e) => e.type === 'tool_result');
    expect(toolResultEvents.length).toBe(1);

    // 应该有第二次模型的 token（"已读取文件"）
    const tokenEvents = events.filter((e) => e.type === 'token');
    expect(tokenEvents.some((e) => e.type === 'token' && e.text === '已读取文件')).toBe(true);
  });
});

describe('REQ-GRAPH-2 · tool_call/tool_result 事件经契约透传', () => {
  test('tool_call 事件含 tool/args/callId', async () => {
    const mockBrain = createMockBrainWithToolCall();
    const tools = new ToolRegistry();
    tools.register(readTool);

    const graph = buildGraph(mockBrain, tools);
    const brain = createGraphBrain(graph);

    const events: AgentEvent[] = [];
    for await (const event of brain([{ role: 'user', content: '读文件' }])) {
      events.push(event);
    }

    const toolCall = events.find((e) => e.type === 'tool_call');
    expect(toolCall).toBeDefined();
    if (toolCall?.type === 'tool_call') {
      expect(toolCall.tool).toBe('read_file');
      expect(toolCall.args).toEqual({ path: '/tmp/test.txt' });
      expect(toolCall.callId).toBe('call-1');
    }
  });

  test('tool_result 事件含 ok/summary', async () => {
    const mockBrain = createMockBrainWithToolCall();
    const tools = new ToolRegistry();
    tools.register(readTool);

    const graph = buildGraph(mockBrain, tools);
    const brain = createGraphBrain(graph);

    const events: AgentEvent[] = [];
    for await (const event of brain([{ role: 'user', content: '读文件' }])) {
      events.push(event);
    }

    const toolResult = events.find((e) => e.type === 'tool_result');
    expect(toolResult).toBeDefined();
    if (toolResult?.type === 'tool_result') {
      expect(typeof toolResult.ok).toBe('boolean');
      expect(typeof toolResult.summary).toBe('string');
    }
  });
});
