/**
 * 大脑主体（Phase 1 mock 实现）。
 *
 * 铁律遵守：
 * - 脑口分离：只产出 contract 事件，禁止感知终端 / 渲染。
 * - 职责单一：本文件只负责"如何流式产出事件"，不负责如何显示。
 * - 低耦合：对外暴露的是 Brain 抽象类型，Phase 2 可无痛替换为 LangGraph 实现。
 *
 * Phase 2 会用 LangGraph.js + Instructor 替换 mockBrain，
 * 但对外签名（Brain）保持不变，嘴巴层一行不改。
 */
import type { AgentEvent, Brain, ChatMessage } from './contract.ts';

/** 让出事件循环，模拟网络流的到达节奏（不阻塞渲染层）。 */
function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 根据用户最后一条输入，编造一段可流式吐出的回复文本。 */
function draftReply(history: readonly ChatMessage[]): string {
  const lastUser = [...history].reverse().find((m) => m.role === 'user');
  const prompt = lastUser?.content.trim() ?? '';
  if (prompt.length === 0) {
    return '你好，我是 ballad —— 一个脑口分离架构的 Coding Agent。请输入你的需求。';
  }
  return (
    `收到你的消息：「${prompt}」。\n` +
    '当前为 Phase 1 骨架，大脑以流式方式逐字吐出事件，表现层负责无闪烁渲染。' +
    '后续接入 LangGraph.js 与真实模型后，这里的逻辑会被替换，而契约保持不变。'
  );
}

/**
 * Phase 1 的占位大脑：先思考、再把回复按字符流式吐出。
 * @param charDelayMs 每个字符之间的间隔，用于验证高帧率下的渲染稳定性。
 */
export function createMockBrain(charDelayMs = 12): Brain {
  return async function* mockBrain(
    history: readonly ChatMessage[],
  ): AsyncGenerator<AgentEvent, void, void> {
    yield { type: 'message_start', role: 'assistant' };

    // 思考阶段：每轮回答前先推理（对齐真实 Agent 的 reasoning 前奏）。
    // 思考时长随输入长度自然增减：短问题想一下，长问题多想会儿。
    // 基线 3s、上限 6s——让流光从容扫几个来回，肉眼看得清「思考中」的呼吸感。
    // charDelayMs=0（测试用）时思考同样压扁为 0，避免单测空等数秒。
    const lastUser = [...history].reverse().find((m) => m.role === 'user');
    const promptLen = lastUser?.content.trim().length ?? 0;
    const thinkMs = charDelayMs === 0 ? 0 : Math.min(3000 + promptLen * 80, 6000);
    yield { type: 'thinking', label: '正在推理' };
    await delay(thinkMs);

    const reply = draftReply(history);
    for (const char of reply) {
      await delay(charDelayMs);
      yield { type: 'token', text: char };
    }

    const outputTokens = Math.ceil(reply.length / 4);
    const inputTokens = Math.ceil(
      history.reduce((n, m) => n + m.content.length, 0) / 4,
    );
    yield {
      type: 'message_end',
      usage: { inputTokens, outputTokens },
    };
  };
}
