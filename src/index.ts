/**
 * 统一启动开关：组装"大脑"与"嘴巴"。
 *
 * 这是脑口分离的接线点——选一个 Brain 实现，选一个表现层，插上运行。
 * Phase 4 换 Web GUI 时，只改这里的表现层挂载，core 与大脑一行不动。
 */
import React from 'react';
import { render } from 'ink';
import OpenAI from 'openai';
import Anthropic from '@anthropic-ai/sdk';
import { App } from './platforms/tui/index.tsx';
import type { Brain } from './core/contract.ts';
import {
  selectBrain,
  registryFromEnv,
  type AdapterDeps,
  type ModelConfig,
  type ProviderRegistry,
} from './core/provider.ts';
import { buildGraph, createGraphBrain } from './core/graph/graph.ts';
import { ToolRegistry } from './core/tools/registry.ts';
import type { JsonSchema } from './core/tools/registry.ts';
import { readTool } from './core/tools/read.ts';
import { writeTool, editTool } from './core/tools/write.ts';
import { bashTool } from './core/tools/bash.ts';
import { lsTool, grepTool } from './core/tools/query.ts';
// 导入即注册各协议适配器到路由表（side-effect import）。
import './core/providers/mock.ts';
import './core/providers/openaiChat.ts';
import './core/providers/openaiResponses.ts';
import './core/providers/anthropic.ts';

/** 进入终端备用屏（alternate screen），实现占满全屏、退出后恢复原内容。 */
const ENTER_ALT_SCREEN = '\x1b[?1049h\x1b[H';
const LEAVE_ALT_SCREEN = '\x1b[?1049l';

/** Ink 满屏时每帧写出的整屏清屏序列（擦屏 + 清 scrollback + 光标归位）。 */
const CLEAR_TERMINAL = '\x1b[2J\x1b[3J\x1b[H';
/**
 * 替换序列：归位左上 + 清到屏末（eraseDown）。
 * - 归位 + 清到屏末 = 擦净整个可视区再重画，杜绝旧帧残影（纯归位会残影，输入行错乱）。
 * - 不含 \x1b[2J（整屏强擦）与 \x1b[3J（清 scrollback）——alt-screen 下二者多余，
 *   且是每帧全屏闪的主因。eraseDown 更轻，配合 alt-screen 原地覆盖，抖动最小。
 */
const HOME_ERASE_DOWN = '\x1b[H\x1b[J';

/**
 * 抗闪 stdout 包装：撑满全屏时 Ink 会每帧写出 clearTerminal 整屏清屏（闪）。
 * 该序列的 \x1b[2J\x1b[3J（整屏强擦 + 清 scrollback）在 alt-screen 下多余且是闪的主因，
 * 但完全不擦又会残影（输入行错乱）。故替换为 \x1b[H\x1b[J（归位 + 清到屏末）：
 * 擦净可视区再重画，无残影、抖动最小。其余输出原样透传。
 * 用 Proxy 透明代理，保留 columns/rows/isTTY/on 等 Ink 依赖的全部接口。
 */
