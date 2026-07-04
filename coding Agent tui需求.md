# **🧱 Coding Agent 落地架构与迭代路线全景蓝图 (Technical Specification)**

本文件为该 Coding Agent 项目的终极施工图纸，严格贯彻\*\*“大脑与嘴巴 Day 1 彻底解耦”\*\*的架构铁律。内容剔除所有务虚词令，全量收拢前期迭代的所有硬核交互与工程细节，可直接用于项目初始化或导出为 PDF 作为技术白皮书。

## **🔍 一、 需求全景矩阵 (The Requirements)**

### **1\. 极致的终端交互层 (Advanced TUI UX)**

* **经典布局（cc tui 模式）**：界面整体分为三大块。上方为流式思考与日志滚动区（自适应剩余高度）；中间为条件触发的上下文交互区；底部为独占的输入区。  
* **动态高度输入框**：输入框高度非固定。根据用户输入的文本长度或 Shift+Enter 换行符数量，在 **1 至 5 行之间动态伸缩**。超过 5 行时保持 5 行并触发内部垂直滚动。  
* **全局快捷键掌控**：支持 Ctrl+O 等系统级组合键。按下后，动态切换表现层布局状态（如全屏展开/收起 Agent 思考细节面板、切换 Diff 视图），不影响后台大脑运转。  
* **剪贴板图文无缝粘贴**：  
  * **文本粘贴**：支持大段代码、多行日志直接右键或 Ctrl+V 粘贴，确保 TUI 渲染层不阻塞、不撕裂。  
  * **图片粘贴（多模态预留）**：按下粘贴键时，若系统剪贴板内为图片数据（如屏幕截图），表现层通过系统桥接件静默将其捕获并写入 .agent/temp/ 目录，同时在输入框显示 \[Image: temp\_xxx.png\] 作为多模态上下文标记。

### **2\. 智能上下文与命令系统 (Commands & Context)**

* **/ 斜杠命令系统**：与主流 AI 工具对齐，在输入框输入 / 时触发。  
  * /edit \<需求\>：进入定向代码重构模式。  
  * /explain：解释当前上下文中选中的代码块。  
  * /test：为指定模块自动生成并运行单测。  
  * /index：显式触发本地静态代码图索引（Code Graph 构建）。  
  * /help：唤出高亮命令帮助指南。  
* **@ 上下文提及与树形组件**：用户在输入框打出 @ 时，输入框上方动态弹出一个**简明扼要的树形组件（Tree View）**，异步读取当前目录的文件树。支持键盘上下键导航与首字母模糊匹配，回车后将文件路径自动补全进输入框，锁定为模型上下文。

### **3\. 硬核 Agent 控制内核 (Advanced AI Kernel)**

* **多轮上下文与流式传输**：大模型 Token 必须以极高的帧率流式（Streaming）吐出，且具备完备的会话上下文剪裁与滚动记忆能力。  
* **格式约束与自愈纠错（Self-correction）**：代码修改或工具执行必须由 Zod 强类型 schema 锁定。一旦大模型输出的 JSON 损坏，大脑必须拦截 Error Log，自动将其作为下一次 Prompt 喂回大模型，触发**闭环自动重试修复**。  
* **时间旅行（Time-Travel 状态回放）**：基于有向图检查点（Checkpointer），允许用户随时撤销上一步操作，或者切回多轮对话中任意历史节点，修改用户输入并让 Agent 重新演进。  
* **多 Agent / 子 Agent 并行调度**：支持主图控制流分发任务给多个子图。例如：主 Agent 派发重构单，两个子 Agent 并行进行代码编写与合规性审查（Code Review）。  
* **Token 实时计费面板**：在 TUI 底部状态栏实时计算并显示当前会话消耗的 Input/Output Token 数量，并根据厂商标准换算为真实账单金额（如 Cost: $0.042）。

### **4\. 项目地图与工程增强 (Engineering Infrastructure)**

* **内置代码图（Code Graph）精准定位**：通过用户显式输入的 /index 命令，在不消耗大模型 Token 的前提下，本地静态解析 codebase，理清函数、类、文件之间的调用网状关系，存入本地，实现图增强检索（Graph-RAG）。  
* **Prompt 前缀缓存 (Prefix Caching)**：针对长上下文（长代码库）做费用优化，自动在厂商规定的 API 请求头中打上缓存控制标记。

