/**
 * 工具注册表与 Tool 接口（Phase 2b）。
 *
 * 职责单一（铁律 2）：本文件只定义"工具抽象 + 注册表"，不含具体工具实现。
 * 工具实现各自独立成文件（read/write/bash/query）。
 *
 * No AnyScript（铁律 1）：工具参数经 Zod schema 校验（Self-correction 的前提）；
 * ToolResult 形状与契约的 tool_result 对齐（summary 不带完整 diff，2c 可扩）。
 *
 * 脑口分离（铁律 0）：本文件不 import 任何终端 / Ink / React，只有 Zod 与类型。
 */
import { z } from 'zod';

export type JsonSchema = {
  readonly type: 'object';
  readonly properties: Record<string, { readonly type: 'string'; readonly description?: string }>;
  readonly required?: readonly string[];
  readonly additionalProperties: false;
};

/** 工具执行结果（对齐契约 tool_result 的 ok/summary，callId/tool 由图节点填充）。 */
export interface ToolResult {
  readonly ok: boolean;
  readonly summary: string;
}

/**
 * 工具抽象：name 唯一标识；paramsSchema 校验参数；run 执行并返回结果。
 * execute 节点调用前先用 paramsSchema 校验 args，失败走 Self-correction（不抛错）。
 */
export interface Tool {
  readonly name: string;
  readonly description: string;
  readonly paramsSchema: z.ZodType;
  readonly jsonSchema: JsonSchema;
  readonly run: (args: Record<string, unknown>) => Promise<ToolResult>;
}

/** 工具注册表：name → Tool。图 execute 节点按 name 查找。 */
export class ToolRegistry {
  private readonly tools = new Map<string, Tool>();

  register(tool: Tool): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`ToolRegistry: duplicate tool "${tool.name}"`);
    }
    this.tools.set(tool.name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  list(): readonly string[] {
    return [...this.tools.keys()];
  }

  entries(): readonly Tool[] {
    return [...this.tools.values()];
  }
}
