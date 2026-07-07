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
import { Box, Text, useApp, useInput, useStdout } from 'ink';
import type { Brain, ChatMessage, AgentEvent } from '../../core/contract.ts';
import { Header } from './components/Header.tsx';
import { LogViewer } from './components/LogViewer.tsx';
import { DynamicInput } from './components/DynamicInput.tsx';
import { StatusBar } from './components/StatusBar.tsx';
import { SelectMenu } from './components/SelectMenu.tsx';
import { DetailsPanel } from './components/DetailsPanel.tsx';
import { ShimmerText } from './components/ShimmerText.tsx';
import { theme } from './theme.ts';
import {
  filterItems,
  idleMenuState,
  moveSelection,
  MENU_WINDOW,
  type MenuState,
} from './logic/selectMenu.ts';
import { computeRows } from './logic/inputModel.ts';
import { SLASH_COMMANDS, isCommandQuery } from './logic/slashCommands.ts';
import {
  createClipboardDeps,
  readClipboard,
  type ClipboardDeps,
} from './services/clipboard.ts';

/** 可切换的模型项（/model 菜单展示用）。 */
export interface ModelOption {
  readonly name: string; // registry 里的 name（切换时回传）
  readonly label: string; // 展示名（如 'glm'）
  readonly hint?: string; // 副信息（如 'openai-v1 · z-ai/glm-5.2'）
}