function wrapStdoutAntiFlicker(stdout: NodeJS.WriteStream): NodeJS.WriteStream {
  return new Proxy(stdout, {
    get(target, prop, receiver) {
      if (prop === 'write') {
        return (chunk: unknown, ...rest: unknown[]): boolean => {
          const patched =
            typeof chunk === 'string' && chunk.includes(CLEAR_TERMINAL)
              ? chunk.split(CLEAR_TERMINAL).join(HOME_ERASE_DOWN)
              : chunk;
          return (target.write as (...args: unknown[]) => boolean)(patched, ...rest);
        };
      }
      const value = Reflect.get(target, prop, receiver);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}

/**
 * 把真实 OpenAI SDK 包成 openai-v1 适配器需要的最小 client 接口。
 * SDK 的 client.chat.completions.create({stream:true}) 返回 Stream<ChatCompletionChunk>，
 * Stream 实现 AsyncIterable，正好匹配 OpenAIChatClient.stream 的契约。胶水只在此层（副作用层）。
 */
function makeOpenAIChatClient(config: ModelConfig): unknown {
  const client = new OpenAI({
    apiKey: config.apiKey ?? undefined,
    baseURL: config.baseUrl,
    defaultHeaders: config.headers,
  });
  // 胶水层：把适配器的简化 params 映射成 SDK 期望的 mutable 形状。
  // create({stream:true}) 返回 Promise<Stream>，await 后再迭代；包成 async generator。
  type ChatRole = 'user' | 'assistant' | 'system';
  type ToolDef = { type: 'function'; function: { name: string; description: string; parameters: JsonSchema } };
  return {
    stream: async function* (
      params: {
        model: string;
        messages: readonly { role: ChatRole; content: string }[];
        stream: true;
        stream_options?: { include_usage: true };
        tools?: readonly ToolDef[];
      },
    ): AsyncGenerator<unknown> {
      const s = await client.chat.completions.create({
        model: params.model,
        stream: true,
        stream_options: params.stream_options,
        messages: params.messages.map((m) => ({ role: m.role, content: m.content })),
        ...(params.tools && params.tools.length > 0
          ? { tools: params.tools as ToolDef[], tool_choice: 'auto' as const }
          : {}),
      });
      for await (const chunk of s) {
        yield chunk;
      }
    },
  };
}

/**
 * 读 env 构造 ProviderRegistry（spec REQ-PROV-4：无真实 key 回落 mock）。
 * 唯一副作用聚集处：core 不读 env，纯函数 registryFromEnv 在此接收 process.env。
 * Bun 原生自动加载 .env，无需 dotenv。
 */
function buildRegistry(): ProviderRegistry {
  return registryFromEnv(process.env as Record<string, string | undefined>);
}

/** 把真实 OpenAI SDK 包成 openai-v2 适配器需要的最小 client 接口。 */
function makeOpenAIResponsesClient(config: ModelConfig): unknown {
  const client = new OpenAI({
    apiKey: config.apiKey ?? undefined,
    baseURL: config.baseUrl,
    defaultHeaders: config.headers,
  });
  return {
    stream: async function* (params: {
      model: string;
      input: string;
      stream: true;
    }): AsyncGenerator<unknown> {
      const s = await client.responses.create(params);
      for await (const ev of s) {
        yield ev;
      }
    },
  };
}

/** 把真实 @anthropic-ai/sdk 包成 anthropic 适配器需要的最小 client 接口。 */
function makeAnthropicClient(config: ModelConfig): unknown {
  const client = new Anthropic({
    apiKey: config.apiKey ?? undefined,
    baseURL: config.baseUrl,
    defaultHeaders: config.headers,
  });
  return {
    stream: async function* (params: {
      model: string;
      messages: readonly { role: 'user' | 'assistant' | 'system'; content: string }[];
      max_tokens: number;
      tools?: readonly { name: string; description: string; input_schema: JsonSchema }[];
    }): AsyncGenerator<unknown> {
      const s = await client.messages.stream({
        model: params.model,
        max_tokens: params.max_tokens,
        messages: params.messages.map((m) => ({ role: m.role, content: m.content })),
        ...(params.tools && params.tools.length > 0
          ? {
              tools: params.tools.map((t) => ({
                name: t.name,
                description: t.description,
                input_schema: {
                  type: 'object' as const,
                  properties: t.input_schema.properties,
                  required: [...(t.input_schema.required ?? [])],
                },
              })),
            }
          : {}),
      });
      for await (const ev of s) {
        yield ev;
      }
    },
  };
}

/** 构造依赖注入：把当前激活模型对应的 SDK client 包好。 */
function buildDeps(registry: ProviderRegistry, tools: ToolRegistry): AdapterDeps {
  const active = registry.models.find((m) => m.name === registry.active);
  const toolList = tools.entries();
  if (active === undefined) {
    return { tools: toolList };
  }
  switch (active.protocol) {
    case 'openai-v1':
      return { openai: makeOpenAIChatClient(active), tools: toolList };
    case 'openai-v2':
      return { openai: makeOpenAIResponsesClient(active), tools: toolList };
    case 'anthropic':
      return { anthropic: makeAnthropicClient(active), tools: toolList };
    default:
      // mock 协议不需要 client。
      return { tools: toolList };
  }
}

/** 构造工具注册表：注册首批 4 类工具（read/write/bash/query）。 */
function buildTools(): ToolRegistry {
  const tools = new ToolRegistry();
  tools.register(readTool);
  tools.register(writeTool);
  tools.register(editTool);
  tools.register(bashTool);
  tools.register(lsTool);
  tools.register(grepTool);
  return tools;
}

async function main(): Promise<void> {
  const isTTY = process.stdout.isTTY === true;
  if (isTTY) {
    process.stdout.write(ENTER_ALT_SCREEN);
  }

  const registry = buildRegistry();
  const tools = buildTools();
  const deps = buildDeps(registry, tools);

  // Phase 2b：用 LangGraph 图替代线性 brain。
  // selectBrain 返回模型适配器（reason 节点），buildGraph 包装成图（加 tool-call 循环），
  // createGraphBrain 把图转回 Brain 签名（App 零改）。
  const modelAdapter = selectBrain(registry, deps);
  const graph = buildGraph(modelAdapter, tools);
  const brain = createGraphBrain(graph);
  const cwd = process.cwd();

  // /model 切换器：按 name 重新选 active、重算 deps（不同协议 client 不同）、重建图。
  // 闭包捕获 registry/deps/tools 工厂，返回新 Brain 注入 App。mock-only（无真实模型）时不暴露模型列表。
  const hasRealModels = registry.models.some((m) => m.protocol !== 'mock');
  const availableModels = hasRealModels
    ? registry.models.map((m) => ({
        name: m.name,
        label: m.name,
        hint: `${m.protocol} · ${m.model}`,
      }))
    : undefined;
  const switchBrain = (name: string): Brain => {
    const nextRegistry = { models: registry.models, active: name };
    const nextDeps = buildDeps(nextRegistry, tools);
    const nextModelAdapter = selectBrain(nextRegistry, nextDeps);
    const nextGraph = buildGraph(nextModelAdapter, tools);
    return createGraphBrain(nextGraph);
  };

  // 仅 TTY 下启用抗闪包装；非 TTY（测试/管道）透传原 stdout。
  const stdout = isTTY ? wrapStdoutAntiFlicker(process.stdout) : process.stdout;
  const app = render(
    React.createElement(App, {
      brain,
      cwd,
      availableModels,
      activeModel: registry.active,
      onSwitchModel: hasRealModels ? switchBrain : undefined,
    }),
    { stdout },
  );

  try {
    await app.waitUntilExit();
  } finally {
    if (isTTY) {
      process.stdout.write(LEAVE_ALT_SCREEN);
    }
  }
}

void main();
