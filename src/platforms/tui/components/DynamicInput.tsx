/**
 * 底部固定输入框。
 *
 * 三大交互职责（各自独立、互不纠缠）：
 * 1. 动态高度：按换行数在 1~5 行伸缩，超过 5 行保持 5 行（内部裁剪显示尾部）。
 * 2. 历史翻阅：状态机见 specs/tui-history.spec.md（进出翻阅 / 多行光标 / 退出触发）。
 * 3. 文本编辑：字符输入、退格、回车提交、Shift+Enter 换行。
 *
 * 视觉（与 cc 一致）：上下各一条横线夹一个裸输入行——
 * 顶线始终存在：默认纯横线，翻阅态变为 `─ History n/n ─────` 压线；
 * 底线是纯横线；中间输入行无左右竖线。状态栏（ready/token）由 App
 * 排在本组件底线之下。手绘而非 Ink 内置 border（内置边框插不进文字）。
 *
 * 职责单一：本组件只负责渲染与事件分发；所有计算委托给 logic/inputModel。
 */
import React, { useEffect, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { theme, glyph } from '../theme.ts';
import {
  buildHistoryBorder,
  computeRows,
  historyPosition,
  idleHistoryState,
  stepHistory,
  visibleLines,
  type HistoryState,
} from '../logic/inputModel.ts';

interface DynamicInputProps {
  /** 历史输入（最旧 → 最新），用于 ↑/↓ 导航。 */
  readonly history: readonly string[];
  /** 是否禁用（大脑忙时）。 */
  readonly disabled: boolean;
  /** 终端列数，用于把顶边分隔线与底边补足整行。 */
  readonly width: number;
  readonly onSubmit: (value: string) => void;
  /**
   * 命令模式：由 App 据当前输入判定（'/' 开头且有候选命令）。
   * 为 true 时本组件把 ↑/↓/Enter/Esc 让渡给菜单（见下方回调），
   * 文本编辑（打字/退格）仍照常进行以驱动过滤。
   */
  readonly commandMode?: boolean;
  /** 命令模式下 ↑/↓ 移动菜单高亮（替代历史翻阅）。 */
  readonly onNavigate?: (dir: 'up' | 'down') => void;
  /** 命令模式下 Enter 选中当前高亮命令（替代提交给大脑）。 */
  readonly onAccept?: () => void;
  /** 命令模式下 Esc 关闭菜单。 */
  readonly onCancel?: () => void;
  /** 输入文本变化时回传镜像，供 App 计算命令模式与过滤。 */
  readonly onValueChange?: (value: string) => void;
  /**
   * Ctrl+V 粘贴：返回要追加进输入框的文本（剪贴板文本或图片标记 [Image: ...]）。
   * 由 App 注入 clipboard service；返回空串则忽略。
   */
  readonly onPaste?: () => Promise<string>;
  /**
   * 外部强制清空信号：值变化时清空内部 value（如 /model 选中后清掉 slash command）。
   * 不传则不生效；DynamicInput 的 value 是内部状态机独占，App 改镜像无法反向推回，
   * 故用此信号触发清空。用 number 而非 boolean，每次递增即触发一次。
   */
  readonly resetSignal?: number;
}

export function DynamicInput({
  history,
  disabled,
  width,
  onSubmit,
  commandMode = false,
  onNavigate,
  onAccept,
  onCancel,
  onValueChange,
  onPaste,
  resetSignal,
}: DynamicInputProps): React.ReactElement {
  // 单一状态源：value 与历史翻阅态合并在 HistoryState 里（见 spec）。
  const [state, setState] = useState<HistoryState>(() => idleHistoryState());

  // 外部清空信号：resetSignal 变化时清空 value（/model 选中后清掉 slash command）。
  useEffect(() => {
    if (resetSignal !== undefined && resetSignal > 0) {
      setState(idleHistoryState());
    }
  }, [resetSignal]);
  const { value, browsing } = state;

  // 把 value 变化镜像给 App，用于计算命令模式与菜单过滤（副作用集中一处，
  // 避免在每个 setState 旁散落回调）。
  useEffect(() => {
    onValueChange?.(value);
  }, [value, onValueChange]);

  useInput(
    (input, key) => {
      if (disabled) {
        return;
      }

      // Ctrl+V 粘贴：异步取剪贴板文本/图片标记，追加进输入（键入行为，退出翻阅）。
      if (key.ctrl && input === 'v') {
        if (onPaste) {
          void onPaste().then((pasted) => {
            if (pasted.length > 0) {
              setState((s) => idleHistoryState(s.value + pasted));
            }
          });
        }
        return;
      }

      // 命令模式让渡：↑/↓/Enter/Esc 交给菜单，文本编辑（打字/退格）继续往下走。
      if (commandMode) {
        if (key.upArrow || key.downArrow) {
          onNavigate?.(key.upArrow ? 'up' : 'down');
          return;
        }
        if (key.return && !key.shift) {
          onAccept?.();
          return;
        }
        if (key.escape) {
          onCancel?.();
          return;
        }
        // 其余（字符/退格）落到下方通用编辑分支，实时改写 value 以驱动过滤。
      }

      // 回车提交（非 Shift）。
      if (key.return && !key.shift) {
        if (value.trim().length === 0) {
          return;
        }
        onSubmit(value);
        setState(idleHistoryState());
        return;
      }

      // Shift+Enter 换行（键入行为，退出翻阅）。
      if (key.return && key.shift) {
        setState((s) => idleHistoryState(s.value + '\n'));
        return;
      }

      // 历史翻阅（委托纯函数状态机）。
      if (key.upArrow || key.downArrow) {
        setState((s) => stepHistory(history, s, key.upArrow ? 'up' : 'down'));
        return;
      }

      // 退格：删末字符；删到空且在翻阅态则退出翻阅。
      if (key.backspace || key.delete) {
        setState((s) => {
          const next = s.value.slice(0, -1);
          return next.length === 0 ? idleHistoryState('') : { ...s, value: next };
        });
        return;
      }

      // 普通字符输入：键入即退出翻阅、进入编辑（草稿作废）。
      if (input && !key.ctrl && !key.meta) {
        setState((s) => idleHistoryState(s.value + input));
      }
    },
    { isActive: true },
  );

  const rows = computeRows(value);
  const visible = visibleLines(value, rows);
  const fullBorder = '─'.repeat(Math.max(0, width));
  // 顶边始终存在：翻阅态显示 `─ History n/n ─` 压线，否则纯横线。
  const topBorder = browsing
    ? buildHistoryBorder(historyPosition(state.index), history.length, width)
    : fullBorder;

  return (
    <Box flexDirection="column">
      {/* 顶边：始终一条横线；翻阅态变为 History 压线 */}
      <Text color={theme.border}>{topBorder}</Text>
      {/* 文本区：裸输入行，仅提示符 + 文本，无左右竖线 */}
      {visible.map((line, i) => (
        <Box key={i}>
          <Text color={theme.prompt}>{i === 0 ? glyph.prompt : glyph.indent}</Text>
          <Text wrap="truncate-end">{line}</Text>
          {i === visible.length - 1 ? <Text color={theme.prompt}>{glyph.cursor}</Text> : null}
        </Box>
      ))}
      {/* 底边：一条纯横线到底（无圆角、无竖线） */}
      <Text color={theme.border}>{fullBorder}</Text>
    </Box>
  );
}
