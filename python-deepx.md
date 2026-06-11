# Python 版 DeepX 技术选型文档

> 基于与 Go 版本的全面对比分析，2026-06-03

---

## 一、背景与目标

DeepX 是一个终端 AI 编程 Agent，目前使用 Go 实现（121 个 .go 文件）。本文档分析用 Python 技术栈重新实现的核心价值、主要优势和劣势，并给出具体的技术选型建议。

---

## 二、目标

1. **保留核心优化**：所有"省 Token"和"省时间"的架构设计（零 Token 路由、前缀缓存、上下文压缩）在 Python 版本中原样保留
2. **提升 AI 能力上限**：充分利用 Python 生态的 AI 工具链（LangChain、Embeddings、RAG、MCP 等）
3. **不牺牲用户体验**：TUI 体验达到甚至超过 Go 版本（Textual 的 CSS 能力被严重低估）
4. **合理的分发方案**：针对目标用户（Python 开发者）提供低摩擦的安装体验

---

## 三、需求分析

### 3.1 功能需求

| 功能模块 | 描述 | 复杂度 |
|---------|------|--------|
| LLM Agent 循环 | ReAct 风格的 Agent，支持工具调用、流式输出 | 高 |
| 零 Token 模型路由 | 本地规则判断走 flash/pro，无 LLM 调用 | 低 |
| 前缀缓存策略 | DeepSeek API 前缀缓存的精确重建，最大化命中 | 中 |
| 上下文压缩 | 自动压缩历史，保留最近轮次 + 20% budget | 中 |
| 会话持久化 | 可恢复的对话历史，gob → Python pickle/orjson | 低 |
| 工具系统 | 23+ 内置工具 + MCP 动态工具 | 中 |
| CodeGraph | 两阶段代码索引（语法优先，类型分析后台） | 高 |
| TUI 界面 | Claude Code 风格（消息列表 + 底部输入框） | 中 |
| MCP 集成 | Model Context Protocol 服务器和客户端 | 中 |
| 本地 OCR | PaddleOCR 替代多模态，按场景智能路由 | 中 |
| Web 搜索 | Bing 搜索 + HTML 提取 | 低 |
| 记忆系统 | 跨 Session 搜索 | 低 |

### 3.2 非功能需求

| 维度 | 描述 |
|------|------|
| Token 成本 | 最大化 DeepSeek 前缀缓存命中率（目标 ~99%）|
| 响应速度 | 主要瓶颈在 LLM API，UI 框架差异不可感知 |
| 分发体验 | 目标用户有 Python 环境，pip/pipx 安装零摩擦 |
| 开发效率 | 复用成熟库，减少重复造轮子 |

---

## 四、技术选型

### 4.1 核心框架

| 组件 | Go 版本 | Python 版本 | 说明 |
|------|---------|------------|------|
| Agent 循环 | 手动实现（Go 的 agent/llm.go）| **LangGraph**（声明式图结构）| LangGraph 是正确选择，见 4.7 节 |
| TUI 框架 | Bubble Tea | **Textual** | CSS 能力完整，等效替代 |
| CLI 参数解析 | cobra | Typer / Click | 等效 |
| 配置管理 | viper | Pydantic + YAML/TOML | Python 更简洁 |

**Textual 的能力再确认**（讨论后纠正）：

- 支持复杂 CSS 布局（flex、dock、变量、伪类）
- 支持 `dock: top/bottom/left/right` 固定定位
- 支持过渡动画（transition）
- Claude Code 风格布局（消息列表 + 底部输入框）完全可实现
- 和 Bubble Tea 是 TUI 领域的**同一级别**，不是妥协方案

#### 4.1.1 右侧状态面板（DeepX 原生特性，保留）

DeepX 右侧有一个实时显示端点、Token 数、缓存命中率的**状态面板**，是 DeepX 自己的产品设计亮点（非 Claude Code 专属）。让 API 成本对用户可见，是极好的细节体验。

**交互设计**：`Ctrl+T` 快捷键切换显示/隐藏，不干扰正常对话视野。

