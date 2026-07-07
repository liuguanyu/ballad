/**
 * anthropic 适配器测试（Phase 2a）。
 *
 * 覆盖 spec REQ-PROV-3：把 Anthropic /v1/messages 流式 raw 事件映射为 AgentEvent。
 * 注入 mock client 吐固定事件序列，断言映射（含 thinking / usage / error 路径）。零网络。
 */
import { test, expect, describe } from 'bun:test';
import { z } from 'zod';
import { anthropicAdapter, type AnthropicStreamClient } from '../../../src/core/providers/anthropic.ts';
import { selectBrain, type ModelConfig } from '../../../src/core/provider.ts';
import type { AgentEvent } from '../../../src/core/contract.ts';
import type { Tool } from '../../../src/core/tools/registry.ts';

function model(): ModelConfig {
  return { name: 'claude', protocol: 'anthropic', model: 'claude-sonnet-4-5' };
}

const fakeTool: Tool = {
  name: 'ls',
  description: 'list files',
  paramsSchema: z.object({ path: z.string() }),
  jsonSchema: {
    type: 'object',
    properties: { path: { type: 'string' } },
    required: ['path'],
    additionalProperties: false,
  },
  run: async () => ({ ok: true, summary: 'ok' }),
};

/** 构造 mock client：吐一组 raw 事件。 */
function clientWith(events: unknown[]): AnthropicStreamClient {
  return {
    async *stream() {
      for (const ev of events) {
        yield ev;
      }
    },
  };
}

async function run(client: AnthropicStreamClient): Promise<AgentEvent[]> {
  const brain = anthropicAdapter(model(), { anthropic: client });
  const out: AgentEvent[] = [];
  for await (const ev of brain([{ role: 'user', content: 'hi' }])) {
    out.push(ev);
  }
  return out;
}

describe('REQ-PROV-3 · anthropic 流式映射', () => {
  test('message_start → message_start', async () => {
    const events = await run(clientWith([{ type: 'message_start' }, { type: 'message_stop' }]));
    expect(events[0]?.type).toBe('message_start');
  });

  test('text_delta → token，拼接出正文', async () => {
    const events = await run(
      clientWith([
        { type: 'message_start' },
        { type: 'content_block_delta', delta: { type: 'text_delta', text: 'Hel' } },
        { type: 'content_block_delta', delta: { type: 'text_delta', text: 'lo' } },
        { type: 'message_delta', usage: { output_tokens: 2 } },
        { type: 'message_stop' },
      ]),
    );
    const text = events
      .filter((e) => e.type === 'token')
      .map((e) => (e.type === 'token' ? e.text : ''))
      .join('');
    expect(text).toBe('Hello');
  });

  test('thinking_delta → thinking', async () => {
    const events = await run(
      clientWith([
        { type: 'message_start' },
        { type: 'content_block_delta', delta: { type: 'thinking_delta', thinking: 'let me think' } },
        { type: 'content_block_delta', delta: { type: 'text_delta', text: 'ok' } },
        { type: 'message_delta', usage: { output_tokens: 1 } },
        { type: 'message_stop' },
      ]),
    );
    expect(events.some((e) => e.type === 'thinking')).toBe(true);
  });

  test('message_delta.usage → message_end.usage', async () => {
    const events = await run(
      clientWith([
        { type: 'message_start' },
        { type: 'message_delta', usage: { input_tokens: 5, output_tokens: 8 } },
        { type: 'message_stop' },
      ]),
    );
    const end = events.find((e) => e.type === 'message_end');
    expect(end).toBeDefined();
    if (end?.type === 'message_end') {
      expect(end.usage?.inputTokens).toBe(5);
      expect(end.usage?.outputTokens).toBe(8);
    }
  });

  test('无 message_delta 时流末补 message_end', async () => {
    const events = await run(
      clientWith([{ type: 'message_start' }, { type: 'message_stop' }]),
    );
    expect(events[events.length - 1]?.type).toBe('message_end');
  });

  test('client 抛错 → 吐 error 事件不中断生成器签名', async () => {
    const failingClient: AnthropicStreamClient = {
      async *stream() {
        throw new Error('network down');
        yield; // unreachable，满足 generator 语法
      },
    };
    const events = await run(failingClient);
    const err = events.find((e) => e.type === 'error');
    expect(err).toBeDefined();
    if (err?.type === 'error') {
      expect(err.message).toContain('network down');
    }
  });

  test('注入 client 缺 stream 方法 → 抛错', () => {
    expect(() => anthropicAdapter(model(), { anthropic: {} })).toThrow(/no stream\(\) method/);
  });

  test('deps.anthropic 缺失 → 抛错', () => {
    expect(() => anthropicAdapter(model(), {})).toThrow(/not provided/);
  });
});

describe('REQ-GRAPH-2 · anthropic 工具调用闭环', () => {
  test('请求把工具 schema 注入 tools 参数', async () => {
    let capturedTools: readonly { name: string }[] | undefined;
    const client: AnthropicStreamClient = {
      async *stream(params) {
        capturedTools = params.tools;
        yield { type: 'message_start' };
        yield { type: 'message_stop' };
      },
    };
    const brain = anthropicAdapter(model(), { anthropic: client, tools: [fakeTool] });
    for await (const _ of brain([{ role: 'user', content: 'hi' }])) {
      void _;
    }
    expect(capturedTools?.[0]?.name).toBe('ls');
  });

  test('tool_use 块 + input_json_delta → 统一 tool_call 事件', async () => {
    const events = await run(
      clientWith([
        { type: 'message_start' },
        { type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id: 'tu_1', name: 'ls' } },
        { type: 'content_block_delta', index: 0, delta: { type: 'input_json_delta', partial_json: '{"path":' } },
        { type: 'content_block_delta', index: 0, delta: { type: 'input_json_delta', partial_json: '"."}' } },
        { type: 'content_block_stop', index: 0 },
        { type: 'message_stop' },
      ]),
    );
    const call = events.find((e) => e.type === 'tool_call');
    expect(call).toBeDefined();
    if (call?.type === 'tool_call') {
      expect(call.tool).toBe('ls');
      expect(call.args).toEqual({ path: '.' });
      expect(call.callId).toBe('tu_1');
    }
  });
});

describe('REQ-PROV-1 · anthropic 适配器已注册到路由表', () => {
  // 通过 import 即注册（本文件顶部 import 了适配器模块）
  test('protocol=anthropic 路由不抛"no adapter"', () => {
    const brain = selectBrain(
      { models: [model()], active: 'claude' },
      { anthropic: clientWith([{ type: 'message_start' }, { type: 'message_stop' }]) },
    );
    expect(typeof brain).toBe('function');
  });
});
