/**
 * 顶部标题栏（cc 风格）。
 * 职责单一：纯展示，无状态、无副作用。
 */
import React from 'react';
import { Box, Text } from 'ink';
import { theme, glyph } from '../theme.ts';

interface HeaderProps {
  readonly title: string;
  readonly subtitle: string;
  readonly cwd: string;
}

export function Header({ title, subtitle, cwd }: HeaderProps): React.ReactElement {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text color={theme.accent}>{glyph.logo}</Text>
        <Text bold>{title}</Text>
      </Box>
      <Text color={theme.muted}>   {subtitle}</Text>
      <Text color={theme.muted}>   {cwd}</Text>
    </Box>
  );
}
