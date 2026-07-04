/**
 * 集成测试 · App（脑口接线）。
 * 注入一个确定性假大脑，验证完整链路：
 * 输入 → 提交 → 用户消息入滚动区 → 消费事件流 → 助手回复落库 → token 累加。
 *
 * 用假大脑而非 mockBrain，让测试与具体大脑实现解耦（低耦合原则的体现）。
 */
import { test, expect, describe } from 'bun:test';
import React from 'react';
import { render } from 'ink-testing-library';
import { App } from '../../src/platforms/tui/index.tsx';
import type { AgentEvent, Brain, ChatMessage } from '../../src/core/contract.ts';

type TestStdin = ReturnType<typeof render>['stdin'];

/** 一个立即吐出固定回复的假大脑，回显收到的最后一条用户消息。 */
function makeFakeBrain(reply: string): Brain {
  return async function* fake(
    history: readonly ChatMessage[],
  ): AsyncGenerator<AgentEvent, void, void> {
    const last = [...history].reverse().find((m) => m.role === 'user');
    yield { type: 'message_start', role: 'assistant' };
    yield { type: 'token', text: reply };
    if (last) {
      yield { type: 'token', text: `(echo:${last.content})` };
    }
    yield {
      type: 'message_end',
      usage: { inputTokens: 3, outputTokens: 7 },
    };
  };
}

const flush = (ms = 60) => new Promise((r) => setTimeout(r, ms));

/** 逐字符写入，忠实模拟真实键盘（首字符前预热，等 useInput 监听就绪）。 */
async function typeText(stdin: TestStdin, text: string): Promise<void> {
  await flush(20);
  for (const ch of text) {
    stdin.write(ch);
    await flush(20);
  }
}

describe('App 集成', () => {
  test('启动渲染骨架三要素', () => {
    const { lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('OK'), cwd: '/demo' }),
    );
    const frame = lastFrame() ?? '';
    expect(frame).toContain('ballad'); // Header
    expect(frame).toContain('ready'); // StatusBar
    expect(frame).toContain('> '); // Input 提示符（初始非翻阅，无 History 行）
    expect(frame).not.toContain('History'); // 初始不显示历史行
  });

  test('提交后：用户消息 + 助手回复都进入滚动区', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('reply-ok'), cwd: '/demo' }),
    );
    await typeText(stdin, 'write-code');
    stdin.write('\r');
    await flush(200);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('write-code'); // 用户消息
    expect(frame).toContain('reply-ok'); // 助手回复
    expect(frame).toContain('echo:write-code'); // 大脑确实读到 history
  });

  test('提交后 token 计数累加', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, 'hi');
    stdin.write('\r');
    await flush(200);
    const frame = lastFrame() ?? '';
    // usage: in 3 / out 7
    expect(frame).toContain('out:7');
  });

  test('提交后输入历史可用（上键回填刚发送的消息）', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, 'history-msg');
    stdin.write('\r');
    await flush(200);
    stdin.write('\x1b[A'); // 上键
    await flush();
    expect(lastFrame()).toContain('history-msg');
  });
});

describe('App 集成 · Slash 命令（REQ-CMD-1/2/6）', () => {
  test("输入 '/' 弹出菜单含 /exit 与提示栏", async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, '/');
    const frame = lastFrame() ?? '';
    expect(frame).toContain('/exit');
    expect(frame).toContain('Esc 关闭');
  });

  test("'/ex' 过滤后仍含 /exit（且菜单开着）", async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, '/ex');
    expect(lastFrame() ?? '').toContain('/exit');
  });

  test('选中 /exit 触发退出（onExit spy）且不喂大脑', async () => {
    let exited = false;
    let brainCalled = false;
    const brain: Brain = async function* spyBrain() {
      brainCalled = true;
      yield { type: 'message_start', role: 'assistant' };
    };
    const { stdin } = render(
      React.createElement(App, { brain, cwd: '/demo', onExit: () => (exited = true) }),
    );
    await typeText(stdin, '/exit');
    stdin.write('\r'); // Enter → onAccept → runCommand('exit') → onExit
    await flush(80);
    expect(exited).toBe(true);
    expect(brainCalled).toBe(false);
  });

  test("删掉 '/' 后菜单消失", async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, '/');
    expect(lastFrame() ?? '').toContain('/exit');
    stdin.write('\x7f'); // 退格删掉 '/'
    await flush();
    expect(lastFrame() ?? '').not.toContain('Esc 关闭');
  });

  test('Esc 关闭菜单：菜单消失但文本保留（REQ-CMD-4）', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, '/ex');
    expect(lastFrame() ?? '').toContain('Esc 关闭'); // 菜单开着
    stdin.write('\x1b'); // Esc
    await flush();
    const frame = lastFrame() ?? '';
    expect(frame).not.toContain('Esc 关闭'); // 菜单已消失
    expect(frame).toContain('/ex'); // 文本仍保留在输入行
  });

  test('Esc 关闭后再打字：菜单重新弹出（REQ-CMD-4）', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await typeText(stdin, '/e');
    stdin.write('\x1b'); // Esc 关闭
    await flush();
    expect(lastFrame() ?? '').not.toContain('Esc 关闭');
    await typeText(stdin, 'x'); // 继续打字 → 输入变化 → 重弹
    const frame = lastFrame() ?? '';
    expect(frame).toContain('Esc 关闭'); // 菜单重新弹出
    expect(frame).toContain('/exit');
  });
});

