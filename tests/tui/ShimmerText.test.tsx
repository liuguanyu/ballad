/**
 * 组件测试 · ShimmerText（渲染组装）。
 * 算法正确性由 shimmer.test.ts 覆盖；这里只验渲染结构。
 * 用 active={false} 定格，规避定时器的时间不确定性。
 */
import { test, expect, describe } from 'bun:test';
import React from 'react';
import { render } from 'ink-testing-library';
import { ShimmerText } from '../../src/platforms/tui/components/ShimmerText.tsx';
import { SPINNER_CHARS } from '../../src/platforms/tui/logic/shimmer.ts';

describe('ShimmerText 渲染', () => {
  test('渲染出全部字符', () => {
    const frame = render(
      React.createElement(ShimmerText, { text: 'Thinking', active: false }),
    ).lastFrame() ?? '';
    expect(frame).toContain('Thinking');
  });

  test('spinner=true 时前置一个旋转字符', () => {
    const frame = render(
      React.createElement(ShimmerText, { text: 'Thinking', spinner: true, active: false }),
    ).lastFrame() ?? '';
    const hasSpinner = SPINNER_CHARS.some((c) => frame.includes(c));
    expect(hasSpinner).toBe(true);
    expect(frame).toContain('Thinking');
  });

  test('spinner=false（默认）无旋转字符', () => {
    const frame = render(
      React.createElement(ShimmerText, { text: 'abc', active: false }),
    ).lastFrame() ?? '';
    const hasSpinner = SPINNER_CHARS.some((c) => frame.includes(c));
    expect(hasSpinner).toBe(false);
  });

  test('空 text 不崩', () => {
    const frame = render(
      React.createElement(ShimmerText, { text: '', active: false }),
    ).lastFrame();
    expect(frame).toBeDefined();
  });

  test('中文文本渲染', () => {
    const frame = render(
      React.createElement(ShimmerText, { text: '思考中', active: false }),
    ).lastFrame() ?? '';
    expect(frame).toContain('思考中');
  });
});
