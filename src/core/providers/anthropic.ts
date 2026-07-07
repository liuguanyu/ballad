/**
 * Anthropic 协议适配器（Phase 2a）：/v1/messages 流 → AgentEvent。
 *
 * 设计（守脑口分离 + No Any + 可单测）：
 * - 不直接 import 厂商 SDK 类型。定义最小 client 接口 AnthropicStreamClient，
 *   只暴露"发 messages.create(stream:true) → 异步迭代 raw 事件"。
 * - index.ts 负责把真实 @anthropic-ai/sdk 包成此接口注入；测试传 mock client。
 * - raw 事件经 Zod schema 逐事件校验收窄，杜绝 any（铁律 1）。解析失败吐 error 不中断流。
 *
 * 事件映射（spec REQ-PROV-3）：
 *   message_start       → message_start
 *   content_block_delta  text_delta      → token
 *   content_block_delta  thinking_delta  → thinking
 *   message_delta.usage  → message_end.usage
 */
import { z } from 'zod';
import type { AgentEvent, Brain, ChatMessage } from '../contract.ts';
import type { Adapter, ModelConfig } from '../provider.ts';
import { registerAdapter } from '../provider.ts';
import type { JsonSchema, Tool } from '../tools/registry.ts';

/** 入站消息（适配器内部用的最小形状，从 ChatMessage 映射）。 */
const InboundMsgSchema = z.object({
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string(),
});

/** Anthropic raw 流事件的最小收窄 schema（只取映射需要的字段）。 */
const StartEventSchema = z.object({
  type: z.literal('message_start'),
});

const DeltaTextSchema = z.object({
  type: z.literal('content_block_delta'),
  delta: z.object({ type: z.literal('text_delta'), text: z.string() }),
});

const DeltaThinkingSchema = z.object({
  type: z.literal('content_block_delta'),
  delta: z.object({ type: z.literal('thinking_delta'), thinking: z.string() }),
});

const MessageDeltaSchema = z.object({
  type: z.literal('message_delta'),
  usage: z
    .object({
      input_tokens: z.number().int().nonnegative().optional(),
      output_tokens: z.number().int().nonnegative(),
    })
    .optional(),
});

const StopEventSchema = z.object({ type: z.literal('message_stop') });

/** tool_use 块开始：带 tool 名 + callId（后续 input_json_delta 拼接参数）。 */
const ContentBlockStartSchema = z.object({
  type: z.literal('content_block_start'),
  index: z.number().int().nonnegative(),
  content_block: z.object({
    type: z.literal('tool_use'),
    id: z.string(),
    name: z.string(),
  }),
});

/** tool_use 参数分片（部分 JSON 文本，逐片拼接）。 */
const InputJsonDeltaSchema = z.object({
  type: z.literal('content_block_delta'),
  index: z.number().int().nonnegative(),
  delta: z.object({ type: z.literal('input_json_delta'), partial_json: z.string() }),
});

/** content_block 结束：若该块是 tool_use，此时吐 tool_call。 */
const ContentBlockStopSchema = z.object({
  type: z.literal('content_block_stop'),
  index: z.number().int().nonnegative(),
});

/**
 * 最小 client 接口：给定 messages + model，返回异步可迭代的 raw 事件流。
 * index.ts 把真实 SDK 的 client.messages.stream(...) 包成此形状。
 */
export interface AnthropicToolDefinition {
  readonly name: string;
  readonly description: string;
  readonly input_schema: JsonSchema;
}

export interface AnthropicStreamClient {
  stream(
    params: {
      model: string;
      messages: readonly { role: string; content: string }[];
      max_tokens: number;
      tools?: readonly AnthropicToolDefinition[];
    },
  ): AsyncIterable<unknown>;
}

