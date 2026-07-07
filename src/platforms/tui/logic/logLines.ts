/**
 * 滚动日志区纯逻辑：消息流 → 终端显示行 → 尾部切片。
 *
 * 为什么需要它：Ink/Yoga 的 overflow=hidden 裁剪的是内容"底部"（显示头部），
 * 历史超过一屏时最新消息会被裁掉，且超高帧与终端滚动叠加导致新旧行交错错乱。
 * 因此由本模块把消息流展平成逐行文本（按终端列宽预折行），再按可用高度取
 * 尾部切片——渲染层每帧输出的行数恒定且永远锚定最新内容。
 *
 * 铁律遵守：
 * - 职责单一：只做"计算"，不含 React / Ink / 终端副作用，可脱终端单测。
 * - No AnyScript：全部显式类型。
 */
import type { AgentEvent, ChatMessage } from '../../../core/contract.ts';

/** 显示行的语义类别，渲染层据此决定样式（反白 / 告警色 / 工具气泡 / 常规）。 */
export type LineKind = 'user' | 'assistant' | 'system' | 'tool' | 'blank';

/** 一条预折行后的终端显示行。 */
export interface DisplayLine {
  readonly kind: LineKind;
  readonly text: string;
}

/**
 * 东亚全角字符占 2 列的启发式判定（覆盖 CJK 统一表意、谚文、全角标点等主要区段）。
 * 不追求 Unicode 完备（那是 string-width 的事），对中文对话场景足够精确。
 */
function isWideCodePoint(cp: number): boolean {
  return (
    (cp >= 0x1100 && cp <= 0x115f) || // 谚文字母
    (cp >= 0x2e80 && cp <= 0xa4cf) || // CJK 部首/符号/统一表意/注音等
    (cp >= 0xac00 && cp <= 0xd7a3) || // 谚文音节
    (cp >= 0xf900 && cp <= 0xfaff) || // CJK 兼容表意
    (cp >= 0xfe30 && cp <= 0xfe4f) || // CJK 兼容形式
    (cp >= 0xff00 && cp <= 0xff60) || // 全角 ASCII / 标点
    (cp >= 0xffe0 && cp <= 0xffe6) || // 全角符号
    (cp >= 0x20000 && cp <= 0x3fffd) // CJK 扩展 B+
  );
}

/** 单字符显示宽度（1 或 2 列）。 */
export function charWidth(ch: string): 1 | 2 {
  return isWideCodePoint(ch.codePointAt(0) ?? 0) ? 2 : 1;
}

function textWidth(text: string): number {
  return [...text].reduce((sum, ch) => sum + charWidth(ch), 0);
}

function padDisplayEnd(text: string, columns: number): string {
  return text + ' '.repeat(Math.max(0, columns - textWidth(text)));
}

/**
 * 按显示宽度把单行文本硬折行到 columns 列以内（CJK 记 2 列）。
 * columns <= 0 时不折（防御），空行返回 ['']。
 */
export function wrapLine(line: string, columns: number): string[] {
  if (columns <= 0) {
    return [line];
  }
  const out: string[] = [];
  let current = '';
  let width = 0;
  for (const ch of line) {
    const w = charWidth(ch);
    if (width + w > columns && current.length > 0) {
      out.push(current);
      current = '';
      width = 0;
    }
    current += ch;
    width += w;
  }
  out.push(current);
  return out;
}

/** 把多行文本（可含 \n）折行为显示行数组。 */
function wrapText(text: string, columns: number): string[] {
  return text.split('\n').flatMap((line) => wrapLine(line, columns));
}

/**
 * 工具事件 → 气泡文本（Phase 2b：动作 + 摘要）。
 * tool_call 显示动作行，tool_result 显示结果行（✓/✗ + 摘要）。
 * 其余事件类型返回 null（不渲染）。
 */
export function toolEventText(event: AgentEvent): string | null {
  if (event.type === 'tool_call') {
    return `⚙ ${event.tool}(${JSON.stringify(event.args)})`;
  }
  if (event.type === 'tool_result') {
    return `${event.ok ? '✓' : '✗'} ${event.tool}: ${event.summary}`;
  }
  return null;
}

/**
 * 消息流 + 工具事件 + 流式缓冲 → 逐行显示行（含消息间空行分隔）。
 *
 * 折行宽度约定：用户消息因渲染时左右各加一个反白空格，按 columns-2 折；
 * 系统消息带 '⚠ ' 前缀参与折行；助手/工具/流式按整宽折。
 * 工具事件气泡渲染在已落库消息之后、流式文本之前（时间序）。
 */
export function buildDisplayLines(
  messages: readonly ChatMessage[],
  streaming: string,
  columns: number,
  toolEvents: readonly AgentEvent[] = [],
): DisplayLine[] {
  const out: DisplayLine[] = [];
  for (const message of messages) {
    if (message.role === 'user') {
      const userColumns = Math.max(1, columns - 2);
      for (const text of wrapText(message.content, userColumns)) {
        out.push({ kind: 'user', text: padDisplayEnd(text, userColumns) });
      }
    } else if (message.role === 'system') {
      for (const text of wrapText(`⚠ ${message.content}`, columns)) {
        out.push({ kind: 'system', text });
      }
    } else {
      for (const text of wrapText(message.content, columns)) {
        out.push({ kind: 'assistant', text });
      }
    }
    out.push({ kind: 'blank', text: '' });
  }
  let hadTool = false;
  for (const event of toolEvents) {
    const bubble = toolEventText(event);
    if (bubble !== null) {
      for (const text of wrapText(bubble, columns)) {
        out.push({ kind: 'tool', text });
      }
      hadTool = true;
    }
  }
  if (hadTool) {
    out.push({ kind: 'blank', text: '' });
  }
  if (streaming.length > 0) {
    for (const text of wrapText(streaming, columns)) {
      out.push({ kind: 'assistant', text });
    }
  }
  return out;
}

/**
 * 取尾部切片：先剔除末尾空行（避免最新内容行被空行挤出可视区），
 * 再截取最后 height 行。height <= 0 返回空。
 */
export function tailSlice(
  lines: readonly DisplayLine[],
  height: number,
): DisplayLine[] {
  let end = lines.length;
  while (end > 0 && lines[end - 1]?.kind === 'blank') {
    end -= 1;
  }
  if (height <= 0) {
    return [];
  }
  const trimmed = lines.slice(0, end);
  return trimmed.slice(Math.max(0, trimmed.length - height));
}
