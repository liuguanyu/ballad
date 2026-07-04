/**
 * 单元测试 · 契约层。
 * 契约是脑口通信的唯一媒介，它的校验能力必须被钉死：
 * 合法事件通过、非法事件被拒、类型判别正确。
 */
import { test, expect, describe } from 'bun:test';
import {
  AgentEventSchema,
  ChatMessageSchema,
  RoleSchema,
} from '../../src/core/contract.ts';

describe('RoleSchema', () => {
  test('接受合法角色', () => {
    expect(RoleSchema.parse('user')).toBe('user');
    expect(RoleSchema.parse('assistant')).toBe('assistant');
    expect(RoleSchema.parse('system')).toBe('system');
  });

  test('拒绝未知角色', () => {
    expect(() => RoleSchema.parse('robot')).toThrow();
  });
});

describe('AgentEventSchema', () => {
  test('message_start 合法', () => {
    const ev = AgentEventSchema.parse({ type: 'message_start', role: 'assistant' });
    expect(ev.type).toBe('message_start');
  });

  test('token 事件携带文本', () => {
    const ev = AgentEventSchema.parse({ type: 'token', text: '你' });
    expect(ev).toEqual({ type: 'token', text: '你' });
  });

  test('thinking 事件合法，label 可选', () => {
    expect(AgentEventSchema.parse({ type: 'thinking' }).type).toBe('thinking');
    const ev = AgentEventSchema.parse({ type: 'thinking', label: '正在推理' });
    expect(ev).toEqual({ type: 'thinking', label: '正在推理' });
  });

  test('message_end 的 usage 可选，且被校验为非负整数', () => {
    expect(() => AgentEventSchema.parse({ type: 'message_end' })).not.toThrow();
    expect(() =>
      AgentEventSchema.parse({
        type: 'message_end',
        usage: { inputTokens: 10, outputTokens: 20 },
      }),
    ).not.toThrow();
    // 负数应被拒
    expect(() =>
      AgentEventSchema.parse({
        type: 'message_end',
        usage: { inputTokens: -1, outputTokens: 0 },
      }),
    ).toThrow();
  });

  test('error 事件携带 message', () => {
    const ev = AgentEventSchema.parse({ type: 'error', message: '解析失败' });
    if (ev.type === 'error') {
      expect(ev.message).toBe('解析失败');
    }
  });

  test('判别联合：未知 type 被拒', () => {
    expect(() => AgentEventSchema.parse({ type: 'boom' })).toThrow();
  });

  test('token 事件缺 text 被拒', () => {
    expect(() => AgentEventSchema.parse({ type: 'token' })).toThrow();
  });
});

describe('ChatMessageSchema', () => {
  test('合法消息通过', () => {
    const m = ChatMessageSchema.parse({ role: 'user', content: 'hi' });
    expect(m).toEqual({ role: 'user', content: 'hi' });
  });

  test('缺字段被拒', () => {
    expect(() => ChatMessageSchema.parse({ role: 'user' })).toThrow();
  });
});