interface AppProps {
  readonly brain: Brain;
  readonly cwd: string;
  /** 退出钩子（默认调用 Ink 的 useApp().exit）；测试可注入 spy 观测 /exit。 */
  readonly onExit?: () => void;
  /** 剪贴板依赖（默认走真实系统 CLI）；测试可注入假实现。 */
  readonly clipboard?: ClipboardDeps;
  /** 可切换的模型列表（/model 呼出）；不传则 /model 选中无副作用。 */
  readonly availableModels?: readonly ModelOption[];
  /** 当前激活模型 name（用于 Header/状态栏标识）。 */
  readonly activeModel?: string;
  /** 切换模型：由 index.ts 包装 selectBrain 注入，返回新 Brain。 */
  readonly onSwitchModel?: (name: string) => Brain;
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

function ThinkingBar({
  label,
  elapsed,
}: {
  readonly label: string;
  readonly elapsed: number;
}): React.ReactElement {
  const suffix = elapsed >= 1 ? ` ${elapsed}s` : '';
  return (
    <Box>
      <ShimmerText text={`${label}…${suffix}`} spinner />
    </Box>
  );
}

export function App({
  brain,
  cwd,
  onExit,
  clipboard,
  availableModels,
  activeModel,
  onSwitchModel,
}: AppProps): React.ReactElement {
  const { exit } = useApp();
  const { columns, rows } = useTerminalSize();
  // 当前生效的大脑：初始为传入 brain；/model 切换后替换为 onSwitchModel 返回的新 brain。
  // 用 ref 存（非 state）：brain 是函数，只在提交时被调用，不需要触发重渲染。
  // 避开 useState(函数) 的 lazy initializer 歧义（React 会把函数当 initializer 调用）。
  const activeBrainRef = useRef<Brain>(brain);
  // 当前激活模型名（Header 展示）：初始取 prop，/model 切换成功后同步更新。
  // 若只读 prop，切换后 UI 不会刷新（prop 由入口一次性传入，永不变化）。
  const [currentModel, setCurrentModel] = useState<string | undefined>(activeModel);
  const [messages, setMessages] = useState<readonly ChatMessage[]>([]);
  const [streaming, setStreaming] = useState<string>('');
  const [busy, setBusy] = useState<boolean>(false);
  // 工具事件流（Phase 2b 档 2）：收集 tool_call/tool_result 事件，传给 LogViewer 渲染气泡。
  const [toolEvents, setToolEvents] = useState<readonly AgentEvent[]>([]);
  // 思考态：大脑在推理、尚未吐正文；收到首个 token 即结束。驱动流光提示。
  const [thinking, setThinking] = useState<string | null>(null);
  // 思考文本累积（Phase 2b）：thinking 事件的 text 字段拼接，TUI 可折叠展示。
  const [thinkingText, setThinkingText] = useState<string>('');
  // 思考内容折叠/展开（Tab 切换）。
  const [thinkingExpanded, setThinkingExpanded] = useState<boolean>(false);
  // 思考态经过秒数：超过 1s 后显示，模拟 cc 的等待读秒反馈。
  const [thinkingElapsed, setThinkingElapsed] = useState<number>(0);
  const [usage, setUsage] = useState<Usage>({ inputTokens: 0, outputTokens: 0 });
  const [inputValue, setInputValue] = useState<string>('');
  const [menuState, setMenuState] = useState<MenuState>(() => idleMenuState());
  // 用户按 Esc 主动关闭菜单的意图；下一次输入变化时清除，使菜单可重新弹出。
  const [menuDismissed, setMenuDismissed] = useState<boolean>(false);
  // Ctrl+O 切换的详情面板显隐（纯渲染层状态，不干扰大脑流式）。
  const [detailsOpen, setDetailsOpen] = useState<boolean>(false);
  const historyRef = useRef<string[]>([]);

  // /model 呼出的模型选择菜单：独立于命令菜单的第二层 SelectMenu（复用同一组件）。
  const [modelMenuOpen, setModelMenuOpen] = useState<boolean>(false);
  const [modelMenuState, setModelMenuState] = useState<MenuState>(() => idleMenuState());
  const modelItems: readonly ModelOption[] = availableModels ?? [];

  // 外部强制清空 DynamicInput 的信号（/model 选中后清掉 slash command）。
  // DynamicInput 的 value 是内部状态机独占，App 改镜像无法反向推回，故用此信号触发。
  const [inputResetSignal, setInputResetSignal] = useState<number>(0);

  const quit = useCallback((): void => {
    if (onExit) {
      onExit();
    } else {
      exit();
    }
  }, [onExit, exit]);

  useEffect(() => {
    if (thinking == null) {
      setThinkingElapsed(0);
      return;
    }
    const startedAt = Date.now();
    const id = setInterval(() => {
      setThinkingElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 250);
    return () => clearInterval(id);
  }, [thinking]);

  // 命令模式与过滤：'/' 开头且有候选、且未被 Esc 主动关闭时弹菜单。
  const commandMode = isCommandQuery(inputValue);
  const filtered = commandMode ? filterItems(SLASH_COMMANDS, inputValue) : [];
  const menuOpen = commandMode && filtered.length > 0 && !menuDismissed;

  // 执行选中的命令（/exit 退出；/model 呼出模型菜单；加命令在此加 case）。
  const runCommand = useCallback(
    (value: string): void => {
      switch (value) {
        case 'exit':
          quit();
          break;
        case 'model':
          // 进入模型选择模式：打开第二层菜单，复位高亮。
          if (modelItems.length > 0) {
            setModelMenuOpen(true);
            setModelMenuState(idleMenuState());
          }
          break;
        default:
          break;
      }
    },
    [modelItems.length],
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

  // 模型菜单的导航/选中/取消（与命令菜单同款交互，独立状态）。
  const handleModelNavigate = useCallback(
    (dir: 'up' | 'down'): void => {
      setModelMenuState((s) => moveSelection(s, dir, modelItems.length));
    },
    [modelItems.length],
  );

  const handleModelAccept = useCallback((): void => {
    const chosen = modelItems[modelMenuState.selected];
    if (chosen && onSwitchModel) {
      const nextBrain = onSwitchModel(chosen.name);
      activeBrainRef.current = nextBrain;
      setCurrentModel(chosen.name); // 同步 Header 显示（否则切换后 UI 无反馈）
    }
    setModelMenuOpen(false);
    setModelMenuState(idleMenuState());
    setInputValue('');
    setMenuState(idleMenuState());
    setMenuDismissed(false);
    // 强制清空 DynamicInput 的 slash command（如 /model），避免命令模式重新弹出。
    setInputResetSignal((n) => n + 1);
  }, [modelItems, modelMenuState.selected, onSwitchModel]);

  const handleModelCancel = useCallback((): void => {
    setModelMenuOpen(false);
    setModelMenuState(idleMenuState());
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

  // 全局快捷键：Ctrl+C 退出；Ctrl+O 切换详情面板；Tab 展开/折叠思考内容。
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      quit();
      return;
    }
    if (key.ctrl && input === 'o') {
      setDetailsOpen((v) => !v);
      return;
    }
    // Tab：有思考文本时切换展开/折叠（思考态或思考已完成均可）。
    if (key.tab && thinkingText.length > 0) {
      setThinkingExpanded((v) => !v);
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
      setToolEvents([]); // 新对话清空旧工具事件
      setThinkingText(''); // 清空旧思考文本
      // 提交即进入思考态（默认标签）：真实模型（如 openai-v1 协议）可能全程不发
      // thinking 事件，若等事件才显示，等待期消息流里毫无反馈。thinking 事件到达
      // 时用其 label 覆盖，首个 token 清除；提示固定在输入框顶线正上方。
      setThinking('思考中');
      setThinkingElapsed(0);

      void (async (): Promise<void> => {
        let acc = '';
        try {
          for await (const event of activeBrainRef.current(nextHistory)) {
            switch (event.type) {
              case 'thinking':
                setThinking(event.label ?? '思考中');
                // 累积思考文本（Phase 2b）：thinking 事件的 text 字段拼接，TUI 可折叠展示。
                if (event.text) {
                  setThinkingText((prev) => prev + event.text);
                }
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
              case 'tool_call':
              case 'tool_result':
                // Phase 2b 档 2：收集工具事件，传给 LogViewer 渲染气泡（动作+摘要）。
                setToolEvents((prev) => [...prev, event]);
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
    [messages],
  );

  // LogViewer 的行数预算：终端总高减去所有固定块的实际占高。
  // 必须精确扣除——多算会让最新内容被 overflow 裁掉（滚动错乱的根源），
  // 少算只是留白。各常数与对应组件的渲染行数一一对应：
  // Header=3 行文本 + 1 空行；Details=2 行 + 1 空行；菜单=可见项(≤MENU_WINDOW)+1 提示行；
  // ThinkingBar=1 行（贴在输入框上横线正上方）；输入框=顶线 + 文本行数 + 底线；状态栏=1 行。
  const headerRows = 4;
  const detailsRows = detailsOpen ? 3 : 0;
  const menuRows = menuOpen ? Math.min(filtered.length, MENU_WINDOW) + 1 : 0;
  const modelMenuRows = modelMenuOpen
    ? Math.min(modelItems.length, MENU_WINDOW) + 1
    : 0;
  const thinkingRows = thinking != null ? 1 : 0;
  const thinkingDetailLines = thinkingExpanded && thinkingText.length > 0
    ? thinkingText.split('\n').slice(0, 8)
    : [];
  const thinkingDetailRows = thinkingDetailLines.length;
  const inputRows = computeRows(inputValue) + 2;
  const statusRows = 1;
  const logHeight = Math.max(
    0,
    rows - headerRows - detailsRows - menuRows - modelMenuRows - thinkingDetailRows - thinkingRows - inputRows - statusRows,
  );

  return (
    // 撑满全屏（height=rows）。布局分三类高度策略：
    // - Header / 思考 / 详情 / 菜单 / 输入框 / 状态栏：flexShrink=0，固定高度，永不被压缩；
    // - LogViewer（历史）：flexGrow=1 + flexShrink=1 + minHeight=0，独占中间剩余空间；
    //   超屏时由 logic/logLines 预折行 + 尾部切片，永远显示最新内容（滚动不再错乱），
    //   overflow=hidden 仅作兜底 —— 保证底部输入框恒定可见。
    // 抗闪：入口层（src/index.ts）在 alt-screen 下把 Ink 满屏的 clearTerminal 替换为
    // 归位+清到屏末，原地覆盖不残影、抖动最小。
    <Box flexDirection="column" width={columns} height={rows}>
      <Box flexShrink={0}>
        <Header
          title="ballad"
          subtitle={currentModel ? `model: ${currentModel}` : 'Coding Agent · Phase 1'}
          cwd={cwd}
        />
      </Box>
      <LogViewer
        messages={messages}
        streaming={streaming}
        toolEvents={toolEvents}
        columns={columns}
        height={logHeight}
      />
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
      {modelMenuOpen ? (
        <Box flexShrink={0}>
          <SelectMenu
            items={modelItems.map((m) => ({ value: m.name, label: m.label, hint: m.hint }))}
            state={modelMenuState}
          />
        </Box>
      ) : null}
      {thinking != null ? (
        <Box flexShrink={0}>
          <ThinkingBar label={thinking} elapsed={thinkingElapsed} />
        </Box>
      ) : null}
      {thinkingDetailLines.length > 0 ? (
        <Box flexShrink={0} flexDirection="column" paddingLeft={2}>
          {thinkingDetailLines.map((line, i) => (
            <Text key={i} color={theme.muted}>{line}</Text>
          ))}
        </Box>
      ) : null}
      <Box flexShrink={0}>
        <DynamicInput
          history={historyRef.current}
          disabled={busy}
          width={columns}
          onSubmit={handleSubmit}
          commandMode={menuOpen || modelMenuOpen}
          onNavigate={modelMenuOpen ? handleModelNavigate : handleNavigate}
          onAccept={modelMenuOpen ? handleModelAccept : handleAccept}
          onCancel={modelMenuOpen ? handleModelCancel : handleCancel}
          onValueChange={handleValueChange}
          onPaste={handlePaste}
          resetSignal={inputResetSignal}
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