## **🛠️ 二、 终极技术选型矩阵 (The Tech Stack)**

为了实现“单文件零依赖分发、毫秒级秒开、纯正 TS 生态闭环”，拒绝任何商业绑架与冗余网关，选型配置如下：

| 模块 | 落地选型 | 核心机制与优势 |
| :---- | :---- | :---- |
| **运行时 / 打包引擎** | **Bun** | 15ms 级冷启动秒开。内置 bun build \--compile，可将整个项目连同依赖一键打包成一个 **\~35MB 的单文件二进制程序**，用户端零依赖。 |
| **TUI 界面展现层** | **Ink (React)** | 基于 React 状态驱动理念（UI \= f(State)），完美契合数据流订阅。内置标准 Flexbox 布局引擎（Yoga），两行代码即可通过绝对定位锁死底部动态输入框。 |
| **Agent 状态机内核** | **LangGraph.js** | 官方正统 JS 版本，1:1 对齐 Python 版能力。提供强类型的 State、Nodes 和 Edges 编排，原生内置基于 SQLite 的时间旅行检查点机制。 |
| **结构化校验与纠错** | **@instructor-ai/instructor \+ Zod** | 纯净开源无私货。用 Zod 强类型定义代码输出规范，通过 Instructor 托管大模型原生客户端，自动触发 Self-correction 机制。 |
| **统一持久化底座** | **bun:sqlite** | Bun 内置的高性能 SQLite 驱动。**一专多能**：同时承载 LangGraph 检查点、Token 账本、Prompt 模板、以及 Code Graph 拓扑关系表。 |
| **静态分析 (Code Graph)** | **typescript (Compiler API)** | 用于在用户敲下 /index 时，静态扫描本地 .ts/.tsx 文件，提取 Export/Import 关系与函数/类符号（Symbols）。 |
| **系统剪贴板桥接件** | **Bun.spawn \+ 系统原生 CLI** | 拒绝庞大的三方库。利用 Bun 毫秒级派生子进程的能力，Mac 端调用 pngpaste，Linux 端调用 xclip，实现截图和多行文本的高效捕获。 |
| **云端网页投影 (Path B)** | **ttyd / gotty** | 极客的 Web-Terminal 桥接。云主机部署时，直接执行 ttyd ./agent，即可开端口在网页端完美投影 100% 体验的 TUI 图形界面。 |

## **📐 三、 “脑口分离”项目目录结构规范 (Architecture & Directory)**

代码仓库从 Day 1 起划定绝对的技术红线：src/core（大脑）禁止 import 任何与终端、颜色、光标、Ink 相关的依赖；src/platforms（嘴巴）禁止包含任何大模型调用和状态图重试逻辑。  
`src/`  
`├── core/                  # 🧠 核心大脑层（100% 纯逻辑与计算，支持跨平台复用）`  
`│   ├── contract.ts        # 契约：用 Zod 定义大脑吐给外界的标准结构化 JSON 事件`  
`│   ├── agent.ts           # 大脑主体：LangGraph.js 状态机与节点编排`  
`│   ├── llm.ts             # 模型实例化：Instructor + 厂商原生 SDK`  
`│   └── indexer/           # 索引引擎`  
`│       └── graph.ts       # Code Graph 构建器（解析 AST 并写入 bun:sqlite）`  
`├── platforms/             # 👄 表现层（嘴巴：多端适配器）`  
`│   ├── tui/               # 现阶段：TUI 适配器（Ink 渲染）`  
`│   │   ├── index.tsx      # TUI 入口，负责 useInput 快捷键捕获与组件挂载`  
`│   │   └── components/    # 视图组件：LogViewer、DynamicInput、TreeView、StatusBar`  
`│   └── web/               # 未来扩展：Web GUI 适配器`  
`│       └── server.ts      # 利用 Bun.serve 启动 WebSocket，将契约事件推给前端网页`  
`└── index.ts               # 统一启动开关`

## **🗺️ 四、 四阶段工程落地迭代路线 (The Roadmap)**

### **📌 Phase 1：硬核 TUI 骨架与现代交互 (MVP)**