/** 把 AdapterDeps.anthropic 收窄为 client（依赖注入入口）。 */
function asClient(raw: unknown): AnthropicStreamClient {
  if (raw === null || raw === undefined) {
    throw new Error('anthropic adapter: deps.anthropic not provided');
  }
  // 只校验 stream 是函数，不假设具体类（守低耦合）。
  const candidate = raw as { stream?: unknown };
  if (typeof candidate.stream !== 'function') {
    throw new Error('anthropic adapter: injected client has no stream() method');
  }
  return raw as AnthropicStreamClient;
}

function toAnthropicTools(tools: readonly Tool[] | undefined): readonly AnthropicToolDefinition[] {
  return (tools ?? []).map((tool) => ({
    name: tool.name,
    description: tool.description,
    input_schema: tool.jsonSchema,
  }));
}

function parseToolArgs(raw: string): Record<string, unknown> {
  if (raw.length === 0) {
    return {};
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/** 适配器主体。 */
const anthropicAdapter: Adapter = (config: ModelConfig, deps): Brain => {
  const client = asClient(deps.anthropic);
  return async function* (history: readonly ChatMessage[]): AsyncGenerator<AgentEvent, void, void> {
    const messages = history.flatMap((m) => {
      const r = InboundMsgSchema.safeParse(m);
      return r.success ? [{ role: r.data.role, content: r.data.content }] : [];
    });

    let emittedEnd = false;
    const toolUses = new Map<number, { id: string; name: string; args: string }>();
    try {
      const stream = client.stream({
        model: config.model,
        messages,
        max_tokens: 4096,
        tools: toAnthropicTools(deps.tools),
      });

      for await (const raw of stream) {
        const start = StartEventSchema.safeParse(raw);
        if (start.success) {
          yield { type: 'message_start', role: 'assistant' };
          continue;
        }
        // tool_use 块开始：登记 id + name，等 input_json_delta 拼参数。
        const blockStart = ContentBlockStartSchema.safeParse(raw);
        if (blockStart.success) {
          toolUses.set(blockStart.data.index, {
            id: blockStart.data.content_block.id,
            name: blockStart.data.content_block.name,
            args: '',
          });
          continue;
        }
        const text = DeltaTextSchema.safeParse(raw);
        if (text.success) {
          yield { type: 'token', text: text.data.delta.text };
          continue;
        }
        const thinking = DeltaThinkingSchema.safeParse(raw);
        if (thinking.success) {
          yield { type: 'thinking', text: thinking.data.delta.thinking };
          continue;
        }
        // tool_use 参数分片：逐片拼接部分 JSON。
        const inputDelta = InputJsonDeltaSchema.safeParse(raw);
        if (inputDelta.success) {
          const bucket = toolUses.get(inputDelta.data.index);
          if (bucket) {
            bucket.args += inputDelta.data.delta.partial_json;
          }
          continue;
        }
        // content_block 结束：若是 tool_use 块，吐统一 tool_call 事件。
        const blockStop = ContentBlockStopSchema.safeParse(raw);
        if (blockStop.success) {
          const bucket = toolUses.get(blockStop.data.index);
          if (bucket && bucket.name.length > 0) {
            yield {
              type: 'tool_call',
              tool: bucket.name,
              args: parseToolArgs(bucket.args),
              callId: bucket.id,
            };
            toolUses.delete(blockStop.data.index);
          }
          continue;
        }
        const msgDelta = MessageDeltaSchema.safeParse(raw);
        if (msgDelta.success && msgDelta.data.usage) {
          const u = msgDelta.data.usage;
          emittedEnd = true;
          yield {
            type: 'message_end',
            usage: {
              inputTokens: u.input_tokens ?? 0,
              outputTokens: u.output_tokens,
            },
          };
          continue;
        }
        const stop = StopEventSchema.safeParse(raw);
        if (stop.success && !emittedEnd) {
          emittedEnd = true;
          yield { type: 'message_end', usage: { inputTokens: 0, outputTokens: 0 } };
        }
        // 其余事件类型忽略——不映射。
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

registerAdapter('anthropic', anthropicAdapter);

export { anthropicAdapter };