```
┌────────────────────────────────────┬──────────────────┐
│                                    │  DeepX Status    │
│   消息列表                         │  ────────────    │
│   (flex-grow: 1)                   │  Endpoint: flash │
│                                    │  Model: DeepSeek-v3│
│                                    │  ────────────     │
│                                    │  Input:   2,340   │
│                                    │  Output: 1,892    │
│                                    │  Cache:   1,105   │  ← 绿色（高命中率）
│                                    │  Hit%:    99.1%   │  ← 绿色
│                                    │  ────────────     │
│                                    │  Total: $0.0012   │
├────────────────────────────────────┤                  │
│  [输入框...........................] │                  │
└────────────────────────────────────┴──────────────────┘
                   Ctrl+T 切换面板显示/隐藏
```

**Textual 实现**：

```python
class TokenPanel(Static):
    """右侧状态面板 — DeepX 原生特性"""

    CSS = """
    TokenPanel {
        width: 200;
        dock: right;              /* 靠右固定 */
        background: $surface;
        border-left: solid $primary;
        padding: 1 2;
    }
    TokenPanel.open {
        display: block;
    }
    TokenPanel:not(.open) {
        display: none;
    }
    """

    def update(self, endpoint, model, input_tokens, output_tokens,
               cache_hit, cache_pct, total_cost):
        cp = cache_pct
        color = "green" if cp > 80 else "yellow"
        self.update_content(
            f"""\
[bold]DeepX Status[/bold]

[dim]─── Endpoint ───[/dim]
[.label dim]Model[/]  {model}
[.label dim]Mode[/]   {endpoint}

[dim]─── Tokens ───[/dim]
[.label dim]Input[/]   {input_tokens:,}
[.label dim]Output[/]  {output_tokens:,}
[.label dim]Cache[/]   [{color}]{cache_hit:,}[/]
[.label dim]Hit%[/]    [{color}]{cp:.1f}%[/]

[dim]─── Cost ───[/dim]
[.label dim]Total[/]   $ {total_cost:.4f}
"""
        )


class DeepXTUI(App):
    BINDINGS = [
        Binding("ctrl+t", "toggle_panel", "Status Panel"),
        Binding("ctrl+c", "cancel"),
        Binding("ctrl+o", "toggle_mode", "Auto/Review"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():  # 主区域 + 右侧面板并排
            with Container(id="main"):
                yield Header()
                yield MessageContainer(id="messages")
                with Container(id="input-dock"):
                    yield Input(placeholder="...")
            yield TokenPanel(id="token-panel")

    def action_toggle_panel(self):
        """Ctrl+T：切换状态面板"""
        self.panel_visible = not self.panel_visible
        self.query_one("#token-panel", TokenPanel).set_class(
            self.panel_visible, "open"
        )
```

**进阶：多层数据（连续按 Ctrl+T 展开更多）**

```
第一层（默认）：端点 + Token 总数
第二层（展开）：Round、Context 占用、Budget 剩余
第三层（再展开）：本次会话平均费用、估算总费用、缓存趋势
```

**核心价值**：让 API 成本透明，用户感知到"缓存策略是否在正常工作"、"这次会话大概花了多少钱"，这是 DeepX 的产品差异化细节。

### 4.2 AI / LLM

| 组件 | Go 版本 | Python 版本 | 说明 |
|------|---------|------------|------|
| LLM 调用 | `go-openai` / 直接 HTTP | `openai`, `anthropic`（官方 SDK）| Python 有官方 SDK |
| Agent 框架 | 手动实现 | **LangGraph**（推荐，详见 4.7）| 超集，包含 LangChain Agents 全部能力 |
| tiktoken 计数 | tiktoken-go | `tiktoken`（官方，最成熟）| Python 版本更成熟 |
| Embedding | 无 | `sentence-transformers`, OpenAI Embeddings | Python 独有能力 |
| RAG | 无 | LangChain RAG, Haystack | Python 完整生态 |

### 4.3 图片处理

| 组件 | Go 版本 | Python 版本 | 说明 |
|------|---------|------------|------|
| 多模态 | 不支持 | 可选接入 | 成本高 |
| 本地 OCR | PaddleOCR（14 个 Go 文件）| `paddleocr` / `easyocr` | Python 3 行，代码量减少 90%+ |

**OCR 智能路由方案**（讨论新增）：