* **核心目标**：画出动态高度输入框，打通快捷键与剪贴板，跑通流式对话。  
1. **构建数据契约 (contract.ts)**：定义核心生成器事件结构，包含 thinking、code\_stream、error 等标准 Zod Schema。  
2. **编写动态高度输入框**：在 Ink 中监听输入，计算文本的 \\n 数量，动态让 \<Box height={Math.min(lineCount \+ 1, 5)}\>, 配合全局 useInput 捕获 Ctrl+O，触发 React 侧边栏/详情面板的展开与隐藏。  
3. **编写剪贴板文本与图片获取模块**：封装 ClipboardService，利用 Bun.spawn 调取系统命令，确保 Ctrl+V 时大数据量不卡顿。  
4. **流式长对话跑通**：大脑实现为一个 AsyncGenerator。嘴巴层（Ink）消费该生成器，局部刷新组件状态，确保高频吐字时终端**完全不闪烁**。

### **📌 Phase 2：内核策略、Code Graph 与工具链 (Advanced Kernel)**

* **核心目标**：引入图状态机与本地代码图，赋予 Agent 读写文件与自我愈合的能力。  
1. **接入 LangGraph.js 状态机**：用 Graph 结构重构大脑。引入 MemorySaver（绑定 bun:sqlite）。编写测试用例验证多轮对话中的 **Time-Travel（历史回溯重放）** 功能。  
2. **实现 /index 与 Code Graph 引擎**：  
   * 在 SQLite 中建立 symbols 与 deps 表。  
   * 当用户在 TUI 敲下 /index 时，调用 TS Compiler API 扫描本地项目，通过 Generator 持续向 TUI 回传当前的百分比进度，Ink 渲染出高亮进度条。  
3. **实现 @ Mentions 树形组件**：输入框检测到 @ 时，激活行内树形组件，展示由 SQLite 缓存或本地目录读取的精简树形结构，支持键盘方向键和回车选中。  
4. **格式控制与 Self-correction**：集成 Instructor。定义修改文件的标准 Zod Schema。故意让大模型输出残缺的 JSON，验证状态机能否自动捕捉解析错误并进行自我修正重试。  
5. **基础工具链与 Token 计费**：接入 MCP SDK 或自定义写盘工具。在流式结束的 usage 结构中抓取 Token 数，计费后持久化并实时渲染在 Ink 的 \<StatusBar /\> 上。

### **📌 Phase 3：云端两栖与视觉大招 (Visual Boost & Cloud Deployment)**

* **核心目标**：实现不改动大脑代码的云主机分发与终端内联图片显示。  
1. **终端原生多模态视觉（Sixel 渲染）**：编写终端图片渲染器。当 Agent 修改了前端 UI 代码，后台静默启动 Playwright 截图，将其转化为 Sixel 转义字符。在 Ink 释放终端刷新的间隙，直接通过 process.stdout.write 将网页截图直观地打印在黑窗口里。  
2. **云端分发与 Path B 验证**：  
   * 执行 bun build \--compile \--target=linux-x64 ./src/index.ts \--outfile ./dist/agent 进行交叉编译。  
   * 将二进制包上传至云主机，使用 ttyd \-p 8080 ./dist/agent 代理。  
   * 在本地浏览器打开云端端口，验证在网页 Web-Terminal 中 100% 完美还原快捷键、动态输入、树形组件以及 Sixel 图片。

### **📌 Phase 4：全量图形化转型 (Full Web-GUI / A计划)**

* **核心目标**：彻底脱离终端限制，平滑升级为现代网页端图形 Agent 产品。  
1. **废弃旧表現层**：保持 src/core/（大脑、LangGraph、Code Graph、SQLite 计费）一字不改，直接废弃 src/platforms/tui。  
2. **启用 src/platforms/web/**：利用 Bun 内置的超级网络底座 Bun.serve 启动常驻常开的 WebSocket 服务。  
3. **对接现代网页前端**：编写标准的 React 网页。网页通过 WebSocket 连接 Bun 后端，直接接收 Phase 1 就定型好的标准 AgentEventSchema 结构化 JSON 事件。在网页端用高大上的 Monaco Editor（VS Code 同款内核）和 Canvas 画布组件，将其转化为完全媲美 Bolt.new 的商业级图形界面。