/**
 * 工具层测试（Phase 2b）。
 *
 * 覆盖 REQ-TOOL-1（参数 Zod 校验）/ REQ-TOOL-2（四工具 + bash 权限边界）。
 * 用临时目录测 read/write/query；bash 测白名单/危险/元字符/超时。
 */
import { test, expect, describe, beforeEach, afterEach } from 'bun:test';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readTool } from '../../../src/core/tools/read.ts';
import { writeTool, editTool } from '../../../src/core/tools/write.ts';
import { lsTool, grepTool } from '../../../src/core/tools/query.ts';
import { bashTool } from '../../../src/core/tools/bash.ts';
import { ToolRegistry } from '../../../src/core/tools/registry.ts';

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'ballad-tool-'));
});
afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe('REQ-TOOL-1 · 参数 Zod 校验失败走 ok=false（不抛错）', () => {
  test('read_file 缺 path', async () => {
    const r = await readTool.run({});
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('参数校验失败');
  });

  test('write_file 缺 content', async () => {
    const r = await writeTool.run({ path: 'x' });
    expect(r.ok).toBe(false);
  });
});

describe('REQ-TOOL-2 · read_file', () => {
  test('读取已存在文件', async () => {
    const p = join(dir, 'a.txt');
    await writeFile(p, 'line1\nline2\n');
    const r = await readTool.run({ path: p });
    expect(r.ok).toBe(true);
    expect(r.summary).toContain('line1');
    expect(r.summary).toContain('3 行'); // 末尾 \n 产生 3 段
  });

  test('读取不存在文件 ok=false', async () => {
    const r = await readTool.run({ path: join(dir, 'nope.txt') });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('失败');
  });
});

describe('REQ-TOOL-2 · write_file / edit_file', () => {
  test('write_file 创建文件', async () => {
    const p = join(dir, 'sub', 'b.txt');
    const r = await writeTool.run({ path: p, content: 'hello' });
    expect(r.ok).toBe(true);
    expect(r.summary).toContain('写入');
  });

  test('edit_file 唯一替换成功', async () => {
    const p = join(dir, 'c.txt');
    await writeFile(p, 'foo bar baz');
    const r = await editTool.run({ path: p, oldString: 'bar', newString: 'QUX' });
    expect(r.ok).toBe(true);
    expect(r.summary).toContain('替换 1 处');
  });

  test('edit_file oldString 不存在失败', async () => {
    const p = join(dir, 'd.txt');
    await writeFile(p, 'foo');
    const r = await editTool.run({ path: p, oldString: 'nope', newString: 'x' });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('未找到');
  });

  test('edit_file 多处匹配失败（需唯一）', async () => {
    const p = join(dir, 'e.txt');
    await writeFile(p, 'a a a');
    const r = await editTool.run({ path: p, oldString: 'a', newString: 'b' });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('匹配');
  });
});

describe('REQ-TOOL-2 · ls / grep', () => {
  beforeEach(async () => {
    await writeFile(join(dir, 'x.ts'), 'export const A = 1;\n');
    await writeFile(join(dir, 'y.ts'), 'const B = 2;\n');
    await mkdir(join(dir, 'sub'));
  });

  test('ls 列目录', async () => {
    const r = await lsTool.run({ path: dir });
    expect(r.ok).toBe(true);
    expect(r.summary).toContain('x.ts');
    expect(r.summary).toContain('sub/');
  });

  test('grep 搜内容', async () => {
    const r = await grepTool.run({ pattern: 'export', path: dir });
    expect(r.ok).toBe(true);
    expect(r.summary).toContain('x.ts');
    expect(r.summary).not.toContain('y.ts');
  });
});

describe('REQ-TOOL-2 · run_shell 权限边界', () => {
  test('白名单只读命令放行', async () => {
    const r = await bashTool.run({ cmd: `ls ${dir}` });
    expect(r.ok).toBe(true);
  });

  test('危险命令 rm 被拒', async () => {
    const r = await bashTool.run({ cmd: 'rm -rf /tmp/x' });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('危险命令');
  });

  test('非白名单命令被拒', async () => {
    const r = await bashTool.run({ cmd: 'foo bar' });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('白名单');
  });

  test('shell 元字符注入被拒', async () => {
    const r = await bashTool.run({ cmd: 'ls; rm x' });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('元字符');
  });

  test('重定向被拒', async () => {
    const r = await bashTool.run({ cmd: 'ls > x' });
    expect(r.ok).toBe(false);
    expect(r.summary).toContain('元字符');
  });
});

describe('ToolRegistry', () => {
  test('注册 + 查找 + 去重', () => {
    const reg = new ToolRegistry();
    reg.register(readTool);
    expect(reg.get('read_file')).toBe(readTool);
    expect(reg.list()).toContain('read_file');
    expect(() => reg.register(readTool)).toThrow(/duplicate/);
  });
});
