/**
 * Slash 命令注册表与命令模式判定（纯逻辑，无 React / Ink）。
 *
 * 铁律遵守：命令是 TUI 概念，不进 core；No AnyScript。
 * 加新命令 = 往 SLASH_COMMANDS 追加一项 + 在 App 的执行分发里加一个 case。
 *
 * 见 specs/tui-slash-commands.spec.md（REQ-CMD-1 命令模式、REQ-CMD-6 /exit）。
 */
import type { MenuItem } from './selectMenu.ts';

/** 一条 slash 命令：复用 MenuItem 形状，value 为稳定标识、label 为展示名。 */
export interface SlashCommand extends MenuItem {
  readonly value: string; // 'exit'
  readonly label: string; // '/exit'
  readonly hint: string; // '退出 ballad'
}

/** 命令注册表（有序，即菜单展示顺序）。 */
export const SLASH_COMMANDS: readonly SlashCommand[] = [
  { value: 'exit', label: '/exit', hint: '退出 ballad' },
  { value: 'model', label: '/model', hint: '切换模型' },
];

/**
 * 是否进入命令模式：文本以 '/' 开头且不含空格/换行。
 * 一旦出现空格或换行（如 '/e x'、'/a\n'），视为普通输入，不再弹菜单。
 */
export function isCommandQuery(value: string): boolean {
  return value.startsWith('/') && !/\s/.test(value);
}
