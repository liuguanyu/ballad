/**
 * 底部状态栏。Phase 1 展示运行状态与累计 Token；
 * 真实计费换算留待 Phase 2 补齐。
 * 职责单一：纯展示。
 */
import React from 'react';
import { Box, Text } from 'ink';
import { theme } from '../theme.ts';

interface StatusBarProps {
  readonly busy: boolean;
  readonly inputTokens: number;
  readonly outputTokens: number;
}

export function StatusBar({
  busy,
  inputTokens,
  outputTokens,
}: StatusBarProps): React.ReactElement {
  return (
    <Box>
      <Text color={busy ? theme.busy : theme.ready}>
        {busy ? '● thinking…' : '● ready'}
      </Text>
      <Text color={theme.muted}>
        {'   '}
        tokens in:{inputTokens} out:{outputTokens}
      </Text>
    </Box>
  );
}
