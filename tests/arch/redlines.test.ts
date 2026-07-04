/**
 * 架构红线守护测试。
 *
 * 让工程铁律由 CI 强制执行，而非靠自觉（见项目根 AGENTS.md）：
 * - 铁律 0 脑口分离：core/ 不得依赖任何终端 / Ink / React 渲染。
 * - 铁律 3 单向依赖：platforms/ 可依赖 core/，但 core/ 不得反向依赖 platforms/。
 * - 铁律 1 No AnyScript：源码不得出现 any / as any / @ts-ignore。
 *
 * 用静态扫描源码文本实现，零运行时依赖。任何一条被打破都会让本测试变红。
 */
import { test, expect, describe } from 'bun:test';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const SRC = join(import.meta.dir, '..', '..', 'src');

/** 递归收集某目录下的所有 .ts/.tsx 源文件绝对路径。 */
function collectSources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...collectSources(full));
    } else if (full.endsWith('.ts') || full.endsWith('.tsx')) {
      out.push(full);
    }
  }
  return out;
}

/** 提取一个源文件里所有 import 的模块说明符。 */
function importSpecifiers(source: string): string[] {
  const specs: string[] = [];
  const re = /(?:import|export)[^'"]*?from\s*['"]([^'"]+)['"]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    if (m[1]) {
      specs.push(m[1]);
    }
  }
  return specs;
}

const CORE_DIR = join(SRC, 'core');
const PLATFORMS_DIR = join(SRC, 'platforms');

/** core 层禁止依赖的渲染 / 终端相关模块。 */
const FORBIDDEN_IN_CORE = ['ink', 'react', 'chalk', 'ink-testing-library'];

describe('铁律 0 · 脑口分离：core 不碰终端', () => {
  const coreFiles = collectSources(CORE_DIR);

  test('core 目录存在且有源文件', () => {
    expect(coreFiles.length).toBeGreaterThan(0);
  });

  for (const file of coreFiles) {
    test(`core 文件不 import 终端依赖: ${file.replace(SRC, 'src')}`, () => {
      const specs = importSpecifiers(readFileSync(file, 'utf8'));
      for (const spec of specs) {
        const base = spec.replace(/^node:/, '').split('/')[0] ?? '';
        expect(FORBIDDEN_IN_CORE).not.toContain(base);
      }
    });
  }
});

describe('铁律 3 · 单向依赖：core 不反向依赖 platforms', () => {
  const coreFiles = collectSources(CORE_DIR);

  for (const file of coreFiles) {
    test(`core 文件不 import platforms: ${file.replace(SRC, 'src')}`, () => {
      const specs = importSpecifiers(readFileSync(file, 'utf8'));
      const leaks = specs.filter((s) => s.includes('platforms'));
      expect(leaks).toEqual([]);
    });
  }
});

describe('铁律 1 · No AnyScript：源码无 any / 逃逸标注', () => {
  const allFiles = [...collectSources(CORE_DIR), ...collectSources(PLATFORMS_DIR)];

  for (const file of allFiles) {
    test(`无 any / as any / @ts-ignore: ${file.replace(SRC, 'src')}`, () => {
      const source = readFileSync(file, 'utf8');
      // 去掉行注释与块注释，避免注释里的词误伤
      const code = source
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/.*$/gm, '');
      // 独立的 any 类型标注（: any / <any> / any[] / as any）
      expect(code).not.toMatch(/:\s*any\b/);
      expect(code).not.toMatch(/\bas\s+any\b/);
      expect(code).not.toMatch(/<any>/);
      expect(code).not.toMatch(/@ts-ignore/);
      expect(code).not.toMatch(/@ts-expect-error/);
    });
  }
});
