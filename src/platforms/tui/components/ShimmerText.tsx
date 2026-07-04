/**
 * 流光文字组件：一条微光扫过文字（cc 思考态的呼吸感）。
 *
 * 组装：useShimmerFrame 拿 frame → shimmerColors 拿每字符色 → 渲染带色 <Text>。
 * 可选 spinner 前缀（盲文旋转字符）。复用于歌词流光、模型思考态提示。
 *
 * 职责单一：只做「帧 + 颜色 → 视图」的组装，算法在 logic/shimmer，计时在 hooks。
 * 见 specs/tui-shimmer.spec.md（REQ-SHIM-4）。
 */
import React from 'react';
import { Box, Text } from 'ink';
import {
  SHIMMER_ACCENT,
  shimmerColors,
  spinnerFrame,
} from '../logic/shimmer.ts';
import { useShimmerFrame } from '../hooks/useShimmerFrame.ts';

interface ShimmerTextProps {
  /** 要展示的文本。 */
  readonly text: string;
  /** 是否前置盲文旋转 spinner，默认 false。 */
  readonly spinner?: boolean;
  /** 是否推进动画，默认 true；false 时定格（静止展示 / 思考结束）。 */
  readonly active?: boolean;
  /** 帧间隔毫秒，默认 100。 */
  readonly intervalMs?: number;
  /** 自定义光束调色板（暗→亮→暗）。 */
  readonly palette?: readonly string[];
}

export function ShimmerText({
  text,
  spinner = false,
  active = true,
  intervalMs,
  palette,
}: ShimmerTextProps): React.ReactElement {
  const frame = useShimmerFrame({ active, intervalMs });
  const colors = shimmerColors(text, frame, palette ? { palette } : undefined);
  const chars = [...text];

  return (
    <Box>
      {spinner ? (
        <Text color={SHIMMER_ACCENT}>{spinnerFrame(frame)} </Text>
      ) : null}
      {chars.map((ch, i) => (
        <Text key={i} color={colors[i]}>
          {ch}
        </Text>
      ))}
    </Box>
  );
}
