/**
 * 流光文字纯逻辑（算法本体，无 React / Ink，可脱终端单测）。
 *
 * 一条从暗→亮→暗的渐变「光束」在文字上逐字符、逐帧向右扫过，扫完留一段暗色
 * 间隔再来下一道。源自 pan-player-cmd 的 Go 版 renderShimmerText，拆为纯函数。
 *
 * 铁律遵守：职责单一（只算颜色/字符，不渲染、不计时）；No AnyScript。
 * 见 specs/tui-shimmer.spec.md（REQ-SHIM-1/2）。
 */

/** 默认蓝色系流光波（暗→亮→暗，波峰 #8CCBFF 居中最亮）。 */
export const DEFAULT_PALETTE: readonly string[] = [
  '#1E6FD9',
  '#2A86F0',
  '#45A3FF',
  '#66B8FF',
  '#8CCBFF',
  '#66B8FF',
  '#45A3FF',
  '#2A86F0',
  '#1E6FD9',
];

/** 波峰中间色，用于 spinner 前缀等强调场景。 */
export const SHIMMER_ACCENT = '#45A3FF';

/** 光束扫完后的最小循环周期，保证有暗色间隔。 */
export const MIN_CYCLE = 30;

/** spinner 盲文旋转字符。 */
export const SPINNER_CHARS: readonly string[] = [
  '⠋',
  '⠙',
  '⠹',
  '⠸',
  '⠼',
  '⠴',
  '⠦',
  '⠧',
  '⠇',
  '⠏',
];

/** shimmerColors 选项。 */
export interface ShimmerOptions {
  /** 光束渐变色（暗→亮→暗）；默认蓝色系。 */
  readonly palette?: readonly string[];
  /** 光束外字符的基础暗色；默认 palette 首元素。 */
  readonly base?: string;
}

/** 正取模：保证负数也落在 [0, m)。 */
function mod(n: number, m: number): number {
  return ((n % m) + m) % m;
}

/**
 * 计算每个字符当前帧应显示的颜色（REQ-SHIM-1）。
 * 返回长度 = 字符数（按 Unicode code point 切分，兼容中文/emoji）。
 *
 * @param text 目标文本
 * @param frame 动画帧（越大光束越靠右）
 */
export function shimmerColors(
  text: string,
  frame: number,
  options: ShimmerOptions = {},
): string[] {
  const chars = [...text];
  const n = chars.length;
  if (n === 0) {
    return [];
  }
  const palette = options.palette ?? DEFAULT_PALETTE;
  const base = options.base ?? palette[0] ?? '#1E6FD9';
  const cycleLen = Math.max(n + palette.length, MIN_CYCLE);

  return chars.map((_, i) => {
    const pos = mod(i - frame, cycleLen);
    return pos < palette.length ? (palette[pos] ?? base) : base;
  });
}

/**
 * 当前帧的 spinner 字符（REQ-SHIM-2）。转速为主流光一半（frame/2），负 frame 也正确。
 */
export function spinnerFrame(frame: number): string {
  const idx = mod(Math.floor(frame / 2), SPINNER_CHARS.length);
  return SPINNER_CHARS[idx] ?? SPINNER_CHARS[0] ?? '⠋';
}
