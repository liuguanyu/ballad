/**
 * 真实模型接入层（Phase 2a）：协议路由 + 多模型注册表。
 *
 * 职责单一（铁律 2）：本文件只定义"配置形状 + 按 protocol 路由"，不含任何协议细节、
 * 不读 env、不 new SDK client。协议适配在 providers/*.ts，env 读取在 index.ts。
 *
 * 脑口分离（铁律 0）：本文件不 import 任何终端 / Ink / React，只有 Zod 与类型。
 *
 * No AnyScript（铁律 1）：所有对外类型由 Zod schema 推导；SDK 流式 chunk 经 unknown 收窄在适配器内。
 *
 * Phase 2b 会用 LangGraph.js 把"无状态生成器"重构为"图状态机"，但对外 Brain 签名不变，
 * 本路由层一行不动。
 */
import { z } from 'zod';
import type { Brain } from './contract.ts';
import type { Tool } from './tools/registry.ts';

/** 支持的 wire protocol。路由按此分发，不按品牌。 */
export const WireProtocolSchema = z.enum([
  'anthropic', // /v1/messages
  'openai-v1', // /v1/chat/completions
  'openai-v2', // /v1/responses
  'mock', // 离线（无 key fallback / 测试基准）
]);
export type WireProtocol = z.infer<typeof WireProtocolSchema>;

/**
 * 单条模型配置（注册表元素）。判别按 protocol。
 * 同协议下的品牌差异（base_url / model / headers）仅在此表达，适配器不分支。
 */
export const ModelConfigSchema = z.object({
  name: z.string().min(1),
  protocol: WireProtocolSchema,
  /** 厂商 model id，如 'claude-sonnet-4-5' / 'gpt-4o' / 内网模型名。 */
  model: z.string().min(1),
  baseUrl: z.string().url().optional(),
  apiKey: z.string().optional(),
  /** 透传到 SDK 的额外请求头（如内网网关鉴权）。 */
  headers: z.record(z.string(), z.string()).optional(),
});
export type ModelConfig = z.infer<typeof ModelConfigSchema>;

/** 多模型注册表。运行时按 active 切换即换模型。 */
export interface ProviderRegistry {
  readonly models: readonly ModelConfig[];
  /** 当前激活实例的 name（必须能在 models 中找到）。 */
  readonly active: string;
}

/**
 * 从扁平 env 字典解析多模型注册表（纯函数，可单测；不读 process.env）。
 *
 * 约定前缀式分组：`MODELS_<NAME>_{PROTOCOL,MODEL,BASE_URL,API_KEY,HEADERS_*}`。
 * - <NAME> 是模型实例标识（如 GLM / DEEPSEEK / OPENAI），即 registry 里的 name（小写化）。
 * - 同一协议下可有多个实例（glm-5.2 / deepseek-v4-pro 都走 openai-v1），适配器不分支。
 * - BALLAD_ACTIVE_MODEL 指定激活项；不设则取第一条；无任何真实模型回落 mock。
 *
 * 纯函数接收 env 字典，红线"core 不读 env"指 core 不直接访问 process.env——
 * 由 index.ts 把 process.env 传入此处解析，逻辑可测。
 */
export function registryFromEnv(env: Record<string, string | undefined>): ProviderRegistry {
  const groups = new Map<string, Record<string, string>>();
  for (const [key, value] of Object.entries(env)) {
    if (!key.startsWith('MODELS_') || value === undefined || value === '') {
      continue;
    }
    // MODELS_<NAME>_<FIELD>：拆成 name + field。
    const rest = key.slice('MODELS_'.length);
    const underscore = rest.indexOf('_');
    if (underscore === -1) {
      continue; // 只有 MODELS_<NAME> 无字段，忽略
    }
    const name = rest.slice(0, underscore).toLowerCase();
    const field = rest.slice(underscore + 1).toLowerCase();
    const bucket = groups.get(name) ?? {};
    bucket[field] = value;
    groups.set(name, bucket);
  }

  const models: ModelConfig[] = [];
  for (const [name, fields] of groups) {
    const protocol = fields['protocol'];
    const model = fields['model'];
    if (!protocol || !model) {
      continue; // 缺关键字段，跳过该条
    }
    const parsed = ModelConfigSchema.safeParse({
      name,
      protocol,
      model,
      baseUrl: fields['base_url'],
      apiKey: fields['api_key'],
    });
    if (parsed.success) {
      models.push(parsed.data);
    }
  }

  // 无任何真实模型 → 回落 mock，保证开箱即跑（spec REQ-PROV-4）。
  if (models.length === 0) {
    models.push({ name: 'mock', protocol: 'mock', model: 'mock' });
  }

  const active = env['BALLAD_ACTIVE_MODEL'] ?? models[0]!.name;
  return { models, active };
}

/**
 * SDK client 工厂（依赖注入）。
 * core 不自己 new SDK client —— 由 index.ts 据配置构造后注入，测试传 mock。
 * 每个 adapter 声明它需要的 client 形状；这里用 unknown + 各适配器内部收窄，
 * 避免 core 直接依赖厂商 SDK 类型（守低耦合 + No Any）。
 */
export interface AdapterDeps {
  readonly anthropic?: unknown;
  readonly openai?: unknown;
  readonly tools?: readonly Tool[];
}

/** 适配器函数签名：给定单条配置 + 注入的 client，返回一个 Brain。 */
export type Adapter = (config: ModelConfig, deps: AdapterDeps) => Brain;

/** 协议 → 适配器 的注册表（内部，可被测试覆盖）。 */
const adapters: Partial<Record<WireProtocol, Adapter>> = {};

/** 注册一个协议的适配器（providers/*.ts 在 import 时调用）。 */
export function registerAdapter(protocol: WireProtocol, adapter: Adapter): void {
  adapters[protocol] = adapter;
}

/**
 * 纯函数路由：按激活实例的 protocol 选适配器，注入 deps，返回 Brain。
 * 不读 env、不 new client、不持有状态。找不到协议或激活项时抛错（接线层应保证不触发）。
 */
export function selectBrain(registry: ProviderRegistry, deps: AdapterDeps): Brain {
  const active = registry.models.find((m) => m.name === registry.active);
  if (active === undefined) {
    throw new Error(`selectBrain: active model "${registry.active}" not in registry`);
  }
  const adapter = adapters[active.protocol];
  if (adapter === undefined) {
    throw new Error(`selectBrain: no adapter registered for protocol "${active.protocol}"`);
  }
  return adapter(active, deps);
}
