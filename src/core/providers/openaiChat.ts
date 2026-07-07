/**
 * OpenAI v1 协议适配器（Phase 2a）：/v1/chat/completions 流 → AgentEvent。
 *
 * 设计同 anthropic 适配器：不直接吃厂商 SDK 类型，定义最小 client 接口 OpenAIChatClient，
 * index.ts 把真实 openai sdk 包成此接口注入；测试传 mock。raw chunk 经 Zod 收窄，零 any。
 *
 * 事件映射（spec REQ-PROV-3）：
 *   首个 chunk（有 choices）        → message_start（v1 无原生 start 事件）
 *   choices[].delta.content          → token
 *   choices[].delta.reasoning_content → thinking（非标字段，glm/deepseek 等兼容网关透传思考）
 *   末 chunk usage（include_usage）  → message_end.usage
 *
 * 边界：usage chunk 来临时 choices 常为空数组（v1 已知行为），单独识别。
 *       reasoning_content 不在 OpenAI 官方标准里，是兼容网关私货；有就映射、无就跳过。
 */
import { z } from 'zod';
import type { AgentEvent, Brain, ChatMessage } from '../contract.ts';
import type { Adapter, ModelConfig } from '../provider.ts';
import { registerAdapter } from '../provider.ts';
import type { JsonSchema, Tool } from '../tools/registry.ts';

const InboundMsgSchema = z.object({
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string(),
});

/** v1 chunk 的最小收窄 schema。 */
const ToolCallSchema = z.object({
  index: z.number().int().nonnegative().optional(),
  id: z.string().optional(),
  function: z
    .object({
      name: z.string().optional(),
      arguments: z.string().optional(),
    })
    .optional(),
});

const ChoiceSchema = z.object({
  // content 是标准正文；reasoning_content 是 glm/deepseek 等兼容网关的非标思考透传字段。
  delta: z
    .object({
      content: z.string().optional(),
      reasoning_content: z.string().optional(),
      tool_calls: z.array(ToolCallSchema).optional(),
    })
    .optional(),
  finish_reason: z.string().nullable().optional(),
});

const ChunkSchema = z.object({
  choices: z.array(ChoiceSchema).optional(),
  usage: z
    .object({
      prompt_tokens: z.number().int().nonnegative().optional(),
      completion_tokens: z.number().int().nonnegative().optional(),
    })
    .optional(),
});

/**
 * 最小 client 接口：发 chat.completions.create(stream:true) → 异步迭代 raw chunk。
 * index.ts 把真实 openai sdk 的 client.chat.completions.create({stream:true}) 包成此形状。
 */
export interface OpenAIToolDefinition {
  readonly type: 'function';
  readonly function: {
    readonly name: string;
    readonly description: string;
    readonly parameters: JsonSchema;
  };
}

export interface OpenAIChatClient {
  stream(params: {
    model: string;
    messages: readonly { role: string; content: string }[];
    stream: true;
    stream_options?: { include_usage: true };
    tools?: readonly OpenAIToolDefinition[];
  }): AsyncIterable<unknown>;
}

function asClient(raw: unknown): OpenAIChatClient {
  if (raw === null || raw === undefined) {
    throw new Error('openai-v1 adapter: deps.openai not provided');
  }
  const candidate = raw as { stream?: unknown };
  if (typeof candidate.stream !== 'function') {
    throw new Error('openai-v1 adapter: injected client has no stream() method');
  }
  return raw as OpenAIChatClient;
}

function toOpenAITools(tools: readonly Tool[] | undefined): readonly OpenAIToolDefinition[] {
  return (tools ?? []).map((tool) => ({
    type: 'function' as const,
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.jsonSchema,
    },
  }));
}

function parseToolArgs(raw: string | undefined): Record<string, unknown> {
  if (!raw) {
    return {};
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

const openaiChatAdapter: Adapter = (config: ModelConfig, deps): Brain => {
  const client = asClient(deps.openai);
  return async function* (history: readonly ChatMessage[]): AsyncGenerator<AgentEvent, void, void> {
    const messages = history.flatMap((m) => {
      const r = InboundMsgSchema.safeParse(m);
      return r.success ? [{ role: r.data.role, content: r.data.content }] : [];
    });

    let started = false;
    let emittedEnd = false;
    const toolCalls = new Map<number, { id: string; name: string; args: string }>();
    try {
      const stream = client.stream({
        model: config.model,
        messages,
        stream: true,
        stream_options: { include_usage: true },
        tools: toOpenAITools(deps.tools),
      });

      for await (const raw of stream) {
        const chunk = ChunkSchema.safeParse(raw);
        if (!chunk.success) {
          continue; // 形状不符，跳过（不抛错，保流）
        }
        const { choices, usage } = chunk.data;

        if (!started && choices && choices.length > 0) {
          started = true;
          yield { type: 'message_start', role: 'assistant' };
        }

        if (choices) {
          for (const choice of choices) {
            // 兼容网关的思考透传（glm/deepseek 等用 reasoning_content）→ thinking 事件。
            // 驱动 TUI 流光，且首个正文 token 仍会清除思考态（见 App handleSubmit）。
            // text 字段承载实际思考文本，TUI 可折叠展示。
            const reasoning = choice.delta?.reasoning_content;
            if (typeof reasoning === 'string' && reasoning.length > 0) {
              yield { type: 'thinking', text: reasoning };
            }
            const text = choice.delta?.content;
            if (typeof text === 'string' && text.length > 0) {
              yield { type: 'token', text };
            }

            // 工具调用分片累积：v1 把 tool_calls 拆多个 chunk 增量吐，按 index 归桶，
            // name/id 首片给出、arguments 逐片拼接，finish_reason=tool_calls 时统一吐 tool_call。
            const deltaToolCalls = choice.delta?.tool_calls;
            if (deltaToolCalls) {
              deltaToolCalls.forEach((tc, i) => {
                const idx = tc.index ?? i;
                const bucket = toolCalls.get(idx) ?? { id: '', name: '', args: '' };
                if (tc.id) {
                  bucket.id = tc.id;
                }
                if (tc.function?.name) {
                  bucket.name = tc.function.name;
                }
                if (tc.function?.arguments) {
                  bucket.args += tc.function.arguments;
                }
                toolCalls.set(idx, bucket);
              });
            }

            // 模型决定调工具：吐累积的 tool_call 事件，交给图 execute 节点执行 + 回喂。
            if (choice.finish_reason === 'tool_calls' && toolCalls.size > 0) {
              for (const bucket of toolCalls.values()) {
                if (bucket.name.length === 0) {
                  continue;
                }
                yield {
                  type: 'tool_call',
                  tool: bucket.name,
                  args: parseToolArgs(bucket.args),
                  callId: bucket.id.length > 0 ? bucket.id : `call-${bucket.name}`,
                };
              }
              toolCalls.clear();
            }
          }
        }

        if (usage) {
          emittedEnd = true;
          yield {
            type: 'message_end',
            usage: {
              inputTokens: usage.prompt_tokens ?? 0,
              outputTokens: usage.completion_tokens ?? 0,
            },
          };
        }
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

registerAdapter('openai-v1', openaiChatAdapter);

export { openaiChatAdapter };
