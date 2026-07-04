/**
 * 输入框纯逻辑模型。
 *
 * 铁律遵守：
 * - 职责单一：本文件只做"计算"，不含任何渲染 / React / 终端副作用，可脱离终端单测。
 * - No AnyScript：全部显式类型，无 any。
 * - 供 DynamicInput 组件与单元测试共用，组件只负责渲染与事件分发。
 */

/** 动态高度的行数边界。 */
export const MIN_ROWS = 1;
export const MAX_ROWS = 5;

/**
 * 按换行符计算输入框应占的行数，钳制在 [min, max]。
 * @param value 当前输入文本
 */
export function computeRows(
  value: string,
  min: number = MIN_ROWS,
  max: number = MAX_ROWS,
): number {
  const lineCount = value.length === 0 ? 1 : value.split('\n').length;
  return Math.min(Math.max(lineCount, min), max);
}

/**
 * 取输入文本中"当前可见"的尾部若干行（超过 rows 时内部向上滚动）。
 * value 为空时返回单个空行，保证输入框始终有一行可渲染。
 */
export function visibleLines(value: string, rows: number): string[] {
  const lines = value.length === 0 ? [''] : value.split('\n');
  return lines.slice(Math.max(0, lines.length - rows));
}

/** 历史导航方向。 */
export type NavDirection = 'up' | 'down';

/** 文本末行的 0-based 行号。 */
export function lastLineIndex(text: string): number {
  return text.length === 0 ? 0 : text.split('\n').length - 1;
}

/**
 * 历史翻阅状态（见 specs/tui-history.spec.md）。
 * - browsing：是否处于翻阅态（初始 false，非翻阅时不显示 History 行）。
 * - index：翻阅时定位的历史条目（0-based，最旧→最新）。
 * - cursorLine：当前条目内光标所在行（支撑多行导航）。
 * - value：当前应显示于输入框的文本。
 * - draft：进入翻阅前保存的编辑草稿，退出翻阅时恢复。
 */
export interface HistoryState {
  readonly browsing: boolean;
  readonly index: number;
  readonly cursorLine: number;
  readonly value: string;
  readonly draft: string;
}

/** 非翻阅态的初始状态工厂。 */
export function idleHistoryState(value: string = ''): HistoryState {
  return { browsing: false, index: 0, cursorLine: 0, value, draft: '' };
}

/**
 * 上/下键的历史翻阅状态转换（纯函数）。
 * 完整规则见 specs/tui-history.spec.md（REQ-HIST-2..5）。
 *
 * @param history 历史输入（最旧 → 最新）
 * @param state 当前翻阅状态
 * @param direction 'up' / 'down'
 */
export function stepHistory(
  history: readonly string[],
  state: HistoryState,
  direction: NavDirection,
): HistoryState {
  const total = history.length;

  if (direction === 'up') {
    // 非翻阅 + ↑：进入翻阅，存草稿，载入最新一条，光标置末行。
    if (!state.browsing) {
      if (total === 0) {
        return state;
      }
      const index = total - 1;
      const value = history[index] ?? '';
      return {
        browsing: true,
        index,
        cursorLine: lastLineIndex(value),
        value,
        draft: state.value,
      };
    }
    // 翻阅 + 条目内非首行：光标上移。
    if (state.cursorLine > 0) {
      return { ...state, cursorLine: state.cursorLine - 1 };
    }
    // 翻阅 + 首行 + 有更旧：切上一条，光标置末行。
    if (state.index > 0) {
      const index = state.index - 1;
      const value = history[index] ?? '';
      return { ...state, index, value, cursorLine: lastLineIndex(value) };
    }
    // 翻阅 + 全局首行再↑：退出翻阅，恢复草稿。
    return { ...idleHistoryState(state.draft) };
  }

  // direction === 'down'
  // 非翻阅 + ↓：不动。
  if (!state.browsing) {
    return state;
  }
  const last = lastLineIndex(state.value);
  // 翻阅 + 条目内非末行：光标下移。
  if (state.cursorLine < last) {
    return { ...state, cursorLine: state.cursorLine + 1 };
  }
  // 翻阅 + 末行 + 有更新：切下一条，光标置首行。
  if (state.index < total - 1) {
    const index = state.index + 1;
    const value = history[index] ?? '';
    return { ...state, index, value, cursorLine: 0 };
  }
  // 翻阅 + 全局末行再↓：退出翻阅，恢复草稿。
  return { ...idleHistoryState(state.draft) };
}

/**
 * 生成"压在输入框顶边框上"的 History 分隔线。
 * 形如：`─ History 3/3 ─────────────…`（用 '─' 补足到 width）。
 *
 * @param pos 当前历史位置（1-based；无导航时等于 total）
 * @param total 历史总条数
 * @param width 目标总宽度（终端列数）
 */
export function buildHistoryBorder(
  pos: number,
  total: number,
  width: number,
): string {
  const label = `─ History ${pos}/${total} `;
  if (width <= label.length) {
    return label.slice(0, Math.max(0, width));
  }
  return label + '─'.repeat(width - label.length);
}

/** History 分隔线上显示的当前位置（1-based）。仅翻阅态调用，index 为 0-based 条目号。 */
export function historyPosition(index: number): number {
  return index + 1;
}
