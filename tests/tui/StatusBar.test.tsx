/**
 * 组件测试 · StatusBar + Header。
 * 纯展示组件，断言状态文案与传入数据正确映射。
 */
import { test, expect, describe } from 'bun:test';
import React from 'react';
import { render } from 'ink-testing-library';
import { StatusBar } from '../../src/platforms/tui/components/StatusBar.tsx';
import { Header } from '../../src/platforms/tui/components/Header.tsx';

describe('StatusBar', () => {
  test('busy=false 显示 ready', () => {
    const { lastFrame } = render(
      React.createElement(StatusBar, { busy: false, inputTokens: 0, outputTokens: 0 }),
    );
    expect(lastFrame()).toContain('ready');
  });

  test('busy=true 显示 thinking', () => {
    const { lastFrame } = render(
      React.createElement(StatusBar, { busy: true, inputTokens: 0, outputTokens: 0 }),
    );
    expect(lastFrame()).toContain('thinking');
  });

  test('渲染 token 计数', () => {
    const { lastFrame } = render(
      React.createElement(StatusBar, { busy: false, inputTokens: 42, outputTokens: 128 }),
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('42');
    expect(frame).toContain('128');
  });
});

describe('Header', () => {
  test('渲染标题、副标题、cwd', () => {
    const { lastFrame } = render(
      React.createElement(Header, {
        title: 'ballad',
        subtitle: 'Phase 1',
        cwd: '/demo/path',
      }),
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('ballad');
    expect(frame).toContain('Phase 1');
    expect(frame).toContain('/demo/path');
  });
});
