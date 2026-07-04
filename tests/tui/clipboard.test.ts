/**
 * 单元测试 · clipboard 服务（确定性，注入式，脱系统 CLI）。
 * 覆盖 specs/tui-clipboard.spec.md：REQ-CLIP-1/3/4。
 */
import { test, expect, describe } from 'bun:test';
import {
  buildImageMarker,
  buildImagePath,
  readClipboard,
  resolveCommands,
  type ClipCommand,
  type ClipboardDeps,
} from '../../src/platforms/tui/services/clipboard.ts';

describe('resolveCommands · REQ-CLIP-1 平台分派', () => {
  test('darwin: pbpaste / pngpaste', () => {
    const c = resolveCommands('darwin');
    expect(c?.text.cmd).toBe('pbpaste');
    expect(c?.image.cmd).toBe('pngpaste');
  });

  test('linux: xclip 文本/图片参数不同', () => {
    const c = resolveCommands('linux');
    expect(c?.text.cmd).toBe('xclip');
    expect(c?.image.args).toContain('image/png');
  });

  test('未知平台返回 null（上层降级 empty）', () => {
    expect(resolveCommands('win32')).toBeNull();
  });
});

describe('纯逻辑标记 · REQ-CLIP-3', () => {
  test('buildImageMarker', () => {
    expect(buildImageMarker(7)).toBe('[Image: clip_7.png]');
  });
  test('buildImagePath 落在 .agent/temp', () => {
    expect(buildImagePath(7)).toBe('.agent/temp/clip_7.png');
  });
});

/** 造一个假 runner：按命令名返回预设 stdout/code。 */
function fakeDeps(
  overrides: {
    image?: { stdout: Uint8Array; code: number };
    text?: { stdout: Uint8Array; code: number };
    platform?: string;
  },
  written: Array<{ path: string; bytes: Uint8Array }> = [],
): ClipboardDeps {
  return {
    platform: overrides.platform ?? 'darwin',
    runner: {
      async run(command: ClipCommand) {
        if (command.cmd === 'pngpaste') {
          return overrides.image ?? { stdout: new Uint8Array(), code: 1 };
        }
        return overrides.text ?? { stdout: new Uint8Array(), code: 1 };
      },
    },
    writer: {
      async write(path: string, bytes: Uint8Array) {
        written.push({ path, bytes });
      },
    },
    nextSeq: () => 42,
  };
}

describe('readClipboard · REQ-CLIP-4 判别顺序', () => {
  test('有图片 → image 优先，且写盘', async () => {
    const written: Array<{ path: string; bytes: Uint8Array }> = [];
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47]); // PNG 魔数
    const r = await readClipboard(
      fakeDeps({ image: { stdout: png, code: 0 } }, written),
    );
    expect(r.kind).toBe('image');
    if (r.kind === 'image') {
      expect(r.marker).toBe('[Image: clip_42.png]');
      expect(r.path).toBe('.agent/temp/clip_42.png');
    }
    expect(written).toHaveLength(1);
    expect(written[0]?.bytes).toEqual(png);
  });

  test('无图片有文本 → text', async () => {
    const enc = new TextEncoder().encode('hello clipboard');
    const r = await readClipboard(
      fakeDeps({ image: { stdout: new Uint8Array(), code: 1 }, text: { stdout: enc, code: 0 } }),
    );
    expect(r.kind).toBe('text');
    if (r.kind === 'text') {
      expect(r.text).toBe('hello clipboard');
    }
  });

  test('都为空 → empty', async () => {
    const r = await readClipboard(fakeDeps({}));
    expect(r.kind).toBe('empty');
  });

  test('不支持的平台 → empty', async () => {
    const r = await readClipboard(fakeDeps({ platform: 'win32' }));
    expect(r.kind).toBe('empty');
  });
});