```
用户发送图片
    │
    ├── 命中规则（文件名含 error/screenshot）→ 直接 OCR → 返回
    │
    ├── 不确定 → OCR 提取文字 → 质量评估
    │         ├── 含代码关键字（def, func, import...）≥ 2 个 → OCR
    │         ├── 含错误特征（Error, Exception, Traceback...）→ OCR
    │         ├── 含终端特征（\x1b[, $ , #...）→ OCR
    │         ├── 文字太少(<20) 或乱码率高(>30%) → 多模态
    │         └── 不确定 → LLM 轻量判断（最贵兜底）
    │
    └── 架构图/流程图/纯视觉内容 → 多模态 LLM 描述
```

三层路由的实际开销：规则匹配 0ms / OCR 提取 ~50-100ms / LLM 判断 ~500ms。绝大多数场景第一层命中，多模态只触发在真正不确定时。

### 4.4 代码理解

| 组件 | Go 版本 | Python 版本 | 说明 |
|------|---------|------------|------|
| 语法分析 | `gotreesitter` | `tree-sitter-python` | 等效 |
| 类型分析（Go）| `go/types` | `goat`（实验性）| 优先用 LSP 替代 |
| 类型分析（通用）| 无 | `tree-sitter-lsp` / pylance | Python 更丰富 |
| LSP 客户端 | 无 | `pygls`, `langkit` | 可按需接入 |

两阶段索引策略（保持和 Go 版本一致）：
1. 语法级图谱立即返回（tree-sitter）
2. 类型分析后台异步执行（需要时）

### 4.5 MCP 生态

| 组件 | Go 版本 | Python 版本 | 说明 |
|------|---------|------------|------|
| MCP SDK | 社区维护 | `FastMCP`（官方）+ LangChain MCP | Python 完整生态 |
| MCP Servers | 社区较少 | 大量 PyPI 包 | 主要差距在质量 |
| Claude Code 兼容 | 不兼容 | Skill 目录可直接复用（如果也迁移）| 同一语言生态 |

注：MCP 协议的 Python 生态实际上被低估了，`FastMCP` 来自 MCP 官方，能力完整。

### 4.6 会话与存储

| 组件 | Go 版本 | Python 版本 | 说明 |
|------|---------|------------|------|
| 历史序列化 | `gob` 二进制 | `pickle` / `orjson` + `jsonl` | JSON 更通用，可跨语言 |
| Session 目录 | `~/.deepx/sessions/` | `~/.deepx/sessions/` | 保持兼容 |
| Token 计数 | tiktoken-go | `tiktoken` | 等效 |
| 前缀签名 | `sha256.Sum256` | `hashlib.sha256` | 一模一样 |

---

### 4.7 LangGraph 架构设计（核心选型）

> 讨论后确认：LangGraph 是比 LangChain Agents 更正确的选择，差距是根本性的。

#### 为什么 DeepX 天然是 LangGraph 的场景

DeepX 的实际架构是**有状态的、循环的、多分支的**，而不是简单的线性链：

```python
# LangChain Agents：线性链，工具调用是链上的一步
chain = create_react_agent(llm, tools)
result = chain.invoke({"input": user_msg})  # 单次调用，结束

# LangGraph：状态机，工具调用是图上的节点，循环由框架管理
graph = StateGraph(DeepXState)
graph.add_node("agent", agent_node)      # ReAct 循环节点
graph.add_node("tools", tool_executor)  # 工具执行节点
graph.add_edge("agent", "tools")        # 显式边关系
graph.add_edge("tools", "agent")        # 循环回到 agent 判断

# 条件分支：agent 自己决定下一步去哪里
graph.add_conditional_edges("agent", decide_next, {
    "tools": "tools",          # 需要工具
    "plan": "plan_node",       # 需要规划
    "compressor": "compressor", # 上下文超限
    "model_switch": "model_switcher",  # 模型升级
    "end": END,                # 完成
})
```

**LangChain Agents 是链式执行（Linear），DeepX 的实际行为是图式执行（Graphical）**。

#### LangGraph vs LangChain Agents 核心差距

| 能力 | LangChain Agents | LangGraph | DeepX 场景 |
|------|-----------------|-----------|-----------|
| Agent 循环 | ✅ 单轮工具调用 | ✅ + 显式状态管理 | 必须 |
| 多轮对话状态 | 手动管理 | 内置 checkpointer | 必须 |
| 子 Agent 并行 | ❌ 串行 | ✅ 声明式并行（asyncio.gather）| CreatePlan 场景 |
| DAG 规划 | ❌ 需手动实现 | ✅ 原生支持 | CreatePlan 场景 |
| 条件分支路由 | 内部黑盒 | 显式 `add_conditional_edges` | 工具/规划/压缩路由 |
| 状态序列化/恢复 | 手动 | 内置 checkpointer | 会话持久化 |
| 流式输出 | ✅ | ✅ per-node 流式 | LLM 流式响应 |
| 循环终止条件 | 内置 100 轮 | 声明式 END 节点 | 必须 |

