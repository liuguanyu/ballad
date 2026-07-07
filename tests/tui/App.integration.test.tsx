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

  test('选中 /model 呼出模型列表（REQ-CMD-7）', async () => {
    const models = [
      { name: 'glm', label: 'glm', hint: 'openai-v1 · glm-5.2' },
      { name: 'deepseek', label: 'deepseek', hint: 'openai-v1 · deepseek-v4' },
    ];
    const { stdin, lastFrame } = render(
      React.createElement(App, {
        brain: makeFakeBrain('x'),
        cwd: '/demo',
        availableModels: models,
        onSwitchModel: () => makeFakeBrain('switched'),
      }),
    );
    await typeText(stdin, '/model');
    stdin.write('\r'); // 选中 /model → 进入模型选择模式
    await flush(80);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('glm');
    expect(frame).toContain('deepseek');
  });

  test('切换模型后 Header 同步显示新模型名（REQ-CMD-7）', async () => {
    const models = [
      { name: 'glm', label: 'glm', hint: 'openai-v1' },
      { name: 'deepseek', label: 'deepseek', hint: 'openai-v1' },
    ];
    const { stdin, lastFrame } = render(
      React.createElement(App, {
        brain: makeFakeBrain('x'),
        cwd: '/demo',
        availableModels: models,
        activeModel: 'glm',
        onSwitchModel: () => makeFakeBrain('switched'),
      }),
    );
    expect(lastFrame() ?? '').toContain('model: glm');
    await typeText(stdin, '/model');
    stdin.write('\r'); // 进模型菜单
    await flush(80);
    stdin.write('\x1b[B'); // 下键 → 高亮 deepseek
    await flush(80);
    stdin.write('\r'); // 选中
    await flush(80);
    const frame = lastFrame() ?? '';
    expect(frame).toContain('model: deepseek'); // Header 已同步
    expect(frame).not.toContain('model: glm');
    expect(frame).not.toContain('/model'); // slash command 已被清空（resetSignal）
    expect(frame).not.toContain('Esc 关闭'); // 命令菜单也不再因 /model 重新弹出
  });

  test('在模型列表中选中某 model 触发 onSwitchModel（REQ-CMD-7）', async () => {
    const models = [
      { name: 'glm', label: 'glm', hint: 'openai-v1' },
      { name: 'deepseek', label: 'deepseek', hint: 'openai-v1' },
    ];
    const switched: string[] = [];
    const { stdin } = render(
      React.createElement(App, {
        brain: makeFakeBrain('x'),
        cwd: '/demo',
        availableModels: models,
        onSwitchModel: (name: string) => {
          switched.push(name);
          return makeFakeBrain('switched');
        },
      }),
    );
    await typeText(stdin, '/model');
    stdin.write('\r'); // 进模型菜单
    await flush(80);
    stdin.write('\r'); // 选中第一个（glm）
    await flush(80);
    expect(switched).toEqual(['glm']);
  });

  test('Esc 关闭模型列表（REQ-CMD-7）', async () => {
    const models = [
      { name: 'glm', label: 'glm', hint: 'openai-v1' },
      { name: 'deepseek', label: 'deepseek', hint: 'openai-v1' },
    ];
    const { stdin, lastFrame } = render(
      React.createElement(App, {
        brain: makeFakeBrain('x'),
        cwd: '/demo',
        availableModels: models,
        onSwitchModel: () => makeFakeBrain('x'),
      }),
    );
    await typeText(stdin, '/model');
    stdin.write('\r'); // 进模型菜单
    await flush(80);
    expect(lastFrame() ?? '').toContain('glm');
    stdin.write('\x1b'); // Esc
    await flush(80);
    expect(lastFrame() ?? '').not.toContain('Esc 关闭'); // 模型菜单关闭后提示栏消失
  });

  test('不传 availableModels 时 /model 选中无副作用（向后兼容）', async () => {
    let brainCalled = false;
    const brain: Brain = async function* () {
      brainCalled = true;
      yield { type: 'message_start', role: 'assistant' };
    };
    const { stdin } = render(
      React.createElement(App, { brain, cwd: '/demo' }),
    );
    await typeText(stdin, '/model');
    stdin.write('\r');
    await flush(80);
    // 无 availableModels：不弹模型菜单，不崩，brain 未被调用（命令不进对话流）
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

  test('大脑不发 thinking 事件时，提交后也默认显示"思考中"流光（真实模型场景）', async () => {
    // openai-v1 等协议全程不产 thinking 事件；等待期消息流里必须有反馈。
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const brain: Brain = async function* noThinkingBrain() {
      yield { type: 'message_start', role: 'assistant' };
      await gate; // 模拟真实模型的静默等待期（无 thinking 事件）
      yield { type: 'token', text: 'late-answer' };
      yield { type: 'message_end', usage: { inputTokens: 1, outputTokens: 1 } };
    };
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain, cwd: '/demo' }),
    );
    await typeText(stdin, 'q');
    stdin.write('\r');
    await flush(60);
    expect(lastFrame() ?? '').toContain('思考中'); // 默认流光在位
    release();
    await flush(80);
    const doneFrame = lastFrame() ?? '';
    expect(doneFrame).toContain('late-answer');
    expect(doneFrame).not.toContain('思考中'); // 首个 token 后消失
  });

  test('流光固定在输入框上横线正上方，并在持续后显示读秒', async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const brain: Brain = async function* thinkBrain() {
      yield { type: 'message_start', role: 'assistant' };
      yield { type: 'thinking', label: '正在推理' };
      await gate;
      yield { type: 'token', text: 'done' };
      yield { type: 'message_end', usage: { inputTokens: 1, outputTokens: 1 } };
    };
    const { stdin, lastFrame } = render(
      React.createElement(App, { brain, cwd: '/demo' }),
    );
    await typeText(stdin, 'q');
    stdin.write('\r');
    await flush(1200);
    const lines = (lastFrame() ?? '').split('\n');
    const thinkIdx = lines.findIndex((l) => l.includes('正在推理'));
    const inputTopIdx = lines.findIndex((l) => l.includes('─'.repeat(8)));
    expect(thinkIdx).toBeGreaterThan(-1);
    expect(inputTopIdx).toBeGreaterThan(-1);
    expect(inputTopIdx - thinkIdx).toBe(1); // thinking 贴在输入框顶线正上方
    expect(lines[thinkIdx]).toContain('1s');
    release();
    await flush(80);
  });
});
