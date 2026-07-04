/**
 * 统一启动开关：组装"大脑"与"嘴巴"。
 *
 * 这是脑口分离的接线点——选一个 Brain 实现，选一个表现层，插上运行。
 * Phase 4 换 Web GUI 时，只改这里的表现层挂载，core 与大脑一行不动。
 */
import React from 'react';
import { render } from 'ink';
import { createMockBrain } from './core/agent.ts';
import { App } from './platforms/tui/index.tsx';

/** 进入终端备用屏（alternate screen），实现占满全屏、退出后恢复原内容。 */
const ENTER_ALT_SCREEN = '\x1b[?1049h\x1b[H';
const LEAVE_ALT_SCREEN = '\x1b[?1049l';

/** Ink 满屏时每帧写出的整屏清屏序列（擦屏 + 清 scrollback + 光标归位）。 */
const CLEAR_TERMINAL = '\x1b[2J\x1b[3J\x1b[H';
/**
 * 替换序列：归位左上 + 清到屏末（eraseDown）。
 * - 归位 + 清到屏末 = 擦净整个可视区再重画，杜绝旧帧残影（纯归位会残影，输入行错乱）。
 * - 不含 \x1b[2J（整屏强擦）与 \x1b[3J（清 scrollback）——alt-screen 下二者多余，
 *   且是每帧全屏闪的主因。eraseDown 更轻，配合 alt-screen 原地覆盖，抖动最小。
 */
const HOME_ERASE_DOWN = '\x1b[H\x1b[J';

/**
 * 抗闪 stdout 包装：撑满全屏时 Ink 会每帧写出 clearTerminal 整屏清屏（闪）。
 * 该序列的 \x1b[2J\x1b[3J（整屏强擦 + 清 scrollback）在 alt-screen 下多余且是闪的主因，
 * 但完全不擦又会残影（输入行错乱）。故替换为 \x1b[H\x1b[J（归位 + 清到屏末）：
 * 擦净可视区再重画，无残影、抖动最小。其余输出原样透传。
 * 用 Proxy 透明代理，保留 columns/rows/isTTY/on 等 Ink 依赖的全部接口。
 */
function wrapStdoutAntiFlicker(stdout: NodeJS.WriteStream): NodeJS.WriteStream {
  return new Proxy(stdout, {
    get(target, prop, receiver) {
      if (prop === 'write') {
        return (chunk: unknown, ...rest: unknown[]): boolean => {
          const patched =
            typeof chunk === 'string' && chunk.includes(CLEAR_TERMINAL)
              ? chunk.split(CLEAR_TERMINAL).join(HOME_ERASE_DOWN)
              : chunk;
          return (target.write as (...args: unknown[]) => boolean)(patched, ...rest);
        };
      }
      const value = Reflect.get(target, prop, receiver);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}

async function main(): Promise<void> {
  const isTTY = process.stdout.isTTY === true;
  if (isTTY) {
    process.stdout.write(ENTER_ALT_SCREEN);
  }

  const brain = createMockBrain();
  const cwd = process.cwd();
  // 仅 TTY 下启用抗闪包装；非 TTY（测试/管道）透传原 stdout。
  const stdout = isTTY ? wrapStdoutAntiFlicker(process.stdout) : process.stdout;
  const app = render(React.createElement(App, { brain, cwd }), { stdout });

  try {
    await app.waitUntilExit();
  } finally {
    if (isTTY) {
      process.stdout.write(LEAVE_ALT_SCREEN);
    }
  }
}

void main();
