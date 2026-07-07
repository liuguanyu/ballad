/**
 * 契约层：大脑 → 嘴巴的唯一通信媒介。
 *
 * 铁律遵守：
 * - 脑口分离：本文件禁止 import 任何终端 / Ink / React 依赖。
 * - No AnyScript：所有对外类型均由 Zod schema 经 z.infer 推导，单一事实来源。
 * - 职责单一：本文件只定义"数据形状"，不含任何行为逻辑。
 */
import { z } from 'zod';

/** 会话中一条消息的角色。 */
export const RoleSchema = z.enum(['user', 'assistant', 'system']);
export type Role = z.infer<typeof RoleSchema>;

/**
 * 大脑吐给外界的标准结构化事件。
 * 表现层（嘴巴）只认这些事件，不关心大脑内部如何产生它们。
 */
export const AgentEventSchema = z.discriminatedUnion('type', [
  /** 一次助手回复的开始，标记后续 token 归属同一条消息。 */
  z.object({
    type: z.literal('message_start'),
    role: RoleSchema,
  }),
  /**
   * 大脑正在推理、尚未吐出正文（reasoning / thinking 阶段）。
   * 表现层据此显示"思考中"微光提示；收到第一个 token 即结束思考态。
   * 独立于正文的语义通道——对齐真实模型的 thinking/reasoning 分离。
   * text 字段承载实际思考文本（可选，向后兼容），TUI 可折叠展示。
   */
  z.object({
    type: z.literal('thinking'),
    label: z.string().optional(),
    text: z.string().optional(),
  }),
  /** 流式思考 / 正文 token（高帧率吐字）。 */
  z.object({
    type: z.literal('token'),
    text: z.string(),
  }),
  /** 代码块的流式片段（预留给 Phase 2 的结构化代码输出）。 */
  z.object({
    type: z.literal('code_stream'),
    language: z.string(),
    text: z.string(),
  }),
  /**
   * 工具调用：模型决定调某工具（Phase 2b）。
   * args 是经工具 Zod schema 校验后的参数（execute 节点调用前校验）。
   * callId 用于配对后续的 tool_result（自愈时模型可见对应错误）。
   */
  z.object({
    type: z.literal('tool_call'),
    tool: z.string(),
    args: z.record(z.string(), z.unknown()),
    callId: z.string(),
  }),
  /**
   * 工具结果：执行完的摘要（Phase 2b）。
   * ok=false 时 summary 是错误信息，回喂模型触发 Self-correction。
   * 不带完整 diff——2c 加 diff 视图时可扩可选字段（如 diff?: string），不破坏契约。
   */
  z.object({
    type: z.literal('tool_result'),
    tool: z.string(),
    callId: z.string(),
    ok: z.boolean(),
    summary: z.string(),
  }),
  /** 一次助手回复结束，可携带本轮 token 用量。 */
  z.object({
    type: z.literal('message_end'),
    usage: z
      .object({
        inputTokens: z.number().int().nonnegative(),
        outputTokens: z.number().int().nonnegative(),
      })
      .optional(),
  }),
  /** 错误事件：解析失败、API 报错等，交由表现层高亮展示。 */
  z.object({
    type: z.literal('error'),
    message: z.string(),
  }),
]);
export type AgentEvent = z.infer<typeof AgentEventSchema>;

/** 会话历史中的一条完整消息（用于渲染滚动区与历史回放）。 */
export const ChatMessageSchema = z.object({
  role: RoleSchema,
  content: z.string(),
});
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

/**
 * 大脑的抽象接口：给定历史消息，异步流式产出标准事件。
 * 表现层依赖此抽象，而非任何具体实现（低耦合）。
 */
export type Brain = (
  history: readonly ChatMessage[],
) => AsyncGenerator<AgentEvent, void, void>;
