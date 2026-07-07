/**
 * 上拉选择框（纯渲染，泛型可复用）。
 *
 * 职责单一：只把「过滤后的 items + 菜单状态」映射为视图，不持有状态、不含 useInput——
 * 键盘由 App/DynamicInput 驱动（命令模式让渡）。slash command / MCP list 等复用同一组件。
 *
 * 视觉（贴合 cc / reasonix 截图）：最多 MENU_WINDOW 行，高亮行用主题色（theme.selected）
 * 前景着色（非反白），每行 `label  hint`；底部一条提示栏 `↑/↓ 移动 · Enter 选中 · Esc 关闭`。
 * 空 items 由上层决定不挂载，本组件对空 items 返回空盒子以防御。
 */
import React from 'react';
import { Box, Text } from 'ink';
import { theme } from '../theme.ts';
import {
  visibleWindow,
  type MenuItem,
  type MenuState,
} from '../logic/selectMenu.ts';

interface SelectMenuProps {
  /** 已过滤的候选项（顺序即展示顺序）。 */
  readonly items: readonly MenuItem[];
  /** 高亮 / 滚动状态。 */
  readonly state: MenuState;
}

export function SelectMenu({ items, state }: SelectMenuProps): React.ReactElement | null {
  if (items.length === 0) {
    return null;
  }
  const rows = visibleWindow(items, state);

  return (
    <Box flexDirection="column">
      {rows.map(({ item, active }) => {
        const line = item.hint ? `${item.label}  ${item.hint}` : item.label;
        return (
          <Box key={item.value}>
            {active ? (
              <Text color={theme.selected}>{` ${line} `}</Text>
            ) : (
              <Text color={theme.muted}>{` ${line} `}</Text>
            )}
          </Box>
        );
      })}
      <Text color={theme.muted}>↑/↓ 移动 · Enter 选中 · Esc 关闭</Text>
    </Box>
  );
}
