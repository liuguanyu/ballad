/**
 * ls / grep 工具（Phase 2b）：只读查询。
 *
 * 纯只读，无权限风险。ls 列目录；grep 用 Bun 内置正则搜文件内容。
 */
import { z } from 'zod';
import { readdir, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { readFile } from 'node:fs/promises';
import type { Tool, ToolResult } from './registry.ts';

export const LsParamsSchema = z.object({
  path: z.string().min(1).default('.'),
});

export const GrepParamsSchema = z.object({
  pattern: z.string().min(1),
  path: z.string().min(1).default('.'),
});

export const lsTool: Tool = {
  name: 'ls',
  description: 'List files and directories under a local path.',
  paramsSchema: LsParamsSchema,
  jsonSchema: {
    type: 'object',
    properties: { path: { type: 'string', description: 'Directory path to list, defaults to current directory' } },
    required: [],
    additionalProperties: false,
  },
  async run(args: Record<string, unknown>): Promise<ToolResult> {
    const parsed = LsParamsSchema.safeParse(args);
    if (!parsed.success) {
      return { ok: false, summary: `参数校验失败: ${parsed.error.message}` };
    }
    const { path } = parsed.data;
    try {
      const entries = await readdir(path);
      const lines: string[] = [];
      for (const e of entries.slice(0, 200)) {
        // 限制 200 项防爆
        const s = await stat(join(path, e)).catch(() => null);
        lines.push(s?.isDirectory() ? `${e}/` : e);
      }
      const note = entries.length > 200 ? `（共 ${entries.length} 项，仅显示前 200）` : '';
      return { ok: true, summary: `ls ${path}：${entries.length} 项${note}\n${lines.join('\n')}` };
    } catch (err) {
      return {
        ok: false,
        summary: `ls ${path} 失败: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  },
};

export const grepTool: Tool = {
  name: 'grep',
  description: 'Search direct child files under a local directory with a regular expression.',
  paramsSchema: GrepParamsSchema,
  jsonSchema: {
    type: 'object',
    properties: {
      pattern: { type: 'string', description: 'Regular expression to search for' },
      path: { type: 'string', description: 'Directory path to search, defaults to current directory' },
    },
    required: ['pattern'],
    additionalProperties: false,
  },
  async run(args: Record<string, unknown>): Promise<ToolResult> {
    const parsed = GrepParamsSchema.safeParse(args);
    if (!parsed.success) {
      return { ok: false, summary: `参数校验失败: ${parsed.error.message}` };
    }
    const { pattern, path } = parsed.data;
    try {
      const re = new RegExp(pattern);
      const entries = await readdir(path, { withFileTypes: true });
      const matches: string[] = [];
      for (const e of entries) {
        if (!e.isFile()) continue;
        const content = await readFile(join(path, e.name), 'utf8').catch(() => '');
        for (const line of content.split('\n')) {
          if (re.test(line)) {
            matches.push(`${e.name}: ${line}`);
            if (matches.length >= 100) break; // 限制 100 行防爆
          }
        }
        if (matches.length >= 100) break;
      }
      const note = matches.length >= 100 ? '（仅显示前 100 行）' : '';
      return { ok: true, summary: `grep ${pattern} in ${path}：${matches.length} 行${note}\n${matches.join('\n')}` };
    } catch (err) {
      return {
        ok: false,
        summary: `grep ${path} 失败: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  },
};
