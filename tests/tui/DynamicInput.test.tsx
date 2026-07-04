/**
 * 组件测试 · DynamicInput（渲染 + 事件分发）。
 *
 * 分层约定：
 * - 历史导航 / 动态高度的"逻辑正确性"已由 inputModel.test.ts 确定性覆盖；
 * - 这里只验证组件把按键正确分发给纯函数、并渲染出预期结构。
 *
 * 忠实模拟：真实终端里字符逐个到达，故用 typeText 逐字符写入 stdin。
 * 一次性写多字符会被 Ink 的 parseKeypress 误判为转义序列——那不符合真实键入。
 * 方向键必须带 ESC 前缀（\x1b[A / \x1b[B），与真实终端一致。
 *
 * 已知限制（见文末 skip 用例）：Ink 的 useInput 对多字节字符（中文/emoji）
 * 处理不完善，中文键入的真实表现由端到端冒烟在真 pty 下覆盖。
 */
import { test, expect, describe } from 'bun:test';
import React from 'react';
import { render } from 'ink-testing-library';
import { DynamicInput } from '../../src/platforms/tui/components/DynamicInput.tsx';

type RenderResult = ReturnType<typeof render>;
type TestStdin = RenderResult['stdin'];

const ARROW_UP = '\x1b[A';
const ARROW_DOWN = '\x1b[B';
const ENTER = '\r';
const BACKSPACE = '\x7f';

const flush = () => new Promise((r) => setTimeout(r, 30));

/**
 * 逐字符写入，忠实模拟真实键盘（一次性多字符会被 Ink 误解析）。
 * 首字符前先等一拍：Ink 的 useInput 通过 useEffect 注册监听，
 * mount 当拍写入会丢失——真实终端里用户也不会在 0ms 内敲键。
 */
async function typeText(stdin: TestStdin, text: string): Promise<void> {
  await flush();
  for (const ch of text) {
    stdin.write(ch);
    await flush();
  }
}

/** 发送一个按键序列（如方向键），同样先预热等监听就绪。 */
async function press(stdin: TestStdin, seq: string): Promise<void> {
  await flush();
  stdin.write(seq);
  await flush();
}

function renderInput(opts?: {
  history?: string[];
  disabled?: boolean;
  width?: number;
  onSubmit?: (v: string) => void;
  commandMode?: boolean;
  onNavigate?: (dir: 'up' | 'down') => void;
  onAccept?: () => void;
  onCancel?: () => void;
  onValueChange?: (v: string) => void;
  onPaste?: () => Promise<string>;
}) {
  return render(
    React.createElement(DynamicInput, {
      history: opts?.history ?? [],
      disabled: opts?.disabled ?? false,
      width: opts?.width ?? 80,
      onSubmit: opts?.onSubmit ?? (() => {}),
      commandMode: opts?.commandMode ?? false,
      onNavigate: opts?.onNavigate,
      onAccept: opts?.onAccept,
      onCancel: opts?.onCancel,
      onValueChange: opts?.onValueChange,
      onPaste: opts?.onPaste,
    }),
  );
}

describe('DynamicInput · 键入与提交', () => {
  test('初始非翻阅态：不显示 History 行', () => {
    expect(renderInput({ history: ['a'] }).lastFrame()).not.toContain('History');
  });

  test('ASCII 键入回显到输入框', async () => {
    const { stdin, lastFrame } = renderInput();
    await typeText(stdin, 'hello');
    expect(lastFrame()).toContain('hello');
  });

  test('回车提交非空内容并清空', async () => {
    const submitted: string[] = [];
    const { stdin, lastFrame } = renderInput({ onSubmit: (v) => submitted.push(v) });
    await typeText(stdin, 'submit-me');
    stdin.write(ENTER);
    await flush();
    expect(submitted).toEqual(['submit-me']);
    expect(lastFrame()).not.toContain('submit-me');
  });

  test('空内容回车不触发 onSubmit', async () => {
    let called = false;
    const { stdin } = renderInput({ onSubmit: () => (called = true) });
    stdin.write(ENTER);
    await flush();
    expect(called).toBe(false);
  });

  test('退格删除字符', async () => {
    const { stdin, lastFrame } = renderInput();
    await typeText(stdin, 'abc');
    stdin.write(BACKSPACE);
    await flush();
    const frame = lastFrame() ?? '';
    expect(frame).toContain('ab');
    expect(frame).not.toContain('abc');
  });

  test('disabled 时忽略输入与提交', async () => {
    let called = false;
    const { stdin, lastFrame } = renderInput({
      disabled: true,
      onSubmit: () => (called = true),
    });
    await typeText(stdin, 'x');
    stdin.write(ENTER);
    await flush();
    expect(called).toBe(false);
    expect(lastFrame()).not.toContain('> x');
  });
});

