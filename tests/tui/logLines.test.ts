/**
 * 纯逻辑测试 · logLines（滚动区折行 + 尾部切片）。
 *
 * 修复背景：Ink 的 overflow=hidden 裁内容底部（显示头部），历史超一屏时最新
 * 消息被裁掉、滚动错乱。logLines 把消息流预折行成显示行，再截取尾部 N 行，
 * 保证渲染层每帧行数恒定且永远锚定最新内容。
 */
import { test, expect, describe } from 'bun:test';
import {
  buildDisplayLines,
  charWidth,
  tailSlice,
  toolEventText,
  wrapLine,
} from '../../src/platforms/tui/logic/logLines.ts';
import type { AgentEvent, ChatMessage } from '../../src/core/contract.ts';

describe('charWidth / wrapLine（CJK 宽度感知折行）', () => {
  test('ASCII 记 1 列，CJK 记 2 列', () => {
    expect(charWidth('a')).toBe(1);
    expect(charWidth('中')).toBe(2);
    expect(charWidth('，')).toBe(2);
  });

  test('纯 ASCII 按列数硬折', () => {
    expect(wrapLine('abcdefgh', 3)).toEqual(['abc', 'def', 'gh']);
  });

  test('CJK 按显示宽度折（4 列放 2 个汉字）', () => {
    expect(wrapLine('一二三四五', 4)).toEqual(['一二', '三四', '五']);
  });

  test('空行返回单个空串；columns<=0 不折', () => {
    expect(wrapLine('', 10)).toEqual(['']);
    expect(wrapLine('abc', 0)).toEqual(['abc']);
  });
});

describe('buildDisplayLines（消息流 → 显示行）', () => {
  const messages: ChatMessage[] = [
    { role: 'user', content: '问题' },
    { role: 'assistant', content: '回答' },
    { role: 'system', content: '警告' },
  ];

  test('各角色映射 kind，消息间插空行分隔；用户行补齐到整列用于整行反白', () => {
    const lines = buildDisplayLines(messages, '', 10);
    expect(lines.map((l) => l.kind)).toEqual([
      'user', 'blank', 'assistant', 'blank', 'system', 'blank',
    ]);
    expect(lines[0]?.text).toBe('问题    '); // CJK 占 4 列，补到 8 列；渲染层左右各留一格，合计贯通 10 列
    expect(lines[4]?.text).toContain('⚠');
  });

  test('流式文本追加在末尾', () => {
    const lines = buildDisplayLines(messages, '生成中', 80);
    expect(lines[lines.length - 1]).toEqual({ kind: 'assistant', text: '生成中' });
  });

  test('长助手消息按列宽折成多行', () => {
    const long: ChatMessage[] = [{ role: 'assistant', content: 'x'.repeat(25) }];
    const lines = buildDisplayLines(long, '', 10);
    const assistant = lines.filter((l) => l.kind === 'assistant');
    expect(assistant.length).toBe(3); // 25 / 10 → 3 行
    expect(assistant[0]?.text.length).toBe(10);
  });

  test('多行消息（含 \\n）逐行展开', () => {
    const multi: ChatMessage[] = [{ role: 'assistant', content: 'a\nb\nc' }];
    const lines = buildDisplayLines(multi, '', 80);
    expect(lines.filter((l) => l.kind === 'assistant').length).toBe(3);
  });

  test('工具事件气泡渲染在消息后、流式前', () => {
    const events: AgentEvent[] = [
      { type: 'tool_call', tool: 'read_file', args: { path: 'a.ts' }, callId: '1' },
      { type: 'tool_result', tool: 'read_file', callId: '1', ok: true, summary: '42 行' },
    ];
    const lines = buildDisplayLines(messages, '流式', 200, events);
    const toolLines = lines.filter((l) => l.kind === 'tool');
    expect(toolLines.length).toBe(2);
    expect(toolLines[0]?.text).toContain('read_file');
    expect(toolLines[1]?.text).toContain('42 行');
    // 时间序：tool 行在最后的流式行之前
    const lastToolIdx = lines.findLastIndex((l) => l.kind === 'tool');
    const streamIdx = lines.findIndex((l) => l.text === '流式');
    expect(lastToolIdx).toBeLessThan(streamIdx);
  });
});

describe('toolEventText（工具气泡文案）', () => {
  test('tool_call / tool_result / 其他事件', () => {
    expect(
      toolEventText({ type: 'tool_call', tool: 'bash', args: { cmd: 'ls' }, callId: '1' }),
    ).toContain('bash');
    expect(
      toolEventText({ type: 'tool_result', tool: 'bash', callId: '1', ok: false, summary: '失败' }),
    ).toContain('✗');
    expect(toolEventText({ type: 'token', text: 'x' })).toBeNull();
  });
});

describe('tailSlice（尾部锚定：超屏永远显示最新内容）', () => {
  test('内容不超预算时全量返回（剔除末尾空行）', () => {
    const messages: ChatMessage[] = [{ role: 'user', content: 'hi' }];
    const lines = buildDisplayLines(messages, '', 80);
    const tail = tailSlice(lines, 100);
    expect(tail.map((l) => l.text.trimEnd())).toEqual(['hi']); // 末尾 blank 被剔除，用户行保留整行反白 padding
  });

  test('超预算时截取尾部：旧消息被裁、最新消息在位', () => {
    const messages: ChatMessage[] = Array.from({ length: 30 }, (_, i) => ({
      role: 'assistant' as const,
      content: `msg-${i}`,
    }));
    const lines = buildDisplayLines(messages, '', 80);
    const tail = tailSlice(lines, 5);
    expect(tail.length).toBe(5);
    const texts = tail.map((l) => l.text);
    expect(texts).toContain('msg-29'); // 最新的在
    expect(texts).not.toContain('msg-0'); // 最旧的被裁
  });

  test('流式文本永远保留在尾部（滚动错乱回归）', () => {
    const messages: ChatMessage[] = Array.from({ length: 50 }, (_, i) => ({
      role: 'assistant' as const,
      content: `history-${i}`,
    }));
    const tail = tailSlice(buildDisplayLines(messages, 'streaming-now', 80), 10);
    expect(tail[tail.length - 1]?.text).toBe('streaming-now');
  });

  test('height<=0 返回空', () => {
    const lines = buildDisplayLines([{ role: 'user', content: 'x' }], '', 80);
    expect(tailSlice(lines, 0)).toEqual([]);
  });
});
