/**
 * 组件测试 · LogViewer。
 * 断言历史消息 → 视图文本的映射：用户/助手/系统消息都出现，
 * 正在流式的文本也出现。反白的 ANSI 效果由端到端冒烟验证
 * （ink-testing-library 的 lastFrame 已 strip 颜色）。
 */
import { test, expect, describe } from 'bun:test';
import React from 'react';
import { render } from 'ink-testing-library';
import { LogViewer } from '../../src/platforms/tui/components/LogViewer.tsx';
import type { ChatMessage } from '../../src/core/contract.ts';

describe('LogViewer', () => {
  test('渲染多角色消息', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '用户说的话' },
      { role: 'assistant', content: '助手的回复' },
      { role: 'system', content: '系统提示' },
    ];
    const { lastFrame } = render(
      React.createElement(LogViewer, { messages, streaming: '' }),
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('用户说的话');
    expect(frame).toContain('助手的回复');
    expect(frame).toContain('系统提示');
  });

  test('系统消息带告警前缀', () => {
    const { lastFrame } = render(
      React.createElement(LogViewer, {
        messages: [{ role: 'system', content: '警告内容' }],
        streaming: '',
      }),
    );
    expect(lastFrame()).toContain('⚠');
  });

  test('流式文本被渲染在末尾', () => {
    const { lastFrame } = render(
      React.createElement(LogViewer, {
        messages: [{ role: 'user', content: '问题' }],
        streaming: '正在生成的回复…',
      }),
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('问题');
    expect(frame).toContain('正在生成的回复…');
  });

  test('空历史 + 空流式不崩', () => {
    const { lastFrame } = render(
      React.createElement(LogViewer, { messages: [], streaming: '' }),
    );
    expect(typeof lastFrame()).toBe('string');
  });
});