describe('DynamicInput · 历史翻阅（组件分发）', () => {
  const history = ['first', 'second', 'third'];

  test('上键进入翻阅：回填最新一条并显示 History 3/3', async () => {
    const { stdin, lastFrame } = renderInput({ history });
    await press(stdin, ARROW_UP);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('third');
    expect(frame).toContain('History 3/3');
  });

  test('全局末行再下键：退出翻阅、History 行消失、回到空', async () => {
    const { stdin, lastFrame } = renderInput({ history });
    await press(stdin, ARROW_UP); // 进翻阅 → third（单行=末行）
    await press(stdin, ARROW_DOWN); // 末行再↓ → 退出翻阅
    const frame = lastFrame() ?? '';
    expect(frame).not.toContain('History');
    expect(frame).not.toContain('> third');
  });

  test('键入任意字符退出翻阅（History 行消失）', async () => {
    const { stdin, lastFrame } = renderInput({ history });
    await press(stdin, ARROW_UP); // 进翻阅
    expect(lastFrame() ?? '').toContain('History');
    await typeText(stdin, 'x'); // 键入 → 退出翻阅
    expect(lastFrame() ?? '').not.toContain('History');
  });

  test('删字删到空退出翻阅', async () => {
    const { stdin, lastFrame } = renderInput({ history: ['ab'] });
    await press(stdin, ARROW_UP); // 进翻阅 → 'ab'
    expect(lastFrame() ?? '').toContain('History');
    stdin.write(BACKSPACE);
    await flush();
    stdin.write(BACKSPACE);
    await flush();
    expect(lastFrame() ?? '').not.toContain('History');
  });
});

describe('DynamicInput · 动态高度与边框', () => {
  test('单行输入含提示符 >', async () => {
    const { stdin, lastFrame } = renderInput();
    await typeText(stdin, 'oneline');
    expect(lastFrame()).toContain('> oneline');
  });

  test('底部是纯横线（无圆角、无竖线），文字不溢出到该行', async () => {
    const { stdin, lastFrame } = renderInput();
    await typeText(stdin, 'abcdef');
    const lines = (lastFrame() ?? '').split('\n');
    const last = lines.at(-1) ?? '';
    expect(last).toMatch(/^─+$/); // 末行全是横线
    expect(last).not.toContain('╰');
    expect(last).not.toContain('abcdef');
  });

  test('输入行无左右竖线', async () => {
    const { stdin, lastFrame } = renderInput();
    await typeText(stdin, 'x');
    const inputLine = (lastFrame() ?? '')
      .split('\n')
      .find((l) => l.includes('> x')) ?? '';
    expect(inputLine).not.toContain('│');
  });
});

describe('DynamicInput · 命令模式让渡（REQ-CMD-4/5）', () => {
  test('命令模式下 ↑/↓ 走 onNavigate、不触发历史翻阅', async () => {
    const nav: Array<'up' | 'down'> = [];
    const { stdin } = renderInput({
      commandMode: true,
      history: ['old'],
      onNavigate: (d) => nav.push(d),
    });
    await press(stdin, ARROW_DOWN);
    await press(stdin, ARROW_UP);
    expect(nav).toEqual(['down', 'up']);
  });

  test('命令模式下 Enter 走 onAccept、不走 onSubmit', async () => {
    let accepted = false;
    let submitted = false;
    const { stdin } = renderInput({
      commandMode: true,
      onAccept: () => (accepted = true),
      onSubmit: () => (submitted = true),
    });
    await typeText(stdin, '/'); // 进入命令文本
    stdin.write(ENTER);
    await flush();
    expect(accepted).toBe(true);
    expect(submitted).toBe(false);
  });

  test('命令模式下 Esc 走 onCancel', async () => {
    let cancelled = false;
    const { stdin } = renderInput({
      commandMode: true,
      onCancel: () => (cancelled = true),
    });
    await press(stdin, '\x1b'); // ESC
    expect(cancelled).toBe(true);
  });

  test('命令模式下打字仍改写输入并回传 onValueChange', async () => {
    const seen: string[] = [];
    const { stdin, lastFrame } = renderInput({
      commandMode: true,
      onValueChange: (v) => seen.push(v),
    });
    await typeText(stdin, '/ex');
    expect(lastFrame() ?? '').toContain('/ex');
    expect(seen.at(-1)).toBe('/ex');
  });
});

describe('DynamicInput · Ctrl+V 粘贴（REQ-CLIP-5）', () => {
  const CTRL_V = '\x16';

  test('Ctrl+V 调用 onPaste 并把返回文本追加进输入', async () => {
    const { stdin, lastFrame } = renderInput({
      onPaste: async () => 'pasted-text',
    });
    await flush();
    stdin.write(CTRL_V);
    await flush();
    await flush();
    expect(lastFrame() ?? '').toContain('pasted-text');
  });

  test('onPaste 返回空串时不改动输入', async () => {
    const { stdin, lastFrame } = renderInput({ onPaste: async () => '' });
    await typeText(stdin, 'abc');
    stdin.write(CTRL_V);
    await flush();
    await flush();
    const frame = lastFrame() ?? '';
    expect(frame).toContain('abc'); // 原文保留，无多余追加
  });
});

describe('DynamicInput · 已知输入层限制（留档）', () => {
  // Ink useInput 对一次性写入的多字节字符会过滤（parseKeypress 误判），
  // 这不是组件缺陷。真实中文键入由端到端冒烟在真 pty 下验证。
  test.skip('中文键入回显（Ink 输入层限制，见 e2e 冒烟）', () => {});
});