#### LangGraph 的完整架构想象

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint import MemorySaver

# DeepX 的状态定义
class DeepXState(TypedDict):
    messages: list[BaseMessage]           # 对话历史
    tools_used: list[ToolCall]            # 工具调用记录
    task: str                             # 当前任务
    subtasks: list[Task] | None          # CreatePlan 拆解的子任务
    results: list[Any] | None             # 子任务结果
    model: str                           # 当前模型（flash/pro）
    context_budget: int                  # 剩余 token 预算
    session_id: str                      # 会话 ID
    compress_triggered: bool              # 是否触发了压缩

workflow = StateGraph(DeepXState)

# 节点定义
workflow.add_node("agent", agent_node)           # 主 Agent 循环（ReAct）
workflow.add_node("tools", tool_executor)        # 工具执行
workflow.add_node("plan", plan_node)             # CreatePlan 分析
workflow.add_node("subagents", parallel_subagent_node)  # 并行子 Agent
workflow.add_node("compressor", compress_node)   # 上下文压缩
workflow.add_node("model_switch", switch_model_node)   # 模型切换

# 固定边（工具执行后必须回到 agent 判断）
workflow.add_edge("agent", "tools")
workflow.add_edge("tools", "agent")

# 条件边（agent 自己决定下一步）
def decide_next(state: DeepXState) -> str:
    last = state["messages"][-1]
    if last.tool_calls:
        return "tools"
    if last.needs_planning:
        return "plan"
    if state.get("compress_triggered"):
        return "compressor"
    if "switch_model" in str(last.content).lower():
        return "model_switch"
    return "end"

workflow.add_conditional_edges("agent", decide_next, {
    "tools": "tools",
    "plan": "plan_node",
    "compressor": "compressor",
    "model_switch": "model_switch",
    "end": END,
})

# 其他节点完成后回到 agent 汇总
workflow.add_edge("plan", "subagents")   # 规划后并行执行子任务
workflow.add_edge("subagents", "agent")  # 子任务完成后汇总
workflow.add_edge("compressor", "agent") # 压缩后继续
workflow.add_edge("model_switch", "agent")  # 切换模型后继续

# 编译（带 checkpointer = 会话持久化）
app = workflow.compile(
    checkpointer=MemorySaver(),
    store=FileStore("./sessions/"),
)

# 运行
config = {"configurable": {"session_id": "abc123"}}
async for event in app.astream_events(
    {"messages": [HumanMessage(content=user_input)], ...},
    config=config,
    stream_mode="messages",
):
    print(event, end="", flush=True)
```

#### LangGraph Checkpointing = 更优雅的会话持久化

Go 版本的会话持久化：

```go
// agent/session.go：手动 gob 序列化
type Manager struct {
    history []*Message
}
func (m *Manager) Save() error {
    enc := gob.NewEncoder(f)
    enc.Encode(m.history)  // 手动序列化
}
```

LangGraph 版本：

```python
# 一行配置，自动序列化所有状态
app = workflow.compile(
    checkpointer=MemorySaver(),  # 内存
    store=FileStore("./sessions/"),  # 持久化到文件
)

# 用户断开后重连：自动从 checkpoint 恢复
config = {"configurable": {"thread_id": "abc123"}}
state = app.get_state(config)  # 恢复到上次节点位置
```

**框架帮你管理"循环什么时候停"、"子任务并行怎么聚合"、"状态怎么序列化恢复"**，这些在 Go 里都是手动写的（约 2000 行代码）。

#### 子 Agent 并行（CreatePlan）实现

```python
async def parallel_subagent_node(state: DeepXState) -> DeepXState:
    """CreatePlan 的并行执行：独立子任务同时运行"""
    tasks = state["subtasks"]
    results = await asyncio.gather(*[
        run_subagent(t) for t in tasks
    ])
    return {"results": list(results)}

