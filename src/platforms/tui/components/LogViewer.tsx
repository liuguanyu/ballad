/**
 * 滚动日志区：渲染会话历史，占据 Header 与输入区之间的全部剩余高度。
 *
 * 尾部锚定（关键修复）：Ink/Yoga 的 overflow=hidden 只裁内容"底部"（显示头部），
 * 历史超过一屏时最新消息反而被裁掉，且超高帧与终端自身滚动叠加导致行序错乱。
 * 故本组件不再依赖 overflow 裁剪，而是委托 logic/logLines 把消息流按列宽预折行、
 * 按 height 预算截取"最后 N 行"——每帧输出行数恒定且永远显示最新内容（cc 行为）。
 *
 * 布局配合：flexGrow 吃满剩余高度、flexShrink=1 + minHeight=0 + overflow=hidden
 * 作为兜底防线，保证下方输入框/状态栏永不被挤出屏幕。
 *
 * 关键交互：用户消息反白显示（Ink 的 inverse = 前景/背景反转），
 * 助手消息常规色，系统消息告警色，与 cc 的视觉一致。
 * 职责单一：只做「显示行 → 视图」的映射，折行/切片计算在 logic/logLines。
 */
import React from 'react';
import { Box, Text } from 'ink';
import type { AgentEvent, ChatMessage } from '../../../core/contract.ts';
import { theme, textStyle } from '../theme.ts';
import {
  buildDisplayLines,
  tailSlice,
  type DisplayLine,
} from '../logic/logLines.ts';

interface LogViewerProps {
  readonly messages: readonly ChatMessage[];
  /** 正在流式生成、尚未落库的助手文本。 */
  readonly streaming: string;
  /** 工具事件流（Phase 2b）：tool_call/tool_result 渲染为动作+摘要气泡。 */
  readonly toolEvents?: readonly AgentEvent[];
  /** 终端列数（预折行宽度）。缺省 80（非 TTY/测试回退）。 */
  readonly columns?: number;
  /** 可用行数预算（App 按整体布局扣除固定块后传入）。缺省不限（测试便利）。 */
  readonly height?: number;
}

function LineRow({ line }: { line: DisplayLine }): React.ReactElement {
  switch (line.kind) {
    case 'user':
      // 反白显示：用户消息高亮，形成"我说过的话"视觉锚点（效果收口在 theme.textStyle）。
      return <Text {...textStyle.userEcho}> {line.text} </Text>;
    case 'system':
      return <Text color={theme.warn}>{line.text}</Text>;
    case 'tool':
      return <Text color={theme.muted}>{line.text}</Text>;
    case 'blank':
      return <Text> </Text>;
    default:
      return <Text>{line.text.length === 0 ? ' ' : line.text}</Text>;
  }
}

export function LogViewer({
  messages,
  streaming,
  toolEvents = [],
  columns = 80,
  height,
}: LogViewerProps): React.ReactElement {
  const budget = height ?? Number.MAX_SAFE_INTEGER;
  const all = buildDisplayLines(messages, streaming, columns, toolEvents);
  const tail = tailSlice(all, budget);

  return (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflow="hidden">
      {tail.map((line, i) => (
        <LineRow key={i} line={line} />
      ))}
    </Box>
  );
}
