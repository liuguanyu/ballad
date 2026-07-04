# Spec: 剪贴板粘贴（tui-clipboard）

## 背景

白皮书 Phase 1 施工项 3：「编写剪贴板文本与图片获取模块：封装 **ClipboardService**，
利用 Bun.spawn 调取系统命令，确保 Ctrl+V 时大数据量不卡顿」。需求矩阵：
- **文本粘贴**：大段代码 / 多行日志直接粘贴，渲染层不阻塞、不撕裂。
- **图片粘贴（多模态预留）**：剪贴板为图片时，静默捕获写入 `.agent/temp/`，
  输入框显示 `[Image: temp_xxx.png]` 作为多模态上下文标记。

裁决链：`AGENTS.md`（铁律）> 本 spec > 代码。剪贴板是**平台能力**（调系统 CLI），
放 `platforms/tui/services/`，**不进 core**（守脑口分离：core 不碰终端/系统桥接）。

## 需求

### REQ-CLIP-1 跨平台 CLI 桥接
`ClipboardService` 用 `Bun.spawn` 调系统 CLI 读剪贴板，按平台分派：
- **darwin**：文本 `pbpaste`；图片 `pngpaste -`（输出 PNG 二进制到 stdout）。
- **linux**：文本 `xclip -selection clipboard -o`；图片 `xclip -selection clipboard -t image/png -o`。
CLI 缺失（未安装）时不崩溃：返回"无内容"结果，由上层降级为空粘贴。

### REQ-CLIP-2 文本粘贴不阻塞
读文本为异步（`await` 子进程），大数据量（数千行）下不阻塞渲染循环；
返回的文本原样交给上层追加到输入框。

### REQ-CLIP-3 图片捕获与标记
剪贴板为图片时：把 PNG 字节写入 `.agent/temp/clip_<seq>.png`（目录不存在则创建），
返回一个**标记文本** `[Image: clip_<seq>.png]` 供输入框显示与后续多模态引用。
`.agent/` 已在 .gitignore，不污染仓库。

### REQ-CLIP-4 读取结果契约
`readClipboard()` 返回判别联合：
- `{ kind: 'text', text: string }`
- `{ kind: 'image', marker: string, path: string }`
- `{ kind: 'empty' }`（无内容 / CLI 缺失 / 失败）
判定顺序：先试图片（更具体），无图片再试文本，都无则 empty。

### REQ-CLIP-5 与输入区接线（骨架）
Phase 1 提供 service 与纯逻辑，App/输入区在 `Ctrl+V` 时调用 `readClipboard()`
并把 `text` 或 `image.marker` 追加进输入框。
> 注：Ink 的 `useInput` 对 Ctrl+V 的捕获与真实终端粘贴（bracketed paste）在测试环境
> 不稳定，故**接线以纯逻辑 + service 单测为主**，真实 Ctrl+V 手感由 e2e 冒烟在真 pty 覆盖。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-CLIP-1 | `clipboard.test.ts`：按 `platform` 选出正确的命令+参数（`resolveCommands` 纯函数） |
| REQ-CLIP-3 | `clipboard.test.ts`：`buildImageMarker(seq)` → `[Image: clip_<seq>.png]`；路径拼接正确 |
| REQ-CLIP-4 | `clipboard.test.ts`：注入假 runner，图片优先、文本次之、都空则 empty 的判别 |

## 关联实现

- `src/platforms/tui/services/clipboard.ts`（`readClipboard` + 纯逻辑 `resolveCommands`/`buildImageMarker`，`Bun.spawn` 注入式 runner 便于测试）
- 接线：`src/platforms/tui/components/DynamicInput.tsx` 或 `index.tsx`（Ctrl+V 调 service，追加进输入）