# Go 版本等价逻辑（手动 goroutine）
func runSubagents(tasks []Task) []Result {
    ch := make(chan Result, len(tasks))
    var wg sync.WaitGroup
    for _, t := range tasks {
        wg.Add(1)
        go func(t Task) {
            defer wg.Done()
            ch <- executeSubAgent(t)
        }(t)
    }
    go func() { wg.Wait(); close(ch) }()
    var results []Result
    for r := range ch { results = append(results, r) }
    return results
}
```

声明式（图结构）vs 命令式（goroutine + channel）的差距。

#### LangGraph 是 LangChain 的超集

```
LangChain        → 链式执行，适合简单 Agent
LangGraph        → 图式执行 = LangChain 超集 + 状态 + 循环 + 多 Agent
                → DeepX 的正确选择
```

如果将来要加 RAG、多 Agent 协作、复杂工作流，LangGraph 天然支持扩展，不需要重构架构。如果用 LangChain Agents，将来这些扩展很难加。

---

## 五、优势

### 5.1 AI 生态完整性（最重要）

Python 是 AI 时代的主语言，在 DeepX 的核心场景上有压倒性优势：

- **Agent 框架**：LangGraph 是 LangChain 的超集，声明式图结构原生支持多 Agent 并行、子任务调度、状态持久化，Go 需要手动实现同等逻辑（agent/llm.go + agent/subagent.go 约 2000 行）
- **Embedding + RAG**：LangChain RAG pipeline 是完整方案，Go 基本空白
- **Prompt 优化**：DSPy（自动 Prompt 优化）是 Python 独有，Go 无
- **OCR 集成**：`paddleocr` / `easyocr` 安装即用，Go 需要 14 个文件手动桥接

### 5.2 TUI 能力被低估

Textual（Rich 库作者开发）在讨论中被验证：

- **CSS 能力**：flex 布局、dock 定位、CSS 变量、伪类、过渡动画全部支持
- **组件化**：Component 类借鉴 React 模式，支持 reactive 状态、lifecycle hooks
- **Claude Code 布局**：`dock: bottom` + `height: 1fr` 完全可实现
- 实际上 Bubble Tea（Go）和 Textual（Python）是 **TUI 领域同一级别**，不是 Python 的妥协

### 5.3 开发效率

| 任务 | Go 版本 | Python 版本 | 节省 |
|------|---------|------------|------|
| Agent 循环 | 手动实现 ReAct | LangChain 10 行 | ~500 行 |
| OCR 集成 | 14 个 Go 文件 | 3 行 import | ~800 行 |
| MCP 工具注册 | 手动映射 | @tool 装饰器 | ~200 行 |
| Embedding | 无 | `sentence-transformers` 5 行 | ~300 行 |

预估 Python 版本总代码量：60-80 个 .py 文件（vs Go 的 121 个 .go 文件）。

### 5.4 性能在目标场景下足够

DeepX 的实际性能瓶颈：

```
LLM API 响应：100ms ~ 10s（绝对瓶颈）
UI 渲染：< 10ms（Textual Python vs Bubble Tea Go 差距 < 5ms）
OCR 提取：50-100ms（本地，无网络）
```

**UI 框架的 CPU 开销在实际使用中是不可感知的差异**。

---

## 六、劣势

### 6.1 单 binary 分发（唯一的真实短板）

| | Go | Python |
|--|---|--------|
| 分发 | `go build` → 单二进制，零依赖 | 需要 Python 环境 |
| 用户体验 | 下载即运行 | pip install / pipx install |

**但严重程度被高估**：

```bash
# Python 开发者安装 Python 工具的标准方式
pipx install deepx-ai    # 隔离安装，零依赖冲突，一行命令
# 或
pip install deepx-ai      # 标准 pip

