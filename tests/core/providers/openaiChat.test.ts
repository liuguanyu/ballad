/**
 * openai-v1 适配器测试（Phase 2a）。
 *
 * 覆盖 spec REQ-PROV-3：/v1/chat/completions 流式 chunk 映射为 AgentEvent。
 * 注入 mock client 吐固定 chunk 序列，断言映射（含 usage 单独 chunk / 首chunk触发 start / error）。零网络。
 */
import { test, expect, describe } from 'bun:test';
import { z } from 'zod';
import { openaiChatAdapter, type OpenAIChatClient } from '../../../src/core/providers/openaiChat.ts';
import { selectBrain, type ModelConfig } from '../../../src/core/provider.ts';
import type { AgentEvent } from '../../../src/core/contract.ts';
import type { Tool } from '../../../src/core/tools/registry.ts';

function model(): ModelConfig {
  return { name: 'gpt', protocol: 'openai-v1', model: 'gpt-4o' };
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

function clientWith(chunks: unknown[]): OpenAIChatClient {
  return {
    async *stream() {
      for (const c of chunks) {
        yield c;
      }
    },
  };
}

async function run(client: OpenAIChatClient): Promise<AgentEvent[]> {
  const brain = openaiChatAdapter(model(), { openai: client });
  const out: AgentEvent[] = [];
  for await (const ev of brain([{ role: 'user', content: 'hi' }])) {
    out.push(ev);
  }
  return out;
}

describe('REQ-PROV-3 · openai-v1 流式映射', () => {
  test('首个有 choices 的 chunk → message_start', async () => {
    const events = await run(
      clientWith([
        { choices: [{ delta: { content: 'Hi' }, finish_reason: null }] },
        { choices: [], usage: { prompt_tokens: 3, completion_tokens: 1 } },
      ]),
    );
    expect(events[0]?.type).toBe('message_start');
  });

  test('delta.content → token，拼接正文', async () => {
    const events = await run(
      clientWith([
        { choices: [{ delta: { content: 'Hel' }, finish_reason: null }] },
        { choices: [{ delta: { content: 'lo' }, finish_reason: null }] },
        { choices: [], usage: { prompt_tokens: 3, completion_tokens: 2 } },
      ]),
    );
    const text = events
      .filter((e) => e.type === 'token')
      .map((e) => (e.type === 'token' ? e.text : ''))
      .join('');
    expect(text).toBe('Hello');
  });

  test('usage 单独 chunk（choices 空）→ message_end.usage', async () => {
    const events = await run(
      clientWith([
        { choices: [{ delta: { content: 'ok' }, finish_reason: null }] },
        { choices: [], usage: { prompt_tokens: 5, completion_tokens: 1 } },
      ]),
    );
    const end = events.find((e) => e.type === 'message_end');
    expect(end).toBeDefined();
    if (end?.type === 'message_end') {
      expect(end.usage?.inputTokens).toBe(5);
      expect(end.usage?.outputTokens).toBe(1);
    }
  });

  test('无 usage chunk 时流末补 message_end', async () => {
    const events = await run(
      clientWith([{ choices: [{ delta: { content: 'x' }, finish_reason: 'stop' }] }]),
    );
    expect(events[events.length - 1]?.type).toBe('message_end');
  });

  test('delta.content 为空字符串不发 token', async () => {
    const events = await run(
      clientWith([
        { choices: [{ delta: { content: '' }, finish_reason: null }] },
        { choices: [], usage: { prompt_tokens: 1, completion_tokens: 0 } },
      ]),
    );
    expect(events.filter((e) => e.type === 'token')).toHaveLength(0);
  });

  test('client 抛错 → error 事件', async () => {
    const failing: OpenAIChatClient = {
      async *stream() {
        throw new Error('timeout');
        yield;
      },
    };
    const events = await run(failing);
    const err = events.find((e) => e.type === 'error');
    expect(err).toBeDefined();
    if (err?.type === 'error') {
      expect(err.message).toContain('timeout');
    }
  });

  test('deps.openai 缺失 → 抛错', () => {
    expect(() => openaiChatAdapter(model(), {})).toThrow(/not provided/);
  });
});

describe('REQ-GRAPH-2 · openai-v1 工具调用闭环', () => {
  test('请求把工具 schema 注入 tools 参数', async () => {
    let capturedTools: readonly { function: { name: string } }[] | undefined;
    const client: OpenAIChatClient = {
      async *stream(params) {
        capturedTools = params.tools;
        yield { choices: [{ delta: { content: 'x' }, finish_reason: null }] };
      },
    };
    const brain = openaiChatAdapter(model(), { openai: client, tools: [fakeTool] });
    for await (const _ of brain([{ role: 'user', content: 'hi' }])) {
      void _;
    }
    expect(capturedTools?.[0]?.function.name).toBe('ls');
  });

  test('流式 tool_calls 分片 → 统一 tool_call 事件', async () => {
    const events = await run(
      clientWith([
        { choices: [{ delta: { tool_calls: [{ index: 0, id: 'c1', function: { name: 'ls' } }] }, finish_reason: null }] },
        { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '{"path":' } }] }, finish_reason: null }] },
        { choices: [{ delta: { tool_calls: [{ index: 0, function: { arguments: '"."}' } }] }, finish_reason: null }] },
        { choices: [{ delta: {}, finish_reason: 'tool_calls' }] },
      ]),
    );
    const call = events.find((e) => e.type === 'tool_call');
    expect(call).toBeDefined();
    if (call?.type === 'tool_call') {
      expect(call.tool).toBe('ls');
      expect(call.args).toEqual({ path: '.' });
      expect(call.callId).toBe('c1');
    }
  });
});

describe('REQ-PROV-1 · openai-v1 适配器已注册', () => {
  test('protocol=openai-v1 路由成功', () => {
    const brain = selectBrain(
      { models: [model()], active: 'gpt' },
      { openai: clientWith([{ choices: [{ delta: { content: 'x' }, finish_reason: null }] }]) },
    );
    expect(typeof brain).toBe('function');
  });
});
