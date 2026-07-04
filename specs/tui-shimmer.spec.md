# Spec: 流光文字效果（tui-shimmer）

## 背景

对齐 Claude Code「思考中」那种微光扫过文字的呼吸感。参考实现是 pan-player-cmd 的
Go 版 `renderShimmerText`（歌词流光）：一条从暗到亮再到暗的渐变「光束」在文字上逐字符、
逐帧向右扫过，扫完留一段暗色间隔再来下一道。本能力将复用于：歌词式流光展示、
以及后续**模型思考态**的 spinner + 微光提示。

裁决链：`AGENTS.md`（铁律）> 本 spec > 代码。流光是纯表现层效果，**不进 core**。
遵循项目「纯逻辑 in logic/ + 帧驱动 in hooks/ + 渲染 in components/」分层。

## 算法（源自 Go 版，拆分为纯逻辑）

- **调色板 palette**：一个从暗→亮→暗的颜色数组（波峰在中心最亮）。默认蓝色系 9 级：
  `#1E6FD9 #2A86F0 #45A3FF #66B8FF #8CCBFF #66B8FF #45A3FF #2A86F0 #1E6FD9`。
- **基础色 base**：光束之外字符的暗色（默认 palette 首元素 `#1E6FD9`）。
- **循环周期 cycleLen** = `字数 + palette 长度`，且不小于 `MIN_CYCLE`(=30)——保证光束扫完后
  有暗色间隔再出现下一道。
- **每字符颜色**：`pos = ((i - frame) % cycleLen + cycleLen) % cycleLen`；
  `pos < palette.length` 时取 `palette[pos]`（落在光束里），否则取 `base`。
  随 `frame` 增大，光束向右移动。

## 需求

### REQ-SHIM-1 纯逻辑：逐字符着色
`shimmerColors(text, frame, options?)` 返回长度 = 字符数的颜色字符串数组（按上述算法）。
纯函数、无 React/Ink，可脱终端确定性单测。空串返回空数组。
按 Unicode code point（`[...text]`）切分，兼容中文/emoji。

### REQ-SHIM-2 纯逻辑：spinner 帧
`spinnerFrame(frame)` 从盲文旋转字符 `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` 中按 `frame` 取一个，
且转速为主流光的一半（`frame/2`，对齐 Go 版），负 frame 也能正确取模。

### REQ-SHIM-3 hook：帧驱动
`useShimmerFrame(options?)` 用 `setInterval` 每 `intervalMs`(默认 100) 递增并返回 `frame`。
组件卸载时清理定时器。`active=false` 时暂停递增（思考结束即静止）。

### REQ-SHIM-4 组件：ShimmerText
`<ShimmerText text spinner? active? intervalMs? palette? />`：
- 内部用 `useShimmerFrame` 拿 frame，`shimmerColors` 拿每字符色，渲染为一串带色 `<Text>`。
- `spinner=true` 时前置一个 `spinnerFrame(frame)` 旋转字符（用波峰中间色 `#45A3FF`）+ 空格。
- `active=false`（默认 true）时定格不动（便于测试与静止展示）。

## 验收标准

| 需求 | 测试用例 |
| :-- | :-- |
| REQ-SHIM-1 | `shimmer.test.ts`：frame=0 时首字符落波峰起点；波束随 frame 右移；光束外为 base；空串→[]；中文按 code point 计数 |
| REQ-SHIM-2 | `shimmer.test.ts`：spinnerFrame 循环取值；frame/2 半速；负 frame 取模正确 |
| REQ-SHIM-4 | `ShimmerText.test.tsx`：渲染出全部字符；spinner=true 时前置旋转字符；空 text 不崩 |

## 关联实现

- `src/platforms/tui/logic/shimmer.ts`（`shimmerColors` / `spinnerFrame` / 默认 palette 常量）
- `src/platforms/tui/hooks/useShimmerFrame.ts`（帧驱动，setInterval + 卸载清理）
- `src/platforms/tui/components/ShimmerText.tsx`（组装渲染，可选 spinner）
