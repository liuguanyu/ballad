/**
 * 滚动日志区：渲染会话历史，占据 Header 与输入区之间的全部剩余高度。
 *
 * 抗闪核心（全屏形态，与 cc 一致）：本区用 flexGrow 吃满剩余高度并 overflow=hidden，
 * 使整屏总行数每帧恒定——Ink 差分时只重绘变化的行，不整屏重排。历史变长时溢出被
 * 裁剪（显示尾部），而非把布局往上顶导致抖动闪烁。
 *
 * 超屏收缩（关键）：flexShrink=1 + minHeight=0 让本区在内容超过一屏时可缩到内容以下，
 * 溢出由 overflow=hidden 裁掉——否则 Yoga 以内容高度为下限拒绝收缩，会把下方输入框/
 * 状态栏挤出屏幕（输入回显消失）。固定块（输入框/状态栏）则由父层 flexShrink=0 锁死。
 *
 * 关键交互：用户消息反白显示（Ink 的 inverse 属性 = 前景/背景反转），
 * 助手消息常规色，与 cc 的视觉一致。
 * 职责单一：只做历史消息 → 视图的映射，不持有状态。
 */
import React from 'react';
import { Box, Text } from 'ink';
import type { ChatMessage } from '../../../core/contract.ts';
import { theme, glyph, textStyle } from '../theme.ts';

interface LogViewerProps {
  readonly messages: readonly ChatMessage[];
  /** 正在流式生成、尚未落库的助手文本。 */
  readonly streaming: string;
}

function MessageRow({ message }: { message: ChatMessage }): React.ReactElement {
  if (message.role === 'user') {
    // 反白显示：用户消息高亮，形成"我说过的话"视觉锚点（效果收口在 theme.textStyle）。
    return (
      <Box marginBottom={1}>
        <Text {...textStyle.userEcho}> {message.content} </Text>
      </Box>
    );
  }
  if (message.role === 'system') {
    return (
      <Box marginBottom={1}>
        <Text color={theme.warn}>{glyph.warn} {message.content}</Text>
      </Box>
    );
  }
  return (
    <Box marginBottom={1}>
      <Text>{message.content}</Text>
    </Box>
  );
}

export function LogViewer({
  messages,
  streaming,
}: LogViewerProps): React.ReactElement {
  return (
    <Box flexDirection="column" flexGrow={1} flexShrink={1} minHeight={0} overflow="hidden">
      {messages.map((message, i) => (
        <MessageRow key={i} message={message} />
      ))}
      {streaming.length > 0 ? (
        <Box marginBottom={1}>
          <Text>{streaming}</Text>
        </Box>
      ) : null}
    </Box>
  );
}
