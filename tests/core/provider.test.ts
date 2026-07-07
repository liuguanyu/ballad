/**
 * provider 路由与 ModelConfig 校验测试（Phase 2a）。
 *
 * 覆盖 spec REQ-PROV-1（按 protocol 路由）、REQ-PROV-2（注册表 + active 切换）。
 * 纯逻辑，零网络。mock 适配器通过 import 触发自注册。
 */
import { test, expect, describe } from 'bun:test';
import {
  ModelConfigSchema,
  selectBrain,
  registryFromEnv,
  type ProviderRegistry,
  type ModelConfig,
} from '../../src/core/provider.ts';
// 导入即触发 mock 适配器注册（side-effect import）。
import '../../src/core/providers/mock.ts';
import type { AgentEvent, ChatMessage } from '../../src/core/contract.ts';

function mockModel(overrides: Partial<ModelConfig> = {}): ModelConfig {
  return {
    name: 'mock-default',
    protocol: 'mock',
    model: 'mock',
    ...overrides,
  };
}

describe('REQ-PROV-2 · ModelConfig Zod 校验', () => {
  test('合法配置通过', () => {
    const parsed = ModelConfigSchema.parse(mockModel());
    expect(parsed.protocol).toBe('mock');
  });

  test('缺 name 被拒', () => {
    const { name: _omit, ...rest } = mockModel();
    void _omit;
    expect(() => ModelConfigSchema.parse(rest)).toThrow();
  });

  test('缺 model 被拒', () => {
    const { model: _omit, ...rest } = mockModel();
    void _omit;
    expect(() => ModelConfigSchema.parse(rest)).toThrow();
  });

  test('非法 protocol 被拒', () => {
    expect(() => ModelConfigSchema.parse(mockModel({ protocol: 'gemini' as never }))).toThrow();
  });

  test('baseUrl 非法 URL 被拒', () => {
    expect(() => ModelConfigSchema.parse(mockModel({ baseUrl: 'not-a-url' }))).toThrow();
  });
});

describe('REQ-PROV-1 · selectBrain 按 protocol 路由', () => {
  function registry(active: string, models: ModelConfig[]): ProviderRegistry {
    return { models, active };
  }

  async function drain(brain: (h: readonly ChatMessage[]) => AsyncGenerator<AgentEvent>): Promise<string> {
    const events: AgentEvent[] = [];
    for await (const ev of brain([{ role: 'user', content: 'hi' }])) {
      events.push(ev);
    }
    const text = events
      .filter((e) => e.type === 'token')
      .map((e) => (e.type === 'token' ? e.text : ''))
      .join('');
    return text;
  }

  test('active=mock 路由到 mock 适配器并吐出 token', async () => {
    const reg = registry('mock-default', [mockModel()]);
    const brain = selectBrain(reg, {});
    const text = await drain(brain);
    expect(text.length).toBeGreaterThan(0);
  });

  test('active 指向具体实例名（多实例同名协议）', async () => {
    const reg = registry('mock-b', [
      mockModel({ name: 'mock-a' }),
      mockModel({ name: 'mock-b' }),
    ]);
    const brain = selectBrain(reg, {});
    const text = await drain(brain);
    expect(text.length).toBeGreaterThan(0);
  });

  test('active 不在 models 中 → 抛错', () => {
    const reg = registry('nonexistent', [mockModel()]);
    expect(() => selectBrain(reg, {})).toThrow(/not in registry/);
  });

  test('未注册的 protocol → 抛错', () => {
    // anthropic 适配器尚未 import，路由表里没有它
    const reg = registry('claude', [mockModel({ name: 'claude', protocol: 'anthropic' })]);
    expect(() => selectBrain(reg, {})).toThrow(/no adapter registered/);
  });
});

describe('REQ-PROV-2/4 · registryFromEnv 多模型前缀解析', () => {
  test('同协议多实例：glm + deepseek 都走 openai-v1', () => {
    const env: Record<string, string | undefined> = {
      MODELS_GLM_PROTOCOL: 'openai-v1',
      MODELS_GLM_MODEL: 'z-ai/glmi-5.2',
      MODELS_GLM_BASE_URL: 'https://llm.api.zyuncs.com/v1',
      MODELS_GLM_API_KEY: 'k1',
      MODELS_DEEPSEEK_PROTOCOL: 'openai-v1',
      MODELS_DEEPSEEK_MODEL: 'deepseek-v4-pro',
      MODELS_DEEPSEEK_BASE_URL: 'https://api.deepseek.com/v1',
      MODELS_DEEPSEEK_API_KEY: 'k2',
    };
    const reg = registryFromEnv(env);
    expect(reg.models).toHaveLength(2);
    expect(reg.models.map((m) => m.name).sort()).toEqual(['deepseek', 'glm']);
    expect(reg.models.every((m) => m.protocol === 'openai-v1')).toBe(true);
    // 不设 active → 取第一条
    expect(reg.active).toBe(reg.models[0]!.name);
  });

  test('BALLAD_ACTIVE_MODEL 指定激活项', () => {
    const reg = registryFromEnv({
      MODELS_GLM_PROTOCOL: 'openai-v1',
      MODELS_GLM_MODEL: 'glm-5.2',
      MODELS_DEEPSEEK_PROTOCOL: 'openai-v1',
      MODELS_DEEPSEEK_MODEL: 'deepseek-v4-pro',
      BALLAD_ACTIVE_MODEL: 'deepseek',
    });
    expect(reg.active).toBe('deepseek');
  });

  test('缺 protocol 或 model 的条目被跳过', () => {
    const reg = registryFromEnv({
      MODELS_GLM_MODEL: 'no-protocol', // 缺 protocol
      MODELS_DEEPSEEK_PROTOCOL: 'openai-v1', // 缺 model
      MODELS_OK_PROTOCOL: 'mock',
      MODELS_OK_MODEL: 'm',
    });
    expect(reg.models.map((m) => m.name)).toEqual(['ok']);
  });

  test('无任何真实模型 → 回落 mock', () => {
    const reg = registryFromEnv({});
    expect(reg.models).toHaveLength(1);
    expect(reg.models[0]!.protocol).toBe('mock');
    expect(reg.active).toBe('mock');
  });

  test('name 小写化（前缀 GLM → name glm）', () => {
    const reg = registryFromEnv({
      MODELS_GLM_PROTOCOL: 'mock',
      MODELS_GLM_MODEL: 'm',
    });
    expect(reg.models[0]!.name).toBe('glm');
  });

  test('非法 protocol 被跳过（Zod 拒绝）', () => {
    const reg = registryFromEnv({
      MODELS_GLM_PROTOCOL: 'gemini',
      MODELS_GLM_MODEL: 'm',
    });
    // 该条被拒 → 无真实模型 → 回落 mock
    expect(reg.models[0]!.protocol).toBe('mock');
  });
});
