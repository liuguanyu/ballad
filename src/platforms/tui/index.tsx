/**
 * TUI 入口（嘴巴中枢）。
 *
 * 职责：持有会话状态、消费大脑的 AsyncGenerator、把用户输入喂回大脑。
 * 这是本层唯一聚集副作用的地方；下层组件保持纯渲染。
 *
 * 铁律遵守：本文件只从 core 引入抽象（Brain / 事件类型），
 * 不含任何模型调用或重试逻辑——那些属于 core。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Box, useApp, useInput, useStdout } from 'ink';
import type { Brain, ChatMessage } from '../../core/contract.ts';
import { Header } from './components/Header.tsx';
import { LogViewer } from './components/LogViewer.tsx';
import { DynamicInput } from './components/DynamicInput.tsx';
import { StatusBar } from './components/StatusBar.tsx';
import { SelectMenu } from './components/SelectMenu.tsx';
import { DetailsPanel } from './components/DetailsPanel.tsx';
import { ShimmerText } from './components/ShimmerText.tsx';
import {
  filterItems,
  idleMenuState,
  moveSelection,
  type MenuState,
} from './logic/selectMenu.ts';
import { SLASH_COMMANDS, isCommandQuery } from './logic/slashCommands.ts';
import {
  createClipboardDeps,
  readClipboard,
  type ClipboardDeps,
} from './services/clipboard.ts';

interface AppProps {
  readonly brain: Brain;
  readonly cwd: string;
  /** 退出钩子（默认调用 Ink 的 useApp().exit）；测试可注入 spy 观测 /exit。 */
  readonly onExit?: () => void;
  /** 剪贴板依赖（默认走真实系统 CLI）；测试可注入假实现。 */
  readonly clipboard?: ClipboardDeps;
}

interface TermSize {
  readonly columns: number;
  readonly rows: number;
}

/**
 * 订阅终端尺寸并随 resize 更新。
 * 渲染层关注点，不进 core。回退值保证非 TTY（测试）下也有合理尺寸。
 */
function useTerminalSize(): TermSize {
  const { stdout } = useStdout();
  const [size, setSize] = useState<TermSize>({
    columns: stdout?.columns ?? 80,
    rows: stdout?.rows ?? 24,
  });

  useEffect(() => {
    if (!stdout) {
      return;
    }
    const onResize = (): void => {
      setSize({ columns: stdout.columns ?? 80, rows: stdout.rows ?? 24 });
    };
    stdout.on('resize', onResize);
    onResize();
    return () => {
      stdout.off('resize', onResize);
    };
  }, [stdout]);

  return size;
}

interface Usage {
  readonly inputTokens: number;
  readonly outputTokens: number;
}

