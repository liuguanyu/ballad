/**
 * TUI 视觉规范单一入口："嘴巴"层所有颜色与排版符号在此收口。
 * 组件只引用语义名（theme.prompt / glyph.cursor），不认具体色值。
 * 当前单主题；将来加 dark/light 只需新增 satisfies Theme 的对象，组件零改动。
 */
import type { TextProps } from 'ink';

type InkColor = NonNullable<TextProps['color']>;

interface Theme {
  readonly accent: InkColor; // 品牌强调（Logo ▓▓）
  readonly prompt: InkColor; // 输入提示符 > 与光标 ▋
  readonly border: InkColor; // 手绘横线（输入框上下边、History 压线）
  readonly muted: InkColor; // 副标题 / cwd / token 等次要信息
  readonly ready: InkColor; // 空闲状态点
  readonly busy: InkColor; // 思考中状态点
  readonly warn: InkColor; // 系统/错误消息 ⚠
  readonly selected: InkColor; // 选择框高亮项前景（命令菜单 / MCP list 等）
}

export const theme = {
  accent: 'magentaBright',
  prompt: 'cyan',
  border: 'gray',
  muted: 'gray',
  ready: 'green',
  busy: 'yellow',
  warn: 'yellow',
  selected: 'cyan',
} satisfies Theme;

/** 排版符号集中，避免 ▓▓ / ▋ / ⚠ / "> " 散落各处。 */
export const glyph = {
  logo: '▓▓ ',
  prompt: '> ',
  indent: '  ', // 多行输入非首行的对齐占位
  cursor: '▋',
  warn: '⚠',
} as const;

/**
 * 文本效果（非颜色）：直接展开到 <Text {...textStyle.xxx}>。
 * 收口 inverse/bold/underline 等布尔样式，让"高亮该长什么样"只在此处决定。
 * userEcho = 用户消息回显的高亮锚点（当前用反白，将来可换 bold+背景色而不动组件）。
 * 注：选择框高亮已改为主题色前景（theme.selected），不再用反白，故此处不再有 selected 样式。
 */
export const textStyle = {
  userEcho: { inverse: true },
} as const satisfies Record<string, Partial<TextProps>>;
