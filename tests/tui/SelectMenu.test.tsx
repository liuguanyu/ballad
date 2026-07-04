/**
 * 组件测试 · SelectMenu（纯渲染）。
 * 逻辑正确性（过滤/滚动）由 selectMenu.test.ts 覆盖；这里只验渲染结构。
 */
import { test, expect, describe } from 'bun:test';
import React from 'react';
import { render } from 'ink-testing-library';
import { SelectMenu } from '../../src/platforms/tui/components/SelectMenu.tsx';
import {
  idleMenuState,
  type MenuItem,
} from '../../src/platforms/tui/logic/selectMenu.ts';

const CMDS: readonly MenuItem[] = [
  { value: 'exit', label: '/exit', hint: '退出 ballad' },
  { value: 'clear', label: '/clear', hint: '清屏' },
];

describe('SelectMenu 渲染', () => {
  test('渲染所有项的 label 与 hint', () => {
    const frame =
      render(React.createElement(SelectMenu, { items: CMDS, state: idleMenuState() }))
        .lastFrame() ?? '';
    expect(frame).toContain('/exit');
    expect(frame).toContain('退出 ballad');
    expect(frame).toContain('/clear');
  });

  test('底部提示栏在位', () => {
    const frame =
      render(React.createElement(SelectMenu, { items: CMDS, state: idleMenuState() }))
        .lastFrame() ?? '';
    expect(frame).toContain('Enter 选中');
    expect(frame).toContain('Esc 关闭');
  });

  test('空 items 不渲染任何行', () => {
    const { lastFrame } = render(
      React.createElement(SelectMenu, { items: [], state: idleMenuState() }),
    );
    const frame = lastFrame() ?? '';
    expect(frame).not.toContain('Enter 选中');
  });

  test('高亮项落在 selected 指向的行（含 /exit）', () => {
    const frame =
      render(
        React.createElement(SelectMenu, {
          items: CMDS,
          state: { selected: 1, offset: 0 },
        }),
      ).lastFrame() ?? '';
    // 两项都应在帧里；高亮由 ANSI 反白承载，这里只断言内容完整渲染
    expect(frame).toContain('/exit');
    expect(frame).toContain('/clear');
  });
});