export function App({ brain, cwd, onExit, clipboard }: AppProps): React.ReactElement {
  const { exit } = useApp();
  const { columns, rows } = useTerminalSize();
  const [messages, setMessages] = useState<readonly ChatMessage[]>([]);
  const [streaming, setStreaming] = useState<string>('');
  const [busy, setBusy] = useState<boolean>(false);
  // 思考态：大脑在推理、尚未吐正文；收到首个 token 即结束。驱动流光提示。
  const [thinking, setThinking] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage>({ inputTokens: 0, outputTokens: 0 });
  const [inputValue, setInputValue] = useState<string>('');
  const [menuState, setMenuState] = useState<MenuState>(() => idleMenuState());
  // 用户按 Esc 主动关闭菜单的意图；下一次输入变化时清除，使菜单可重新弹出。
  const [menuDismissed, setMenuDismissed] = useState<boolean>(false);
  // Ctrl+O 切换的详情面板显隐（纯渲染层状态，不干扰大脑流式）。
  const [detailsOpen, setDetailsOpen] = useState<boolean>(false);
  const historyRef = useRef<string[]>([]);

  const quit = useCallback((): void => {
    if (onExit) {
      onExit();
    } else {
      exit();
    }
  }, [onExit, exit]);

  // 命令模式与过滤：'/' 开头且有候选、且未被 Esc 主动关闭时弹菜单。
  const commandMode = isCommandQuery(inputValue);
  const filtered = commandMode ? filterItems(SLASH_COMMANDS, inputValue) : [];
  const menuOpen = commandMode && filtered.length > 0 && !menuDismissed;

  // 执行选中的命令（当前仅 /exit；加命令在此加 case）。
  const runCommand = useCallback(
    (value: string): void => {
      switch (value) {
        case 'exit':
          quit();
          break;
        default:
          break;
      }
    },
    [quit],
  );

  // 输入变化：镜像文本，复位菜单高亮，并清除"已手动关闭"意图（改动输入即可重弹）。
  const handleValueChange = useCallback((v: string): void => {
    setInputValue(v);
    setMenuState(idleMenuState());
    setMenuDismissed(false);
  }, []);

  const handleNavigate = useCallback(
    (dir: 'up' | 'down'): void => {
      setMenuState((s) => moveSelection(s, dir, filtered.length));
    },
    [filtered.length],
  );

  const handleAccept = useCallback((): void => {
    const chosen = filtered[menuState.selected];
    if (chosen) {
      runCommand(chosen.value);
    }
    setInputValue('');
    setMenuState(idleMenuState());
    setMenuDismissed(false);
  }, [filtered, menuState.selected, runCommand]);

  // Esc：主动关闭菜单（置 dismissed），保留已输入文本。
  const handleCancel = useCallback((): void => {
    setMenuDismissed(true);
    setMenuState(idleMenuState());
  }, []);

  // 剪贴板依赖：优先用注入的（测试），否则惰性创建真实系统实现（仅一次）。
  const clipboardRef = useRef<ClipboardDeps | null>(clipboard ?? null);
  const handlePaste = useCallback(async (): Promise<string> => {
    if (!clipboardRef.current) {
      clipboardRef.current = createClipboardDeps();
    }
    const result = await readClipboard(clipboardRef.current);
    if (result.kind === 'text') {
      return result.text;
    }
    if (result.kind === 'image') {
      return result.marker;
    }
    return '';
  }, []);

  // 全局快捷键：Ctrl+C 退出；Ctrl+O 切换详情面板（纯渲染，不打断大脑流式）。
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      quit();
      return;
    }
    if (key.ctrl && input === 'o') {
      setDetailsOpen((v) => !v);
    }
  });

  const handleSubmit = useCallback(
    (raw: string): void => {
      const userMsg: ChatMessage = { role: 'user', content: raw };
      historyRef.current = [...historyRef.current, raw];

      const nextHistory: ChatMessage[] = [...messages, userMsg];
      setMessages(nextHistory);
      setBusy(true);
      setStreaming('');
      setThinking(null);

      void (async (): Promise<void> => {
        let acc = '';
        try {
          for await (const event of brain(nextHistory)) {
            switch (event.type) {
              case 'thinking':
                setThinking(event.label ?? '思考中');
                break;
              case 'token':
                setThinking(null); // 首个正文 token 结束思考态
                acc += event.text;
                setStreaming(acc);
                break;
              case 'code_stream':
                setThinking(null);
                acc += event.text;
                setStreaming(acc);
                break;
              case 'message_end':
                if (event.usage) {
                  setUsage((u) => ({
                    inputTokens: u.inputTokens + event.usage!.inputTokens,
                    outputTokens: u.outputTokens + event.usage!.outputTokens,
                  }));
                }
                break;
              case 'error':
                acc += `\n⚠ ${event.message}`;
                setStreaming(acc);
                break;
              case 'message_start':
              default:
                break;
            }
          }
          setMessages((prev) => [...prev, { role: 'assistant', content: acc }]);
        } finally {
          setStreaming('');
          setThinking(null);
          setBusy(false);
        }
      })();
    },
    [brain, messages],
  );

  return (
    // 撑满全屏（height=rows）。布局分三类高度策略：
    // - Header / 思考 / 详情 / 菜单 / 输入框 / 状态栏：flexShrink=0，固定高度，永不被压缩；
    // - LogViewer（历史）：flexGrow=1 + flexShrink=1 + minHeight=0，独占中间剩余空间，
    //   内容超屏时自己收缩、overflow 裁掉顶部旧消息 —— 保证底部输入框恒定可见（曾因
    //   历史撑高把输入框挤出屏幕、回显消失，故所有固定块显式 flexShrink=0）。
    // 抗闪：入口层（src/index.ts）在 alt-screen 下把 Ink 满屏的 clearTerminal 替换为
    // 归位+清到屏末，原地覆盖不残影、抖动最小。
    <Box flexDirection="column" width={columns} height={rows}>
      <Box flexShrink={0}>
        <Header title="ballad" subtitle="Coding Agent · Phase 1 skeleton" cwd={cwd} />
      </Box>
      <LogViewer messages={messages} streaming={streaming} />
      {thinking !== null ? (
        <Box flexShrink={0} marginBottom={1}>
          <ShimmerText text={`${thinking}…`} spinner />
        </Box>
      ) : null}
      {detailsOpen ? (
        <Box flexShrink={0}>
          <DetailsPanel messageCount={messages.length} outputTokens={usage.outputTokens} />
        </Box>
      ) : null}
      {menuOpen ? (
        <Box flexShrink={0}>
          <SelectMenu items={filtered} state={menuState} />
        </Box>
      ) : null}
      <Box flexShrink={0}>
        <DynamicInput
          history={historyRef.current}
          disabled={busy}
          width={columns}
          onSubmit={handleSubmit}
          commandMode={menuOpen}
          onNavigate={handleNavigate}
          onAccept={handleAccept}
          onCancel={handleCancel}
          onValueChange={handleValueChange}
          onPaste={handlePaste}
        />
      </Box>
      <Box flexShrink={0}>
        <StatusBar
          busy={busy}
          inputTokens={usage.inputTokens}
          outputTokens={usage.outputTokens}
        />
      </Box>
    </Box>
  );
}
