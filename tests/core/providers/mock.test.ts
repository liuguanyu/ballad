/**
 * mock 适配器测试（Phase 2a）。
 *
 * 覆盖 spec REQ-PROV-3（mock 适配器把请求收敛为 AgentEvent）。
 * 委托 createMockBrain，应吐出 message_start / thinking / token / message_end 完整序列。
 */
import { test, expect, describe } from 'bun:test';
import { mockAdapter } from '../../../src/core/providers/mock.ts';
import type { ModelConfig } from '../../../src/core/provider.ts';
import type { AgentEvent } from '../../../src/core/contract.ts';

function model(): ModelConfig {
  return { name: 'mock', protocol: 'mock', model: 'mock' };
}

async function run(): Promise<AgentEvent[]> {
  const brain = mockAdapter(model(), {});
  const events: AgentEvent[] = [];
  for await (const ev of brain([{ role: 'user', content: 'hello' }])) {
    events.push(ev);
  }
  return events;
}

describe('REQ-PROV-3 · mock 适配器事件序列', () => {
  test('以 message_start 开头', async () => {
    const events = await run();
    expect(events[0]?.type).toBe('message_start');
  });

  test('含 thinking 事件', async () => {
    const events = await run();
    expect(events.some((e) => e.type === 'thinking')).toBe(true);
  });

  test('含 token 事件且拼接出正文', async () => {
    const events = await run();
    const text = events
      .filter((e) => e.type === 'token')
      .map((e) => (e.type === 'token' ? e.text : ''))
      .join('');
    expect(text.length).toBeGreaterThan(0);
  });

  test('以 message_end 结尾且含 usage', async () => {
    const events = await run();
    const last = events[events.length - 1];
    expect(last?.type).toBe('message_end');
    if (last?.type === 'message_end') {
      expect(last.usage).toBeDefined();
      expect(last.usage?.inputTokens).toBeGreaterThanOrEqual(0);
      expect(last.usage?.outputTokens).toBeGreaterThanOrEqual(0);
    }
  });
});
