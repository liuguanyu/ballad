/**
 * read_file 工具（Phase 2b）：读取本地文件内容。
 *
 * 副作用集中在此（铁律：core 内副作用只在 tool 实现 + 图 execute 节点）。
 * 大文件截断防 token 爆炸——摘要报告实际行数与是否截断。
 */
import { z } from 'zod';
import { readFile } from 'node:fs/promises';
import type { Tool, ToolResult } from './registry.ts';

const MAX_BYTES = 32 * 1024; // 32KB 截断，防 token 爆炸

export const ReadFileParamsSchema = z.object({
  path: z.string().min(1),
});

export const readTool: Tool = {
  name: 'read_file',
  description: 'Read a local text file by path and return its contents, truncated for large files.',
  paramsSchema: ReadFileParamsSchema,
  jsonSchema: {
    type: 'object',
    properties: { path: { type: 'string', description: 'File path to read' } },
    required: ['path'],
    additionalProperties: false,
  },
  async run(args: Record<string, unknown>): Promise<ToolResult> {
    const parsed = ReadFileParamsSchema.safeParse(args);
    if (!parsed.success) {
      return { ok: false, summary: `参数校验失败: ${parsed.error.message}` };
    }
    const { path } = parsed.data;
    try {
      const buf = await readFile(path);
      const truncated = buf.length > MAX_BYTES;
      const text = truncated ? buf.subarray(0, MAX_BYTES).toString('utf8') : buf.toString('utf8');
      const lineCount = text.split('\n').length;
      const note = truncated ? `（已截断至 ${MAX_BYTES} 字节）` : '';
      return {
        ok: true,
        summary: `读取 ${path}：${lineCount} 行${note}\n\`\`\`\n${text}\n\`\`\``,
      };
    } catch (err) {
      return {
        ok: false,
        summary: `读取 ${path} 失败: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  },
};