# 对比 Go 版本
curl -L ... | tar -xz && ./deepx
```

DeepX 的目标用户是**愿意自己部署工具的开发者**，这类用户大概率有 Python 环境。真正需要单 binary 的是非 Python 用户，而这部分用户可能本来就不会选择 DeepX（它本身就是面向开发者的工具）。

如果必须追求单 binary，Python 也有方案：
- **PyInstaller**：打包成单文件，执行速度 ~2-5s（慢于 Go）
- **Nuitka**：编译成 C，接近原生性能
- **Docker**：容器化，零依赖（但引入了 Docker 要求）

### 6.2 Textual 的 JSX 缺失

这是 Ink（Node.js）vs Textual（Python）的真实差距：

| | Ink (Node.js + React) | Textual (Python) |
|--|---------------------|-----------------|
| 声明式 UI | ✅ JSX（业界最直观）| ⚠️ Python API 调用 |
| 响应式状态 | ✅ useState/useEffect | ✅ reactive + on_mount |
| 组件复用 | ✅ React 生态（大量 npm 包）| ⚠️ Textual 组件生态较小 |

Textual 的 Component 类在 v0.50+ 引入了更 React-like 的模式，架构思想上接近，但**语法上不如 JSX 直觉**。这是 Python 的真实差距，但影响有限（UI 逻辑比 UI 语法更重要）。

### 6.3 运行时有 GC 暂停

Go 的 GC 延迟远低于 Java/Python。在 DeepX 的场景（主要等待 LLM 网络响应）下，这不是瓶颈。但对于需要毫秒级 UI 响应的场景（如 vim 模式按键），Python 的 GC 可能导致轻微卡顿。实际影响极小。

---

## 七、Go 版本 vs Python 版本总对比

| 维度 | Go 版本 | Python 版本 | 胜出 |
|------|---------|------------|------|
| 单 binary 分发 | ✅ 原生 | ⚠️ 需要打包工具 | **Go** |
| AI 生态完整度 | ❌ 薄弱，需自造轮子 | ✅ 完整（LangChain, RAG, Embedding）| **Python** |
| MCP 生态 | ❌ 社区维护 | ✅ FastMCP 官方 | **Python** |
| OCR 集成 | ❌ 14 个文件手动封装 | ✅ 3 行 import | **Python** |
| TUI 能力 | ✅ Bubble Tea（Elm 架构）| ✅ Textual（CSS 完整）| 持平 |
| 开发效率（AI 应用）| ⚠️ 手动实现一切 | ✅ 组合成熟库 | **Python** |
| 性能（UI 渲染）| ✅ 极快 | ✅ 足够快 | 持平 |
| 性能（CPU 密集）| ✅ 强 | ⚠️ 一般 | **Go** |
| 内存占用 | ✅ 低 | ⚠️ 中 | **Go** |
| Ink 的 JSX 体验 | 不适用 | ⚠️ Python API 稍冗 | Node.js 优 |
| 前缀缓存策略 | ✅ 完整 | ✅ 完整 | 持平 |
| 零 Token 路由 | ✅ 完整 | ✅ 完整 | 持平 |
| 代码索引（Go 专用）| ✅ go/types | ⚠️ goat（实验性）| **Go** |

---

## 八、结论

### 8.1 可以完全用 Python 实现

每个核心模块都有等效或更好的 Python 实现。核心的"省 Token / 省时间"优化是**架构设计**，不是语言特性，Python 版本中原样保留。

### 8.2 Python 的主要收益

```
AI 能力上限：从"手写 Agent 循环" → "组合 LangGraph"
代码量：从 121 个 .go 文件 → 60-80 个 .py 文件
Agent 核心：从 agent/llm.go + agent/subagent.go（~2000 行手动循环）
         → LangGraph 声明式图（~200 行定义节点和边）
OCR：从 14 个 Go 文件 → 3 行 import
RAG / Embedding：从无 → 开箱即用
```

### 8.3 Go 版本的真实护城河

Go 版本的核心价值是：
- **单 binary 分发**（唯一的决定性优势）
- **作者的个人偏好**（Go 开发体验 + 自成一派的架构设计）

这说明 DeepX 的竞争优势是**对 API 行为的深度理解 + 精妙的缓存架构**，这些不依赖 Go 的特性。用 Python 重写，核心价值完全保留，体验可能更好。

### 8.4 建议

如果重写：

```
优先级高：
├── LangGraph 实现核心 Agent 架构（声明式图结构，替代 agent/llm.go + agent/subagent.go）
├── Textual 实现完整 TUI（dock 布局、CSS 主题、消息流）
├── 前缀缓存策略（核心价值，保留）
├── 零 Token 路由（核心价值，保留）
├── OCR 智能路由（三层决策）
└── 会话持久化（pickle + jsonl）

优先级中：
├── MCP 集成（FastMCP）
├── CodeGraph 两阶段索引
└── Web 搜索工具

可选（Python 特有优势）：
├── LangChain RAG pipeline
├── sentence-transformers Embedding
└── DSPy Prompt 优化
```