/**
 * write_file / edit_file 工具（Phase 2b）：写文件 / 局部替换。
 *
 * 副作用集中在此。edit_file 用 oldString 精确定位替换为 newString（对齐主流 coding agent），
 * oldString 不唯一或不存在时返回失败（喂回模型触发自愈）。
 */
import { z } from 'zod';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { Tool, ToolResult } from './registry.ts';

export const WriteFileParamsSchema = z.object({
  path: z.string().min(1),
  content: z.string(),
});

export const EditFileParamsSchema = z.object({
  path: z.string().min(1),
  oldString: z.string().min(1),
  newString: z.string(),
});

export const writeTool: Tool = {
  name: 'write_file',
  description: 'Write UTF-8 content to a local file, creating parent directories when needed.',
  paramsSchema: WriteFileParamsSchema,
  jsonSchema: {
    type: 'object',
    properties: {
      path: { type: 'string', description: 'File path to write' },
      content: { type: 'string', description: 'Full file content' },
    },
    required: ['path', 'content'],
    additionalProperties: false,
  },
  async run(args: Record<string, unknown>): Promise<ToolResult> {
    const parsed = WriteFileParamsSchema.safeParse(args);
    if (!parsed.success) {
      return { ok: false, summary: `参数校验失败: ${parsed.error.message}` };
    }
    const { path, content } = parsed.data;
    try {
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, content, 'utf8');
      const lines = content.split('\n').length;
      return { ok: true, summary: `写入 ${path}：${lines} 行` };
    } catch (err) {
      return {
        ok: false,
        summary: `写入 ${path} 失败: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  },
};

export const editTool: Tool = {
  name: 'edit_file',
  description: 'Replace one exact string in a local file. The oldString must match exactly once.',
  paramsSchema: EditFileParamsSchema,
  jsonSchema: {
    type: 'object',
    properties: {
      path: { type: 'string', description: 'File path to edit' },
      oldString: { type: 'string', description: 'Exact existing text to replace' },
      newString: { type: 'string', description: 'Replacement text' },
    },
    required: ['path', 'oldString', 'newString'],
    additionalProperties: false,
  },
  async run(args: Record<string, unknown>): Promise<ToolResult> {
    const parsed = EditFileParamsSchema.safeParse(args);
    if (!parsed.success) {
      return { ok: false, summary: `参数校验失败: ${parsed.error.message}` };
    }
    const { path, oldString, newString } = parsed.data;
    try {
      const original = await readFile(path, 'utf8');
      const count = original.split(oldString).length - 1;
      if (count === 0) {
        return { ok: false, summary: `编辑 ${path} 失败: oldString 未找到` };
      }
      if (count > 1) {
        return { ok: false, summary: `编辑 ${path} 失败: oldString 匹配 ${count} 处，需唯一` };
      }
      const next = original.replace(oldString, newString);
      await writeFile(path, next, 'utf8');
      return { ok: true, summary: `编辑 ${path}：替换 1 处` };
    } catch (err) {
      return {
        ok: false,
        summary: `编辑 ${path} 失败: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  },
};
