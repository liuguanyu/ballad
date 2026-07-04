/**
 * 详情面板（Ctrl+O 切换显隐；Phase 1 占位）。
 *
 * 职责单一：纯展示，无状态、无副作用。显隐由 App 的 detailsOpen 控制。
 * Phase 1 只放最小运行信息占位；Phase 2/3 再填思考细节 / Diff 视图。
 *
 * 铁律遵守：只从渲染层取数据，不感知大脑内部（脑口分离）。
 */
import React from 'react';
import { Box, Text } from 'ink';
import { theme } from '../theme.ts';

interface DetailsPanelProps {
  /** 累计会话消息条数（占位运行信息）。 */
  readonly messageCount: number;
  /** 累计输出 token（占位运行信息）。 */
  readonly outputTokens: number;
}

export function DetailsPanel({
  messageCount,
  outputTokens,
}: DetailsPanelProps): React.ReactElement {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={theme.accent}>Details</Text>
      <Text color={theme.muted}>
        {`  messages: ${messageCount} · out tokens: ${outputTokens}`}
      </Text>
    </Box>
  );
}
