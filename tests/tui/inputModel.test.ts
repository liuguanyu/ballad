/**
 * 单元测试 · inputModel 纯逻辑。
 *
 * 这是历史导航 / 动态高度 / 可见行的"确定性真相"层：
 * 不经过 Ink 的输入解析，所以连续导航、边界、多字节文本都能精确断言，
 * 修掉了"组件测试里连按上键读到陈旧 index"那类假象。
 */
import { test, expect, describe } from 'bun:test';
import {
  stepHistory,
  idleHistoryState,
  lastLineIndex,
  historyPosition,
  computeRows,
  visibleLines,
  buildHistoryBorder,
  MAX_ROWS,
  type HistoryState,
} from '../../src/platforms/tui/logic/inputModel.ts';

describe('lastLineIndex', () => {
  test('空 / 单行 = 0', () => {
    expect(lastLineIndex('')).toBe(0);
    expect(lastLineIndex('one line')).toBe(0);
  });
  test('多行 = 行数-1', () => {
    expect(lastLineIndex('a\nb\nc')).toBe(2);
  });
});

describe('stepHistory', () => {
  const history = ['first', 'l1\nl2\nl3', 'third']; // 中间一条为 3 行

  test('非翻阅 ↑ → 进入翻阅、存草稿、载入最新、光标末行', () => {
    const s = idleHistoryState('草稿');
    const r = stepHistory(history, s, 'up');
    expect(r.browsing).toBe(true);
    expect(r.index).toBe(2);
    expect(r.value).toBe('third');
    expect(r.cursorLine).toBe(0); // 'third' 单行，末行=0
    expect(r.draft).toBe('草稿');
  });

  test('非翻阅 ↓ → 不动', () => {
    const s = idleHistoryState('x');
    expect(stepHistory(history, s, 'down')).toEqual(s);
  });

  test('空历史 ↑ → 不动', () => {
    const s = idleHistoryState('x');
    expect(stepHistory([], s, 'up')).toEqual(s);
  });

  test('多行条目内 ↑ 逐行移光标（index 不变）', () => {
    // 先进入翻阅并切到 3 行条目：从末行开始
    const enter = stepHistory(history, idleHistoryState(''), 'up'); // → third
    const toMid = stepHistory(history, enter, 'up'); // 首行再↑ → 切到中间条目(index1)末行
    expect(toMid.index).toBe(1);
    expect(toMid.value).toBe('l1\nl2\nl3');
    expect(toMid.cursorLine).toBe(2); // 末行
    const up1 = stepHistory(history, toMid, 'up');
    expect(up1.index).toBe(1);
    expect(up1.cursorLine).toBe(1); // 条目内上移
  });

  test('多行条目内 ↓ 逐行移光标', () => {
    const s: HistoryState = {
      browsing: true,
      index: 1,
      cursorLine: 0,
      value: 'l1\nl2\nl3',
      draft: 'd',
    };
    const down1 = stepHistory(history, s, 'down');
    expect(down1.index).toBe(1);
    expect(down1.cursorLine).toBe(1);
  });

  test('末行 ↓ 切下一条、光标置首行', () => {
    const s: HistoryState = {
      browsing: true,
      index: 1,
      cursorLine: 2, // 末行
      value: 'l1\nl2\nl3',
      draft: 'd',
    };
    const r = stepHistory(history, s, 'down');
    expect(r.index).toBe(2);
    expect(r.value).toBe('third');
    expect(r.cursorLine).toBe(0);
  });

  test('全局首行再 ↑ → 退出翻阅、恢复草稿', () => {
    const s: HistoryState = {
      browsing: true,
      index: 0,
      cursorLine: 0,
      value: 'first',
      draft: '我的草稿',
    };
    const r = stepHistory(history, s, 'up');
    expect(r.browsing).toBe(false);
    expect(r.value).toBe('我的草稿');
  });

  test('全局末行再 ↓ → 退出翻阅、恢复草稿', () => {
    const s: HistoryState = {
      browsing: true,
      index: 2,
      cursorLine: 0, // 'third' 末行=0
      value: 'third',
      draft: '我的草稿',
    };
    const r = stepHistory(history, s, 'down');
    expect(r.browsing).toBe(false);
    expect(r.value).toBe('我的草稿');
  });
});

describe('historyPosition', () => {
  test('翻阅态位置为 index+1（1-based）', () => {
    expect(historyPosition(0)).toBe(1);
    expect(historyPosition(2)).toBe(3);
  });
});

describe('computeRows', () => {
  test('空 / 单行 = 1 行', () => {
    expect(computeRows('')).toBe(1);
    expect(computeRows('one line')).toBe(1);
  });
  test('按换行数增长', () => {
    expect(computeRows('a\nb')).toBe(2);
    expect(computeRows('a\nb\nc')).toBe(3);
  });
  test('封顶 MAX_ROWS', () => {
    expect(computeRows('a\nb\nc\nd\ne\nf\ng')).toBe(MAX_ROWS);
  });
});

describe('visibleLines', () => {
  test('空文本给一个空行', () => {
    expect(visibleLines('', 1)).toEqual(['']);
  });
  test('不超行数时全显示', () => {
    expect(visibleLines('a\nb', 5)).toEqual(['a', 'b']);
  });
  test('超行数只保留尾部（内部滚动）', () => {
    expect(visibleLines('a\nb\nc\nd\ne\nf', 5)).toEqual(['b', 'c', 'd', 'e', 'f']);
  });
});

describe('buildHistoryBorder', () => {
  test('含 History n/n 且补足到指定宽度', () => {
    const line = buildHistoryBorder(3, 3, 40);
    expect(line).toContain('History 3/3');
    expect(line.length).toBe(40);
  });
  test('宽度过窄时截断不越界', () => {
    const line = buildHistoryBorder(1, 1, 5);
    expect(line.length).toBeLessThanOrEqual(5);
  });
});
