/**
 * 单元测试 · 大脑主体。
 * 大脑对外承诺：产出一段以 message_start 开头、message_end 结尾、
 * 中间为逐字 token 的合法事件流，且每个事件都符合契约。
 * 表现层依赖这个承诺，所以它必须被测试钉死。
 */
import { test, expect, describe } from 'bun:test';
import { createMockBrain } from '../../src/core/agent.ts';
import { AgentEventSchema } from '../../src/core/contract.ts';
import type { AgentEvent, ChatMessage } from '../../src/core/contract.ts';

async function drain(
  gen: AsyncGenerator<AgentEvent, void, void>,
): Promise<AgentEvent[]> {
  const out: AgentEvent[] = [];
  for await (const ev of gen) {
    out.push(ev);
  }
  return out;
}

describe('createMockBrain', () => {
  const brain = createMockBrain(0);

  test('每个事件都符合契约', async () => {
    const events = await drain(brain([{ role: 'user', content: '搭骨架' }]));
    for (const ev of events) {
      expect(() => AgentEventSchema.parse(ev)).not.toThrow();
    }
  });

  test('以 message_start 开头、message_end 结尾', async () => {
    const events = await drain(brain([{ role: 'user', content: 'hi' }]));
    expect(events[0]?.type).toBe('message_start');
    expect(events.at(-1)?.type).toBe('message_end');
  });

  test('中间是逐字 token，拼接还原完整回复', async () => {
    const events = await drain(brain([{ role: 'user', content: '你好' }]));
    const tokens = events.filter((e) => e.type === 'token');
    expect(tokens.length).toBeGreaterThan(0);
    const text = tokens.map((e) => (e.type === 'token' ? e.text : '')).join('');
    expect(text).toContain('你好'); // 回复里回显了用户输入
  });

  test('思考态：message_start 后、首个 token 前吐出 thinking', async () => {
    const events = await drain(brain([{ role: 'user', content: 'hi' }]));
    const thinkIdx = events.findIndex((e) => e.type === 'thinking');
    const firstToken = events.findIndex((e) => e.type === 'token');
    expect(thinkIdx).toBeGreaterThan(0); // 在 message_start 之后
    expect(thinkIdx).toBeLessThan(firstToken); // 在首个 token 之前
    const think = events[thinkIdx];
    if (think?.type === 'thinking') {
      expect(think.label).toBeDefined();
    }
  });

  test('用户输入不同，回复不同（真的读了 history）', async () => {
    const a = await drain(brain([{ role: 'user', content: 'AAA' }]));
    const b = await drain(brain([{ role: 'user', content: 'BBB' }]));
    const textA = a.filter((e) => e.type === 'token').map((e) => (e.type === 'token' ? e.text : '')).join('');
    const textB = b.filter((e) => e.type === 'token').map((e) => (e.type === 'token' ? e.text : '')).join('');
    expect(textA).toContain('AAA');
    expect(textB).toContain('BBB');
    expect(textA).not.toBe(textB);
  });

  test('空历史给出引导语', async () => {
    const events = await drain(brain([]));
    const text = events.filter((e) => e.type === 'token').map((e) => (e.type === 'token' ? e.text : '')).join('');
    expect(text).toContain('ballad');
  });

  test('message_end 携带非负 usage', async () => {
    const events = await drain(brain([{ role: 'user', content: 'hello' }]));
    const end = events.at(-1);
    expect(end?.type).toBe('message_end');
    if (end?.type === 'message_end') {
      expect(end.usage?.inputTokens).toBeGreaterThanOrEqual(0);
      expect(end.usage?.outputTokens).toBeGreaterThan(0);
    }
  });

  test('是可多次调用的工厂（每次返回独立生成器）', async () => {
    const history: ChatMessage[] = [{ role: 'user', content: 'x' }];
    const first = await drain(brain(history));
    const second = await drain(brain(history));
    expect(first.length).toBe(second.length);
  });
});
