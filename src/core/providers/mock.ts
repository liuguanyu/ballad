/**
 * mock 协议适配器（Phase 2a）。
 *
 * 职责单一（铁律 2）：把现有 createMockBrain 包成 Adapter 签名，让 selectBrain 能统一路由。
 * 作为"无 key 离线 fallback"与"单测基准"——不占真实协议预算，保留 createMockBrain 不删。
 *
 * 不读 env、不碰 SDK、零外部依赖。导入时自注册到协议路由表。
 */
import type { Adapter } from '../provider.ts';
import { registerAdapter } from '../provider.ts';
import { createMockBrain } from '../agent.ts';

/** mock 适配器：忽略 config 与 deps，直接委托 createMockBrain。 */
const mockAdapter: Adapter = () => createMockBrain();

registerAdapter('mock', mockAdapter);

export { mockAdapter };