const CTRL_O = '\x0f';

describe('App 集成 · Ctrl+O 详情面板（REQ-HOTKEY-1/2/3）', () => {
  test('初始无面板；Ctrl+O 显示 Details；再 Ctrl+O 隐藏', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('x'), cwd: '/demo' }),
    );
    await flush(20);
    expect(lastFrame() ?? '').not.toContain('Details');
    stdin.write(CTRL_O);
    await flush();
    expect(lastFrame() ?? '').toContain('Details'); // 含运行信息占位
    stdin.write(CTRL_O);
    await flush();
    expect(lastFrame() ?? '').not.toContain('Details');
  });

  test('面板含运行信息（messages 计数）', async () => {
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: makeFakeBrain('reply-ok'), cwd: '/demo' }),
    );
    await typeText(stdin, 'hi');
    stdin.write('\r');
    await flush(200);
    stdin.write(CTRL_O);
    await flush();
    const frame = lastFrame() ?? '';
    expect(frame).toContain('Details');
    expect(frame).toContain('messages:'); // 运行信息项在位
  });

  test('流式进行中切换面板：助手回复仍完整落库（不丢字）', async () => {
    // 逐字慢吐的假大脑，模拟流式中途切换面板
    const slowBrain: Brain = async function* slow(history) {
      const last = [...history].reverse().find((m) => m.role === 'user');
      yield { type: 'message_start', role: 'assistant' };
      for (const ch of 'streamed-reply') {
        await new Promise((r) => setTimeout(r, 8));
        yield { type: 'token', text: ch };
      }
      if (last) {
        yield { type: 'token', text: `(${last.content})` };
      }
      yield { type: 'message_end', usage: { inputTokens: 1, outputTokens: 2 } };
    };
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain: slowBrain, cwd: '/demo' }),
    );
    await typeText(stdin, 'go');
    stdin.write('\r');
    await flush(30);
    stdin.write(CTRL_O); // 流式中途切面板
    await flush(200);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('streamed-reply'); // 流式内容完整，未被打断
    expect(frame).toContain('(go)'); // 大脑读到 history 且完整落库
  });
});

describe('App 集成 · 思考态流光（thinking 事件）', () => {
  const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

  test('收到 thinking 显示流光提示；首个 token 后消失', async () => {
    // 可控大脑：thinking → 停顿 → token → end，停顿期间可观测思考态
    let releaseToken: () => void = () => {};
    const gate = new Promise<void>((r) => (releaseToken = r));
    const brain: Brain = async function* thinkBrain() {
      yield { type: 'message_start', role: 'assistant' };
      yield { type: 'thinking', label: '正在推理' };
      await gate; // 卡在思考态，等测试观测后再放行
      yield { type: 'token', text: 'answer' };
      yield { type: 'message_end', usage: { inputTokens: 1, outputTokens: 1 } };
    };
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain, cwd: '/demo' }),
    );
    await typeText(stdin, 'q');
    stdin.write('\r');
    await flush(60);
    // 思考态：流光提示在位（含 label 或 spinner 字符）
    const thinkingFrame = lastFrame() ?? '';
    const hasSpinner = SPINNER.some((c) => thinkingFrame.includes(c));
    expect(thinkingFrame.includes('正在推理') || hasSpinner).toBe(true);

    releaseToken(); // 放行 → 吐正文
    await flush(80);
    const doneFrame = lastFrame() ?? '';
    expect(doneFrame).toContain('answer'); // 正文到达
    expect(doneFrame).not.toContain('正在推理'); // 思考态已消失
  });
});
