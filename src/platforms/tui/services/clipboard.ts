/**
 * 剪贴板服务（平台能力，走 Bun.spawn 调系统 CLI）。
 *
 * 铁律遵守：
 * - 脑口分离：本文件属 platforms/tui（嘴巴），调系统桥接；core 永不 import 它。
 * - 职责单一：纯逻辑（命令解析 / 标记构造）与副作用（spawn / 写盘）分离，
 *   副作用经注入式 runner，使纯逻辑可脱终端确定性单测。
 * - No AnyScript：全部显式类型。
 *
 * 见 specs/tui-clipboard.spec.md（REQ-CLIP-1..5）。
 */

/** 支持的平台（其余走降级：empty）。 */
export type ClipPlatform = 'darwin' | 'linux';

/** 一条系统命令：可执行名 + 参数。 */
export interface ClipCommand {
  readonly cmd: string;
  readonly args: readonly string[];
}

/** 某平台读文本 / 读图片的命令对。 */
export interface ClipCommands {
  readonly text: ClipCommand;
  readonly image: ClipCommand;
}

/** 读取结果判别联合（REQ-CLIP-4）。 */
export type ClipboardResult =
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'image'; readonly marker: string; readonly path: string }
  | { readonly kind: 'empty' };

/** 图片临时目录（相对 cwd）；.agent/ 已在 .gitignore。 */
export const CLIP_TEMP_DIR = '.agent/temp';

/**
 * 纯逻辑：按平台解析读剪贴板的系统命令（REQ-CLIP-1）。
 * 不支持的平台返回 null，上层据此降级为 empty。
 */
export function resolveCommands(platform: string): ClipCommands | null {
  if (platform === 'darwin') {
    return {
      text: { cmd: 'pbpaste', args: [] },
      image: { cmd: 'pngpaste', args: ['-'] },
    };
  }
  if (platform === 'linux') {
    return {
      text: { cmd: 'xclip', args: ['-selection', 'clipboard', '-o'] },
      image: { cmd: 'xclip', args: ['-selection', 'clipboard', '-t', 'image/png', '-o'] },
    };
  }
  return null;
}

/** 纯逻辑：图片标记文本（REQ-CLIP-3）。 */
export function buildImageMarker(seq: number): string {
  return `[Image: clip_${seq}.png]`;
}

/** 纯逻辑：图片临时文件路径。 */
export function buildImagePath(seq: number): string {
  return `${CLIP_TEMP_DIR}/clip_${seq}.png`;
}

/**
 * 副作用运行器的抽象：跑一条命令，返回其 stdout 字节 + 退出码。
 * 生产实现用 Bun.spawn；测试注入假实现。
 */
export interface ClipRunner {
  run(command: ClipCommand): Promise<{ readonly stdout: Uint8Array; readonly code: number }>;
}

/** 写图片字节到临时文件的抽象；生产用 Bun.write，测试注入假实现。 */
export interface ImageWriter {
  write(path: string, bytes: Uint8Array): Promise<void>;
}

/** readClipboard 的依赖注入项。 */
export interface ClipboardDeps {
  readonly platform: string;
  readonly runner: ClipRunner;
  readonly writer: ImageWriter;
  /** 图片序号来源（避免纯函数外的随机；测试可固定）。 */
  nextSeq(): number;
}

/**
 * 读剪贴板：图片优先、文本次之、都无则 empty（REQ-CLIP-4）。
 * 纯逻辑（命令解析 / 标记）已抽离；本函数只做编排 + 依赖注入的副作用。
 */
export async function readClipboard(deps: ClipboardDeps): Promise<ClipboardResult> {
  const commands = resolveCommands(deps.platform);
  if (!commands) {
    return { kind: 'empty' };
  }

  // 先试图片（更具体）。
  try {
    const img = await deps.runner.run(commands.image);
    if (img.code === 0 && img.stdout.length > 0) {
      const seq = deps.nextSeq();
      const path = buildImagePath(seq);
      await deps.writer.write(path, img.stdout);
      return { kind: 'image', marker: buildImageMarker(seq), path };
    }
  } catch {
    // 图片 CLI 缺失 / 失败：继续试文本。
  }

  // 再试文本。
  try {
    const txt = await deps.runner.run(commands.text);
    if (txt.code === 0 && txt.stdout.length > 0) {
      const text = new TextDecoder().decode(txt.stdout);
      if (text.length > 0) {
        return { kind: 'text', text };
      }
    }
  } catch {
    // 文本 CLI 缺失 / 失败：降级 empty。
  }

  return { kind: 'empty' };
}

/**
 * 生产依赖工厂：用 Bun.spawn 跑命令、Bun.write 写盘、process.platform 选平台。
 * 与纯逻辑分离，测试永远走注入的假依赖，不碰真实系统。
 */
export function createClipboardDeps(): ClipboardDeps {
  let seq = 0;
  return {
    platform: process.platform,
    runner: {
      async run(command: ClipCommand) {
        const proc = Bun.spawn([command.cmd, ...command.args], {
          stdout: 'pipe',
          stderr: 'ignore',
        });
        const stdout = new Uint8Array(await new Response(proc.stdout).arrayBuffer());
        const code = await proc.exited;
        return { stdout, code };
      },
    },
    writer: {
      async write(path: string, bytes: Uint8Array) {
        await Bun.write(path, bytes);
      },
    },
    nextSeq: () => (seq += 1),
  };
}
