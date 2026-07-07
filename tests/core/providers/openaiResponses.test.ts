/**
 * openai-v2 适配器测试（Phase 2a）。
 *
 * 覆盖 spec REQ-PROV-3：/v1/responses 事件流映射为 AgentEvent。
 * 注入 mock client 吐固定 v2 事件序列，断言映射（含 reasoning→thinking / usage / error）。零网络。
 */
import { test, expect, describe } from 'bun:test';
import {
  openaiResponsesAdapter,
  type OpenAIResponsesClient,
} from '../../../src/core/providers/openaiResponses.ts';
import { selectBrain, type ModelConfig } from '../../../src/core/provider.ts';
import type { AgentEvent } from '../../../src/core/contract.ts';

function model(): ModelConfig {
  return { name: 'gpt-responses', protocol: 'openai-v2', model: 'gpt-4o' };
}

function clientWith(events: unknown[]): OpenAIResponsesClient {
  return {
    async *stream() {
      for (const e of events) {
        yield e;
      }
    },
  };
}

async function run(client: OpenAIResponsesClient): Promise<AgentEvent[]> {
  const brain = openaiResponsesAdapter(model(), { openai: client });
  const out: AgentEvent[] = [];
  for await (const ev of brain([{ role: 'user', content: 'hi' }])) {
    out.push(ev);
  }
  return out;
}

describe('REQ-PROV-3 · openai-v2 流式映射', () => {
  test('response.created → message_start', async () => {
    const events = await run(
      clientWith([
        { type: 'response.created' },
        { type: 'response.completed', response: { usage: { input_tokens: 1, output_tokens: 0 } } },
      ]),
    );
    expect(events[0]?.type).toBe('message_start');
  });

  test('response.output_text.delta → token，拼接正文', async () => {
    const events = await run(
      clientWith([
        { type: 'response.created' },
        { type: 'response.output_text.delta', delta: 'Hel' },
        { type: 'response.output_text.delta', delta: 'lo' },
        { type: 'response.completed', response: { usage: { input_tokens: 2, output_tokens: 2 } } },
      ]),
    );
    const text = events
      .filter((e) => e.type === 'token')
      .map((e) => (e.type === 'token' ? e.text : ''))
      .join('');
    expect(text).toBe('Hello');
  });

  test('response.reasoning_text.delta → thinking', async () => {
    const events = await run(
      clientWith([
        { type: 'response.created' },
        { type: 'response.reasoning_text.delta', delta: 'thinking...' },
        { type: 'response.output_text.delta', delta: 'ok' },
        { type: 'response.completed', response: { usage: { input_tokens: 1, output_tokens: 1 } } },
      ]),
    );
    expect(events.some((e) => e.type === 'thinking')).toBe(true);
  });

  test('response.completed.response.usage → message_end.usage', async () => {
    const events = await run(
      clientWith([
        { type: 'response.created' },
        { type: 'response.completed', response: { usage: { input_tokens: 7, output_tokens: 9 } } },
      ]),
    );
    const end = events.find((e) => e.type === 'message_end');
    expect(end).toBeDefined();
    if (end?.type === 'message_end') {
      expect(end.usage?.inputTokens).toBe(7);
      expect(end.usage?.outputTokens).toBe(9);
    }
  });

  test('无 completed 事件时流末补 message_end', async () => {
    const events = await run(
      clientWith([{ type: 'response.created' }, { type: 'response.output_text.delta', delta: 'x' }]),
    );
    expect(events[events.length - 1]?.type).toBe('message_end');
  });

  test('client 抛错 → error 事件', async () => {
    const failing: OpenAIResponsesClient = {
      async *stream() {
        throw new Error('v2 down');
        yield;
      },
    };
    const events = await run(failing);
    const err = events.find((e) => e.type === 'error');
    expect(err).toBeDefined();
    if (err?.type === 'error') {
      expect(err.message).toContain('v2 down');
    }
  });

  test('deps.openai 缺失 → 抛错', () => {
    expect(() => openaiResponsesAdapter(model(), {})).toThrow(/not provided/);
  });

  test('无 user 消息时 input 为空字符串，仍能调用', async () => {
    const brain = openaiResponsesAdapter(model(), {
      openai: clientWith([{ type: 'response.created' }, { type: 'response.completed', response: {} }]),
    });
    const out: AgentEvent[] = [];
    for await (const ev of brain([{ role: 'assistant', content: 'prev' }])) {
      out.push(ev);
    }
    expect(out[0]?.type).toBe('message_start');
  });
});

describe('REQ-PROV-1 · openai-v2 适配器已注册', () => {
  test('protocol=openai-v2 路由成功', () => {
    const brain = selectBrain(
      { models: [model()], active: 'gpt-responses' },
      { openai: clientWith([{ type: 'response.created' }, { type: 'response.completed', response: {} }]) },
    );
    expect(typeof brain).toBe('function');
  });
});
