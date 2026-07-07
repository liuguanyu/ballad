/**
 * 图节点实现（Phase 2b）。
 *
 * 职责单一（铁律 2）：本文件只实现节点逻辑，不含图构建。
 *
 * 节点设计原则（见 plan）：
 * - reason 节点：调模型，流式吐 token/thinking 走旁路（getWriter）
 * - execute 节点：调工具，吐 tool_call/tool_result 走主流（状态更新）
 *
 * No AnyScript（铁律 1）：所有类型经 Zod schema 推导。
 */
import { getWriter } from '@langchain/langgraph';
import type { Brain, ChatMessage, AgentEvent } from '../contract.ts';
import type { ToolRegistry } from '../tools/registry.ts';
import type { GraphStateType, PendingToolCall } from './state.ts';

/**
 * 默认系统提示：告诉模型它运行在本地项目里、拥有本地工具，
 * 遇到"检查项目/读代码/看状态"类请求必须先调用工具，不能凭空回答或声称无法访问本地。
 * 让真实模型走 tool-call 闭环，而不是当普通聊天模型。
 */
export const DEFAULT_SYSTEM_PROMPT =
  'You are a coding agent running locally inside the user\'s current project directory. ' +
  'You have real tools: read_file, write_file, edit_file, ls, grep, run_shell (read-only allowlist). ' +
  'When the user asks you to inspect, check, review, or explain the project, its status, files, or tests, ' +
  'you MUST call the appropriate tools first to gather facts. ' +
  'Never claim you cannot access the local machine or repository — you can, through these tools. ' +
  'Prefer ls/grep/read_file to explore, and run_shell for read-only commands like "git status". ' +
  'Reply in the user\'s language.';

/**
 * reason 节点：调模型适配器，流式吐 token/thinking 走旁路。
 *
 * 模型返回 tool_call 时，存入 pendingToolCall 状态，由 route 条件边决定下一步。
 * 模型无 tool_call 时，pendingToolCall 为 null，route 走 END。
 */
export function createReasonNode(brain: Brain, systemPrompt: string = DEFAULT_SYSTEM_PROMPT) {
  return async (state: GraphStateType): Promise<Partial<GraphStateType>> => {
    const writer = getWriter();
    // 首轮在历史开头注入系统提示（若尚无 system 消息），让模型知道自己有本地工具。
    const hasSystem = state.messages.some((m) => m.role === 'system');
    const history: ChatMessage[] = hasSystem
      ? state.messages
      : [{ role: 'system', content: systemPrompt }, ...state.messages];

    let pendingToolCall: PendingToolCall | null = null;
    let assistantContent = '';

    // 调模型，流式消费事件
    for await (const event of brain(history)) {
      // token/thinking 走旁路（custom channel），不进状态
      if (event.type === 'token' || event.type === 'thinking') {
        writer?.(event);
        if (event.type === 'token') {
          assistantContent += event.text;
        }
      }
      // tool_call 走主流（状态更新），进检查点
      else if (event.type === 'tool_call') {
        pendingToolCall = {
          callId: event.callId,
          tool: event.tool,
          args: event.args,
        };
        writer?.(event); // 旁路也吐，让 TUI 实时显示
      }
      // 其他事件（message_start/message_end/error）旁路吐
      else {
        writer?.(event);
      }
    }

    // 把助手消息追加到状态（主流，进检查点）。
    // 模型只发 tool_call、无正文时 assistantContent 为空——记录调用意图占位，
    // 既保留多轮上下文，又避免写入空 assistant 消息（部分协议拒绝空内容）。
    const assistantMessage: ChatMessage = {
      role: 'assistant',
      content:
        assistantContent.length > 0
          ? assistantContent
          : pendingToolCall
            ? `[调用工具: ${pendingToolCall.tool}]`
            : '',
    };

    return {
      messages: [assistantMessage],
      pendingToolCall,
      step: 1, // 步数 +1
    };
  };
}

/**
 * execute 节点：调工具，吐 tool_call/tool_result 走主流。
 *
 * 工具参数 Zod 校验失败时，不抛错，吐 tool_result(ok=false) 回喂模型（Self-correction）。
 */
export function createExecuteNode(tools: ToolRegistry) {
  return async (state: GraphStateType): Promise<Partial<GraphStateType>> => {
    const writer = getWriter();
    const pending = state.pendingToolCall;

    if (!pending) {
      // 不应该走到这里（route 应该拦截），防御性返回
      return { pendingToolCall: null };
    }

    const tool = tools.get(pending.tool);
    if (!tool) {
      // 工具不存在，吐错误结果
      const errorResult: AgentEvent = {
        type: 'tool_result',
        tool: pending.tool,
        callId: pending.callId,
        ok: false,
        summary: `工具 "${pending.tool}" 不存在`,
      };
      writer?.(errorResult);

      const errorMessage: ChatMessage = {
        role: 'user',
        content: `[工具错误] ${errorResult.summary}`,
      };

      return {
        messages: [errorMessage],
        pendingToolCall: null, // 清空，让模型看到错误后重试
      };
    }

    // 调工具
    const result = await tool.run(pending.args);

    // 吐 tool_result 事件（旁路 + 主流）
    const toolResultEvent: AgentEvent = {
      type: 'tool_result',
      tool: pending.tool,
      callId: pending.callId,
      ok: result.ok,
      summary: result.summary,
    };
    writer?.(toolResultEvent);

    // 把工具结果喂回模型（主流，进检查点）。用 user 角色回喂，
    // 使 reason 节点的系统提示判定只认真正的 system 消息、多轮不被工具结果冲掉。
    const toolMessage: ChatMessage = {
      role: 'user',
      content: `[工具结果: ${pending.tool}]\n${result.summary}`,
    };

    return {
      messages: [toolMessage],
      pendingToolCall: null, // 清空，让模型看到结果后决定下一步
    };
  };
}
