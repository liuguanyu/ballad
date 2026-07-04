/**
 * 单元测试 · selectMenu 纯逻辑（确定性，脱终端）。
 *
 * 覆盖 specs/tui-slash-commands.spec.md：
 * - REQ-CMD-2 前缀过滤（filterItems）
 * - REQ-CMD-3 高亮移动钳制 + 8 行窗口滚动（moveSelection / visibleWindow）
 */
import { test, expect, describe } from 'bun:test';
import {
  MENU_WINDOW,
  filterItems,
  idleMenuState,
  moveSelection,
  visibleWindow,
  type MenuItem,
} from '../../src/platforms/tui/logic/selectMenu.ts';

const CMDS: readonly MenuItem[] = [
  { value: 'exit', label: '/exit', hint: '退出 ballad' },
  { value: 'clear', label: '/clear', hint: '清屏' },
  { value: 'export', label: '/export', hint: '导出' },
];

describe('idleMenuState', () => {
  test('初始高亮首项、窗口顶对齐', () => {
    expect(idleMenuState()).toEqual({ selected: 0, offset: 0 });
  });
});

describe('filterItems · REQ-CMD-2 前缀过滤', () => {
  test("'/' 或空查询返回全部", () => {
    expect(filterItems(CMDS, '/')).toHaveLength(3);
    expect(filterItems(CMDS, '')).toHaveLength(3);
  });

  test("'/ex' 前缀匹配 exit 与 export", () => {
    const r = filterItems(CMDS, '/ex').map((i) => i.value);
    expect(r).toEqual(['exit', 'export']);
  });

  test("'/exi' 收窄到单条 exit", () => {
    expect(filterItems(CMDS, '/exi').map((i) => i.value)).toEqual(['exit']);
  });

  test("无匹配返回空", () => {
    expect(filterItems(CMDS, '/zz')).toEqual([]);
  });

  test('大小写不敏感', () => {
    expect(filterItems(CMDS, '/EX').map((i) => i.value)).toEqual(['exit', 'export']);
  });

  test('无前导斜杠也能匹配（复用方可不带 /）', () => {
    expect(filterItems(CMDS, 'cl').map((i) => i.value)).toEqual(['clear']);
  });
});

describe('moveSelection · REQ-CMD-3 钳制', () => {
  test('down 递增、上边界不越 0、下边界不越 total-1', () => {
    let s = idleMenuState();
    s = moveSelection(s, 'down', 3);
    expect(s.selected).toBe(1);
    s = moveSelection(s, 'down', 3);
    s = moveSelection(s, 'down', 3); // 已到底，钳制
    expect(s.selected).toBe(2);
  });

  test('up 在 0 处钳制不回绕', () => {
    const s = moveSelection(idleMenuState(), 'up', 3);
    expect(s.selected).toBe(0);
  });

  test('total<=0 回到 idle', () => {
    expect(moveSelection({ selected: 5, offset: 3 }, 'down', 0)).toEqual(idleMenuState());
  });
});

describe('moveSelection / visibleWindow · REQ-CMD-3 窗口滚动', () => {
  // 构造 12 项（>8），验证滚动
  const many: MenuItem[] = Array.from({ length: 12 }, (_, i) => ({
    value: `c${i}`,
    label: `/c${i}`,
  }));

  test('向下越过窗口下沿时 offset 跟随', () => {
    let s = idleMenuState();
    for (let i = 0; i < MENU_WINDOW; i++) {
      s = moveSelection(s, 'down', many.length); // selected 0→8
    }
    expect(s.selected).toBe(MENU_WINDOW); // 8
    expect(s.offset).toBe(1); // 窗口下移一格：selected - WINDOW + 1
  });

  test('visibleWindow 最多返回 8 行且高亮正确', () => {
    const s = { selected: 8, offset: 1 };
    const rows = visibleWindow(many, s);
    expect(rows).toHaveLength(MENU_WINDOW);
    expect(rows[0]?.item.value).toBe('c1'); // 从 offset=1 起
    const active = rows.find((r) => r.active);
    expect(active?.item.value).toBe('c8'); // selected=8 高亮
  });

  test('向上回滚时 offset 跟随到 selected', () => {
    let s = { selected: 8, offset: 1 };
    // 一路上移到 0
    for (let i = 0; i < 8; i++) {
      s = moveSelection(s, 'up', many.length);
    }
    expect(s.selected).toBe(0);
    expect(s.offset).toBe(0);
  });

  test('少于窗口时全部可见、无越界', () => {
    const rows = visibleWindow(CMDS, idleMenuState());
    expect(rows).toHaveLength(3);
    expect(rows[0]?.active).toBe(true);
  });
});
