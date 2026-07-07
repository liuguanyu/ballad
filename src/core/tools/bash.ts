/**
 * run_shell 工具（Phase 2b）：执行 shell 命令，带权限边界。
 *
 * 安全重点（铁律：副作用集中在此，但必须有边界）：
 * - 白名单：只允许已知只读命令（ls/cat/git/grep/find/head/tail/wc 等）。
 * - 禁 shell 元字符：; & | $ ` > < \n 等，只支持"单命令+参数"形态，防注入。
 * - 超时：Bun.spawn + setTimeout 兜底，超时杀进程。
 * - 危险命令（rm/mv/cp/curl/wget/chmod 等）默认拒绝。
 */
import { z } from 'zod';
import { spawn } from 'node:child_process';
import type { Tool, ToolResult } from './registry.ts';

const RunShellParamsSchema = z.object({
  cmd: z.string().min(1),
});

/** 只读命令白名单（首 token 匹配）。 */
const ALLOWED = new Set([
  'ls', 'cat', 'head', 'tail', 'wc', 'grep', 'find', 'git', 'pwd', 'echo',
  'which', 'file', 'stat', 'diff', 'sort', 'uniq',
]);

/** 危险命令黑名单（双保险，即便白名单放行也拒）。 */
const DANGEROUS = new Set([
  'rm', 'mv', 'cp', 'mkdir', 'rmdir', 'chmod', 'chown', 'curl', 'wget',
  'npm', 'yarn', 'pnpm', 'bun', 'node', 'python', 'sh', 'bash', 'zsh',
  'kill', 'sudo', 'eval', 'exec',
]);

/** 禁止的 shell 元字符（防注入：; & | $ ` > < 换行 等）。 */
const FORBIDDEN_CHARS = /[#;&|$\`<>\n\r\\]/;

const TIMEOUT_MS = 10_000;

export const bashTool: Tool = {
  name: 'run_shell',
  description: 'Run a safe read-only shell command from an allowlist, such as git status, ls, grep, or pwd.',
  paramsSchema: RunShellParamsSchema,
  jsonSchema: {
    type: 'object',
    properties: { cmd: { type: 'string', description: 'Single read-only shell command without shell metacharacters' } },
    required: ['cmd'],
    additionalProperties: false,
  },
  async run(args: Record<string, unknown>): Promise<ToolResult> {
    const parsed = RunShellParamsSchema.safeParse(args);
    if (!parsed.success) {
      return { ok: false, summary: `参数校验失败: ${parsed.error.message}` };
    }
    const { cmd } = parsed.data;

    if (FORBIDDEN_CHARS.test(cmd)) {
      return { ok: false, summary: `拒绝：含禁止的 shell 元字符` };
    }
    const tokens = cmd.trim().split(/\s+/);
    const head = tokens[0] ?? '';
    if (DANGEROUS.has(head)) {
      return { ok: false, summary: `拒绝：危险命令 "${head}"` };
    }
    if (!ALLOWED.has(head)) {
      return { ok: false, summary: `拒绝：命令 "${head}" 不在白名单` };
    }

    return new Promise<ToolResult>((resolve) => {
      const child = spawn(head, tokens.slice(1), { timeout: TIMEOUT_MS });
      let stdout = '';
      let stderr = '';
      let killed = false;
      const timer = setTimeout(() => {
        killed = true;
        child.kill('SIGKILL');
      }, TIMEOUT_MS);

      child.stdout.on('data', (d) => {
        stdout += d.toString();
      });
      child.stderr.on('data', (d) => {
        stderr += d.toString();
      });
      child.on('error', (err) => {
        clearTimeout(timer);
        resolve({ ok: false, summary: `执行错误: ${err.message}` });
      });
      child.on('close', (code) => {
        clearTimeout(timer);
        if (killed) {
          resolve({ ok: false, summary: `超时（${TIMEOUT_MS}ms）被杀` });
          return;
        }
        const out = (stdout + (stderr ? `\n[stderr]\n${stderr}` : '')).slice(0, 4000);
        const ok = code === 0;
        resolve({
          ok,
          summary: `${cmd} → exit ${code}\n${out}`,
        });
      });
    });
  },
};
