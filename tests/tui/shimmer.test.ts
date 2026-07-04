/**
 * 单元测试 · shimmer 纯逻辑（确定性，脱终端）。
 * 覆盖 specs/tui-shimmer.spec.md：REQ-SHIM-1/2。
 */
import { test, expect, describe } from 'bun:test';
import {
  DEFAULT_PALETTE,
  SPINNER_CHARS,
  shimmerColors,
  spinnerFrame,
} from '../../src/platforms/tui/logic/shimmer.ts';

describe('shimmerColors · REQ-SHIM-1', () => {
  test('空串返回空数组', () => {
    expect(shimmerColors('', 0)).toEqual([]);
  });

  test('长度等于字符数', () => {
    expect(shimmerColors('hello', 0)).toHaveLength(5);
  });

  test('frame=0：首字符落在波峰起点（palette[0]）', () => {
    const colors = shimmerColors('abcdefghij', 0);
    expect(colors[0]).toBe(DEFAULT_PALETTE[0]);
    expect(colors[1]).toBe(DEFAULT_PALETTE[1]); // 光束第二格
  });

  test('光束随 frame 右移一格', () => {
    const f0 = shimmerColors('abcdefghij', 0);
    const f1 = shimmerColors('abcdefghij', 1);
    // frame=1 时，palette[0] 应从索引0移到索引1
    expect(f1[1]).toBe(f0[0]);
  });

  test('光束外的字符取 base（palette[0]）', () => {
    // 短文本会被撑到 MIN_CYCLE=30，波长9之外都是 base
    const colors = shimmerColors('abcdefghijklmnop', 0);
    // 索引 >= palette.length 的字符是 base 暗色
    expect(colors[12]).toBe(DEFAULT_PALETTE[0]);
  });

  test('中文按 code point 计数', () => {
    expect(shimmerColors('思考中', 0)).toHaveLength(3);
  });

  test('自定义 palette 生效', () => {
    const colors = shimmerColors('xy', 0, { palette: ['#111', '#999'], base: '#000' });
    expect(colors[0]).toBe('#111');
  });
});

describe('spinnerFrame · REQ-SHIM-2', () => {
  test('从 SPINNER_CHARS 取值', () => {
    expect(SPINNER_CHARS).toContain(spinnerFrame(0));
  });

  test('半速：frame/2 推进（frame 0,1 同字符，2 才切换）', () => {
    expect(spinnerFrame(0)).toBe(spinnerFrame(1));
    expect(spinnerFrame(2)).not.toBe(spinnerFrame(0));
  });

  test('循环回绕', () => {
    // 10 个字符 × 半速 = 20 帧一循环
    expect(spinnerFrame(0)).toBe(spinnerFrame(SPINNER_CHARS.length * 2));
  });

  test('负 frame 取模正确（不崩、落在字符集内）', () => {
    expect(SPINNER_CHARS).toContain(spinnerFrame(-3));
  });
});
