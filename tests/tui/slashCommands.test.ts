/**
 * 单元测试 · slashCommands（确定性，脱终端）。
 * 覆盖 REQ-CMD-1（命令模式判定）与注册表内容。
 */
import { test, expect, describe } from 'bun:test';
import {
  SLASH_COMMANDS,
  isCommandQuery,
} from '../../src/platforms/tui/logic/slashCommands.ts';

describe('isCommandQuery · REQ-CMD-1', () => {
  test("'/' 与 '/exit' 是命令模式", () => {
    expect(isCommandQuery('/')).toBe(true);
    expect(isCommandQuery('/exit')).toBe(true);
  });

  test('非斜杠开头不是命令模式', () => {
    expect(isCommandQuery('exit')).toBe(false);
    expect(isCommandQuery('')).toBe(false);
    expect(isCommandQuery('  /exit')).toBe(false);
  });

  test('含空格/换行退出命令模式', () => {
    expect(isCommandQuery('/e x')).toBe(false);
    expect(isCommandQuery('/exit ')).toBe(false);
    expect(isCommandQuery('/a\n')).toBe(false);
  });
});

describe('SLASH_COMMANDS 注册表', () => {
  test('含 /exit 且形状完整', () => {
    const exit = SLASH_COMMANDS.find((c) => c.value === 'exit');
    expect(exit).toBeDefined();
    expect(exit?.label).toBe('/exit');
    expect(exit?.hint.length).toBeGreaterThan(0);
  });

  test('含 /model 且形状完整', () => {
    const model = SLASH_COMMANDS.find((c) => c.value === 'model');
    expect(model).toBeDefined();
    expect(model?.label).toBe('/model');
    expect(model?.hint.length).toBeGreaterThan(0);
  });

  test('label 均以 / 开头', () => {
    for (const c of SLASH_COMMANDS) {
      expect(c.label.startsWith('/')).toBe(true);
    }
  });
});
