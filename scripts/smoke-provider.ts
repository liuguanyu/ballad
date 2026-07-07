/**
 * 临时冒烟脚本（Phase 2a）：验证 provider 层真实模型接入。
 * 不进仓，验完删除。只验 core 层：读 .env → 构造 registry → selectBrain → 打印 AgentEvent。
 *
 * 用法：填好 .env 后 `bun run scripts/smoke-provider.ts`
 */
import OpenAI from 'openai';
import { selectBrain, registryFromEnv, type AdapterDeps, type ProviderRegistry } from '../src/core/provider.ts';
import '../src/core/providers/mock.ts';
import '../src/core/providers/openaiChat.ts';
import type { AgentEvent, ChatMessage } from '../src/core/contract.ts';

function buildRegistry(): ProviderRegistry {
  return registryFromEnv(process.env as Record<string, string | undefined>);
}

function buildDeps(registry: ProviderRegistry): AdapterDeps {
  const active = registry.models.find((m) => m.name === registry.active);
  if (!active) return {};
  if (active.protocol === 'openai-v1') {
    const client = new OpenAI({
      apiKey: active.apiKey,
      baseURL: active.baseUrl,
    });
    return {
      openai: {
        stream: async function* (
          params: {
            model: string;
            messages: readonly { role: 'user' | 'assistant' | 'system'; content: string }[];
            stream: true;
            stream_options?: { include_usage: true };
          },
        ): AsyncGenerator<unknown> {
          const s = await client.chat.completions.create({
            ...params,
            messages: params.messages.map((m) => ({ role: m.role, content: m.content })),
          });
          for await (const chunk of s) {
            yield chunk;
          }
        },
      },
    };
  }
  return {};
}

async function main(): Promise<void> {
  const registry = buildRegistry();
  console.error(`[smoke] active model: ${registry.active}`);
  const deps = buildDeps(registry);
  const brain = selectBrain(registry, deps);

  const history: ChatMessage[] = [{ role: 'user', content: '用一句话介绍你自己' }];
  let tokenCount = 0;
  let lastUsage = '';
  for await (const ev of brain(history) as AsyncGenerator<AgentEvent>) {
    switch (ev.type) {
      case 'message_start':
        console.log(`>> message_start role=${ev.role}`);
        break;
      case 'thinking':
        console.log('>> thinking');
        break;
      case 'token':
        process.stdout.write(ev.text);
        tokenCount++;
        break;
      case 'message_end':
        lastUsage = ev.usage
          ? `in=${ev.usage.inputTokens} out=${ev.usage.outputTokens}`
          : '(no usage)';
        console.log(`\n>> message_end ${lastUsage}`);
        break;
      case 'error':
        console.error(`>> ERROR: ${ev.message}`);
        break;
    }
  }
  console.log(`\n[smoke] done. tokens emitted: ${tokenCount}`);
}

void main();
