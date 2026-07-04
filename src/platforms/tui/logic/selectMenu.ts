/**
 * 上拉选择框纯逻辑（泛型，可复用核心）。
 *
 * 铁律遵守：
 * - 职责单一：只做"计算"，不含 React / Ink / 终端副作用，可脱终端单测。
 * - No AnyScript：全部显式类型，无 any。
 * - 供 SelectMenu 组件与 App 编排层共用；slash command / MCP list 等复用同一套。
 *
 * 交互模型（见 specs/tui-slash-commands.spec.md）：呼出 → 前缀过滤 →
 * ↑/↓ 移动高亮（最多 MENU_WINDOW 行可见，超出滚动）→ Enter 选中 / Esc 关闭。
 */

/** 可见窗口最多行数（与 cc / reasonix 一致）。 */
export const MENU_WINDOW = 8;

/** 菜单项的最小形状：谁想复用上拉框，item 满足此形状即可。 */
export interface MenuItem {
  /** 选中时回传的稳定标识（如 'exit'）。 */
  readonly value: string;
  /** 主文本（如 '/exit'）。 */
  readonly label: string;
  /** 右侧说明（如 '退出 ballad'）。 */
  readonly hint?: string;
}

/**
 * 菜单滚动/高亮状态。
 * - selected：过滤后列表中的高亮下标（0-based）。
 * - offset：MENU_WINDOW 可见窗口的起始下标（滚动锚点）。
 */
export interface MenuState {
  readonly selected: number;
  readonly offset: number;
}

/** 高亮移动方向。 */
export type MenuDirection = 'up' | 'down';

/** 呼出/重置时的初始状态：高亮首项、窗口顶对齐。 */
export function idleMenuState(): MenuState {
  return { selected: 0, offset: 0 };
}

/**
 * 按查询前缀过滤菜单项（泛型：保留调用方的具体 item 类型）。
 * 规则：去掉查询前导 '/'，对 item.value 与 item.label（其自身去 '/'）做前缀匹配，
 * 大小写不敏感。空查询（或仅 '/'）返回全部。
 *
 * @param items 全量候选
 * @param query 当前输入文本（可能以 '/' 开头）
 */
export function filterItems<T extends MenuItem>(
  items: readonly T[],
  query: string,
): T[] {
  const needle = query.replace(/^\//, '').toLowerCase();
  if (needle.length === 0) {
    return [...items];
  }
  return items.filter((item) => {
    const byValue = item.value.toLowerCase().startsWith(needle);
    const byLabel = item.label.replace(/^\//, '').toLowerCase().startsWith(needle);
    return byValue || byLabel;
  });
}

/**
 * ↑/↓ 移动高亮：selected 在 [0, total-1] 钳制（不回绕），
 * 并调整 offset 使 selected 始终落在 MENU_WINDOW 窗口内。
 *
 * @param state 当前状态
 * @param dir 方向
 * @param total 过滤后列表长度
 */
export function moveSelection(
  state: MenuState,
  dir: MenuDirection,
  total: number,
): MenuState {
  if (total <= 0) {
    return idleMenuState();
  }
  const delta = dir === 'up' ? -1 : 1;
  const selected = Math.min(Math.max(state.selected + delta, 0), total - 1);
  let offset = state.offset;
  if (selected < offset) {
    offset = selected;
  } else if (selected >= offset + MENU_WINDOW) {
    offset = selected - MENU_WINDOW + 1;
  }
  return { selected, offset };
}

/** visibleWindow 返回的单行：项 + 是否高亮。 */
export interface MenuRow<T extends MenuItem> {
  readonly item: T;
  readonly active: boolean;
}

/**
 * 取当前窗口可见的项切片（最多 MENU_WINDOW 行），并标记每项是否为高亮项。
 * 组件只渲染本函数的返回，无需自己算滚动。
 */
export function visibleWindow<T extends MenuItem>(
  items: readonly T[],
  state: MenuState,
): MenuRow<T>[] {
  const start = Math.max(0, Math.min(state.offset, Math.max(0, items.length - 1)));
  const slice = items.slice(start, start + MENU_WINDOW);
  return slice.map((item, i) => ({ item, active: start + i === state.selected }));
}
