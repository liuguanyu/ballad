/**
 * OpenAI v2 协议适配器（Phase 2a）：/v1/responses 流 → AgentEvent。
 *
 * 设计同 anthropic / openaiChat：不直接吃厂商 SDK 类型，定义最小 client 接口
 * OpenAIResponsesClient，index.ts 把真实 openai sdk 的 client.responses.create({stream:true})
 * 包成此接口注入；测试传 mock。raw 事件经 Zod 收窄，零 any。
 *
 * 事件映射（spec REQ-PROV-3）：
 *   response.created               → message_start
 *   response.output_text.delta     → token
 *   response.reasoning_text.delta  → thinking
 *   response.completed（response.usage）→ message_end.usage
 *
 * v2 与 v1 的关键差异：usage 字段名是 input_tokens/output_tokens（v1 是
 * prompt_tokens/completion_tokens）；事件 type 是点分形式（response.xxx）。
 */
import { z } from 'zod';
import type { AgentEvent, Brain, ChatMessage } from '../contract.ts';
import type { Adapter, ModelConfig } from '../provider.ts';
import { registerAdapter } from '../provider.ts';

const InboundMsgSchema = z.object({
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string(),
});

/** v2 事件的最小收窄 schema（只取映射需要的字段）。 */
const CreatedSchema = z.object({ type: z.literal('response.created') });

const TextDeltaSchema = z.object({
  type: z.literal('response.output_text.delta'),
  delta: z.string(),
});

const ReasoningDeltaSchema = z.object({
  type: z.literal('response.reasoning_text.delta'),
  delta: z.string(),
});

const CompletedSchema = z.object({
  type: z.literal('response.completed'),
  response: z.object({
    usage: z
      .object({
        input_tokens: z.number().int().nonnegative().optional(),
        output_tokens: z.number().int().nonnegative().optional(),
      })
      .optional(),
  }),
});

/** v2 入参用 input_items（字符串数组）而非 messages；这里把历史折成 input。 */
export interface OpenAIResponsesClient {
  stream(params: {
    model: string;
    input: string;
    stream: true;
  }): AsyncIterable<unknown>;
}

function asClient(raw: unknown): OpenAIResponsesClient {
  if (raw === null || raw === undefined) {
    throw new Error('openai-v2 adapter: deps.openai not provided');
  }
  const candidate = raw as { stream?: unknown };
  if (typeof candidate.stream !== 'function') {
    throw new Error('openai-v2 adapter: injected client has no stream() method');
  }
  return raw as OpenAIResponsesClient;
}

const openaiResponsesAdapter: Adapter = (config: ModelConfig, deps): Brain => {
  const client = asClient(deps.openai);
  return async function* (history: readonly ChatMessage[]): AsyncGenerator<AgentEvent, void, void> {
    // v2 的 input 是单条用户文本；取最后一条 user 消息作为输入。
    const lastUser = [...history].reverse().find((m) => {
      const r = InboundMsgSchema.safeParse(m);
      return r.success && r.data.role === 'user';
    });
    const input = lastUser?.content ?? '';

    let emittedEnd = false;
    try {
      const stream = client.stream({ model: config.model, input, stream: true });

      for await (const raw of stream) {
        const created = CreatedSchema.safeParse(raw);
        if (created.success) {
          yield { type: 'message_start', role: 'assistant' };
          continue;
        }
        const text = TextDeltaSchema.safeParse(raw);
        if (text.success) {
          yield { type: 'token', text: text.data.delta };
          continue;
        }
        const reasoning = ReasoningDeltaSchema.safeParse(raw);
        if (reasoning.success) {
          yield { type: 'thinking' };
          continue;
        }
        const completed = CompletedSchema.safeParse(raw);
        if (completed.success) {
          const u = completed.data.response.usage;
          emittedEnd = true;
          yield {
            type: 'message_end',
            usage: {
              inputTokens: u?.input_tokens ?? 0,
              outputTokens: u?.output_tokens ?? 0,
            },
          };
          continue;
        }
        // 其余事件类型（in_progress / output_item.* / reasoning_summary.* 等）忽略。
      }
      if (!emittedEnd) {
        yield { type: 'message_end', usage: { inputTokens: 0, outputTokens: 0 } };
      }
    } catch (err) {
      yield {
        type: 'error',
        message: err instanceof Error ? err.message : String(err),
      };
    }
  };
};

registerAdapter('openai-v2', openaiResponsesAdapter);

export { openaiResponsesAdapter };
