/**
 * 流光帧驱动 hook：按固定间隔递增 frame，供 shimmerColors / spinnerFrame 推进动画。
 *
 * 职责单一：只管「计时推进帧」，不算颜色、不渲染。卸载时清理定时器，避免泄漏。
 * active=false 时暂停（如思考结束即静止），不占用定时器。
 *
 * 见 specs/tui-shimmer.spec.md（REQ-SHIM-3）。
 */
import { useEffect, useState } from 'react';

/** 默认帧间隔（100ms/帧）。 */
export const DEFAULT_INTERVAL_MS = 100;

interface UseShimmerFrameOptions {
  /** 帧间隔毫秒，默认 100。 */
  readonly intervalMs?: number;
  /** 是否推进动画，默认 true；false 时定格。 */
  readonly active?: boolean;
}

/** 返回随时间递增的 frame（active=false 时定格）。 */
export function useShimmerFrame(options: UseShimmerFrameOptions = {}): number {
  const { intervalMs = DEFAULT_INTERVAL_MS, active = true } = options;
  const [frame, setFrame] = useState<number>(0);

  useEffect(() => {
    if (!active) {
      return;
    }
    const timer = setInterval(() => {
      setFrame((f) => f + 1);
    }, intervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [intervalMs, active]);

  return frame;
}
