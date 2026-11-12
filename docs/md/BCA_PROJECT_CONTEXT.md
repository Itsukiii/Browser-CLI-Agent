# BCA — 项目总纲与跨会话共享上下文

> **文件角色：** 项目级共享背景文件（Project Context）。供 ChatGPT 项目中的全部子会话读取，并作为每份子系统开发任务 MD 的共同前置上下文。
>
> **项目名称：** Browser CLI Agent（BCA）  
> **版本：** v0.2（Protocol 2 接入基线）  
> **更新日期：** 2026-11-12  
> **当前状态：** BCA-00 已基于 Codex 交接报告完成阶段验收；公共接口基线为 `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`；BCA-01 已获准启动。仓库代码与测试尚未经架构主会话独立复核。

## 1. 项目背景

BCA 是一个面向**指定浏览器页面**的轻量级感知与输入控制框架。用户在命令行终端查看页面的结构化信息，并通过输入命令控制目标页面。

系统从浏览器获取截图或其他页面信息，由插件完成页面内容识别、结构化及展示格式生成；用户输入经插件映射为标准化动作后，由 Core 调用浏览器能力执行。框架面向不同网页复用底层能力，而不同网页的识别与交互策略由插件提供。

首个具体适配对象为网页游戏**雀魂（Mahjong Soul）**，优先采用截图和图像匹配的视觉识别流程。整个框架的识别来源保持开放，后续可按 Provider 机制接入 DOM 等其他页面数据来源。

### 1.1 核心数据链路

```text
观察链：目标页面 → Browser Adapter / Capture Provider → Frame
      → 插件识别与解析 → PageState → State Store → CLI 展示

操作链：CLI 输入 → Command → 插件命令解析与动作映射
      → Action → Input Provider / Browser Adapter → 目标页面

横向支撑：Provider Registry · Scheduler · Event Bus · Plugin Manager
          Protocol / Models · Config · Logging
```

### 1.2 设计取向

- **通用 Core，页面专属 Plugin：** 核心仅处理浏览器能力、运行生命周期及通用数据传递；具体页面语义归插件。
- **识别方式开放：** 插件使用统一能力接口获取所需数据。雀魂插件从视觉识别起步，Provider 可扩展。
- **低延迟、轻量化：** 采集与命令输入解耦，识别优先处理最新有效帧，按语义状态变化更新终端。
- **接口先行：** 公共协议是多个子系统并行开发的约束基础；数据模型、错误和坐标语义先统一。
- **配置驱动素材：** 使用 Manifest 定义对象语义与识别映射，使用 Profile（如 INI）选择具体视觉资源；同一对象可按显示场景使用多个模板。
- **单仓库协作：** 所有代码、文档、插件和测试置于一个 `bca/` 主目录下。

## 2. 技术方案基线

以下为当前规划基线；实际选型若在子系统开发中变化，应在主会话协调并更新本文件及相关规范。

| 项目 | 当前方案 |
| --- | --- |
| 主要语言 | Python 3.12+（BCA-00 已在 Python 3.14.7 / Windows 测试；3.12/3.13 待验证） |
| 运行平台 | 优先 Windows 开发与使用 |
| 浏览器 | 优先 Chromium / Microsoft Edge |
| 浏览器连接 | 优先 Chrome DevTools Protocol（CDP） |
| 图像处理 | 优先 OpenCV 与 NumPy；具体依赖在视觉模块阶段落实 |
| CLI | 选择支持异步输入与稳定刷新输出的终端组件，具体框架待 CLI 子系统确定 |
| 配置文件 | 项目级配置 TOML；资源 Manifest 使用 JSON；资源 Profile 使用 INI（初步方案） |
| 并发 | 以异步调度为基础；计算密集型识别任务按需要隔离 |
| 测试 | pytest，公共协议单元测试 + 截图样本回归 + 集成测试 |

实际截图帧率、资源占用和端到端延迟需通过原型测量确定。浏览器缩放、页面视口和截图图像之间的坐标转换应有统一约定。

## 3. 系统分层与职责

### 3.1 Core Layer（`src/bca/core/`）

**职责：** 浏览器连接、能力抽象、公共协议、运行时调度和插件生命周期。

| 子模块 | 主要职责 |
| --- | --- |
| `protocol/` | `Frame`、`PageState`、`Command`、`Action`、`ActionResult`、`Event` 等公共数据模型、版本及错误约定 |
| `browser/` | 浏览器连接、目标页面发现与绑定、CDP Adapter、连接状态及页面尺寸元数据 |
| `providers/` | Provider 注册与发现；Capture、Input 等能力的公开接口与实现接入 |
| `runtime/` | Scheduler、Event Bus、共享 State Store、任务取消、事件分发与运行控制 |
| `plugins/` | 插件发现、加载、上下文、生命周期管理以及插件的公共约定 |

Core 以通用能力接口服务插件；`core.protocol` 应保持最小依赖，作为各子系统共享的稳定基础。

### 3.2 Plugin SDK（`src/bca/plugin_sdk/`）

**职责：** 提供多个具体网页插件可复用的辅助能力。

| 子模块 | 主要职责 |
| --- | --- |
| `assets/` | Manifest 读取、Profile 解析、图像/图集资源加载、对象 ID 映射、缓存 |
| `vision/` | 裁剪、缩放、图像预处理、模板匹配与识别辅助工具 |
| `interfaces/` | 插件侧的识别、状态格式化、命令解析与动作映射辅助约定 |

SDK 的具体辅助能力由插件按需选择，统一以 Core 对外公开的协议和 Provider 为基础。

### 3.3 Application Layer（`src/bca/app/cli/`）

**职责：** 命令输入、状态展示、运行入口、配置与诊断。

主要组成：CLI Runtime、Input Handler、Command Router、Terminal Renderer、Session Controller、Diagnostics。终端输入与状态刷新应互不阻塞。

### 3.4 具体插件（`plugins/`）

- `example/`：最小示例插件，用于验证接口与端到端链路。
- `majsoul/`：首个实际插件，负责雀魂页面识别、客观状态输出、命令解析与点击等动作映射。

雀魂视觉素材以静态资源提取结果为优先来源，真实对局截图用于校准和回归测试；资源组织与识别逻辑分开管理。对于牌面等对象使用稳定语义 ID，同一 ID 可关联不同外观主题和使用场景。

## 4. 项目目录约定

```text
bca/
├── pyproject.toml
├── README.md
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── INTERFACES.md
│   ├── PLUGIN_SPEC.md
│   └── DEVELOPMENT_PLAN.md
├── src/
│   └── bca/
│       ├── __init__.py
│       ├── core/
│       │   ├── protocol/
│       │   ├── browser/
│       │   ├── providers/
│       │   ├── runtime/
│       │   └── plugins/
│       ├── plugin_sdk/
│       │   ├── assets/
│       │   ├── vision/
│       │   └── interfaces/
│       └── app/
│           └── cli/
├── plugins/
│   ├── example/
│   └── majsoul/
├── tests/
│   ├── core/
│   ├── plugin_sdk/
│   └── app/
└── configs/
    └── default.toml
```

此目录是规划基线。正式开发后以仓库实际文件和已更新的架构文档为准。

## 5. 公共接口与协作契约

### 5.0 当前已交付基线（BCA-00）

- **工程版本：** `browser-cli-agent 0.2.0`；**公共协议版本：** `PROTOCOL_VERSION=2`。
- **类型体系：** 标准库 `dataclass`（冻结且关键字初始化）、`StrEnum`、`Protocol`；Python 内部传递类型化对象，跨外部边界使用显式 JSON codec。
- **公共模型：** `bca.core.protocol` 包含 `Viewport`、`Frame`、`PageState`、`Command`、`Action`、`ActionResult`、`ErrorDetail`、`Event` 等；codec 为 `to_dict`、`to_json`、`from_dict`、`from_json`。
- **截图：** `Frame` 持有 PNG/JPEG 编码 `bytes`，按不可变共享使用；默认 JSON 输出元数据，图像 Base64 需显式启用。
- **坐标：** Frame 截图坐标通过携带的视口/采集元数据映射至 **CSS viewport** 输入坐标；DPR、滚动和裁剪偏移的实际处理以仓库 `docs/INTERFACES.md` 为准。
- **异步契约：** `bca.core.providers` 的 `Provider.start/close`、`CaptureProvider.capture(page_id) -> Frame`、`InputProvider.execute(action) -> ActionResult` 为 async；包含 `ProviderLookup`、`ProviderRegistry`。`bca.core.runtime` 提供 async `StateSink.publish(PageState)`、`EventSink.emit(Event)` 背压接口。
- **插件契约：** `bca.core.plugins` 提供 `PluginMetadata`、`PluginConfig`、`PluginContext`、`Plugin` Protocol；生命周期与观察/命令处理异步，文本解析与格式化同步。
- **时间：** 带 UTC 时区的 `datetime`，JSON 保留微秒；耗时与超时使用单调时钟。
- **状态责任：** Runtime 调用 `observe()` 后执行一次 `publish()`，按顺序 await 动作执行；错误与取消需有明确处理。
- **测试证据：** Codex 报告 Windows / Python 3.14.7 下 pytest `82 passed / 0 failed`，mypy strict、Ruff、打包、离线安装 smoke test 通过；主会话未独立复测。
- **后续核对：** Git 仓库尚未初始化；Python 3.12/3.13 运行矩阵和真实浏览器集成测试待完成。

完整字段、校验条件、异常类型及代码位置，以实际仓库 `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md` 和源码为准。


### 5.1 关键数据对象

| 对象 | 语义 | 典型流向 |
| --- | --- | --- |
| `Frame` | 截图数据及采集时间、尺寸、视口、坐标元信息 | Capture → Plugin |
| `PageState` | 插件输出的结构化页面状态，关联来源及状态版本 | Plugin → Core → CLI |
| `Command` | 用户输入归一化后的指令及参数 | CLI → Plugin |
| `Action` | 鼠标/键盘等标准化输入动作与目标 | Plugin → Input Provider |
| `ActionResult` | 动作执行结果、错误与时间信息 | Provider → Core / CLI |
| `Event` | 生命周期、页面、状态或动作相关事件 | Core / Plugin → Subscribers |
| `PluginContext` | 插件访问 Provider、配置等运行环境的上下文 | Core → Plugin |

详细字段、同步异步约定、坐标变换、序列化及兼容规则，以 `docs/INTERFACES.md` 和仓库的实际 `core.protocol` 定义为准。

### 5.2 依赖方向

1. `core.protocol` 作为公共基础层。
2. 浏览器、Provider、Runtime 和 Plugin Manager 使用公共协议。
3. Plugin SDK 使用公开的 Core 协议与能力接口。
4. 具体插件通过公开接口使用 Core 和按需选用的 Plugin SDK。
5. CLI 通过公开接口调用 Core 和展示插件返回的状态。

当跨模块需求涉及共享模型、Provider 接口或插件生命周期时，应先在架构主会话确认接口变更，再同步给受影响的子会话。

### 5.3 文档效力与更新顺序

为减少并行开发造成的接口分叉，采用下列约定：

- **本文件 `BCA_PROJECT_CONTEXT.md`：** 稳定的项目背景、总体设计、模块地图和协作规则。
- **`docs/INTERFACES.md` 与已实现的 `core.protocol`：** 当前实际公共接口契约。若文档与代码出现不一致，先记录问题并协调修正。
- **`docs/ARCHITECTURE.md`、`PLUGIN_SPEC.md`、`DEVELOPMENT_PLAN.md`：** 已确认的架构细节、插件规范和阶段计划。
- **各 `BCA-XX_*.md`：** 单次或单个子系统的任务范围、验收条件和交付物。

任务文档须注明依赖的公共协议版本或基线。**Protocol 1→2 为破坏性变更**，后续模块使用 Protocol 2，按仓库实有导出名称和参数调用。共享源文件的内容发生实质变化时，更新本文件的状态和关联任务索引，必要时重新同步到 ChatGPT Project 的共享来源。

## 6. 子会话任务地图

| 编号 / 会话建议名 | 子系统 | 交付目标 | 主要前置依赖 | 状态 |
| --- | --- | --- | --- | --- |
| `BCA-00 / Protocol` | 项目初始化与公共协议 | 仓库骨架、公共模型、Provider/Plugin 接口、基础测试与文档 | 本项目总纲 | **阶段验收完成（依据 Codex 报告，Protocol 2）** |
| `BCA-01 / Browser` | 浏览器与底层能力 | CDP 连接、页面绑定、截图、输入、坐标转换 | BCA-00 / Protocol 2 | **任务文件 v0.2 已生成，可启动子会话** |
| `BCA-02 / Runtime` | 调度、事件与状态 | Scheduler、Event Bus、State Store、任务运行管理 | BCA-00，按需使用 BCA-01 | 规划中 |
| `BCA-03 / Plugin System` | 插件管理 | 插件发现、加载、上下文与生命周期 | BCA-00、Runtime 接口 | 规划中 |
| `BCA-04 / Vision & Assets` | 视觉工具与资源管理 | Manifest/Profile、素材加载、识别辅助库、样本测试 | BCA-00 | 规划中 |
| `BCA-05 / CLI` | 终端应用 | 命令输入、状态展示、运行控制与诊断 | BCA-00、Runtime 与 Plugin 接口 | 规划中 |
| `BCA-06 / Majsoul` | 雀魂适配插件 | 游戏素材接入、画面信息识别与输入映射 | Browser、Plugin System、Vision、CLI | 规划中 |
| `BCA-07 / Integration` | 系统集成与验证 | 端到端测试、稳定性、延迟和资源占用评估 | 各相关模块 | 规划中 |

编号用于任务追踪；随着接口稳定，各子系统可以按依赖关系并行推进。**“规划中”不表示已开发，“任务文档已生成”不表示通过验收。**

## 7. 子会话标准工作流程

1. **主会话创建任务：** 按编号生成一份专属 `BCA-XX_*.md`，说明目标、负责目录、接口依赖、验收方法和交付说明。
2. **子会话读取上下文：** 先读取本总纲，再读取自己的任务 MD，并参考仓库中的当前共享接口文档。
3. **子会话讨论方案：** 明确必要实现细节与模块接口，形成交给 Codex 的提示词。
4. **Codex 开发：** 在同一个 `bca/` 工作目录中实现对应子系统并执行测试。
5. **提交结果摘要：** 回报实际变更文件、接口变化、测试结果、遗留事项和需要协调的决策。
6. **主会话同步状态：** 更新任务索引、总纲和受影响的公共文档，再协调下一个阶段。

### 7.1 子会话沟通原则

- 每个开发会话以自己的任务 MD 为当前工作范围。
- 仅讨论和描述需要实现的功能及必要约束，保持需求聚焦。
- 公共接口变更须同步主会话，并在任务文档或接口文档中明确。
- 阶段产物是交给 Codex 的**开发提示词**与任务说明；代码实现由 Codex 负责。
- 关键设计决策和任务状态保存在共享文件中，不能仅依赖聊天记录或跨会话记忆。

### 7.2 新子会话开场文字（可直接复制）

> 本会话属于 Browser CLI Agent（BCA）项目，负责 `BCA-XX / <子系统名称>`。请先读取 ChatGPT Project 共享来源 `BCA_PROJECT_CONTEXT.md`，再读取本会话专属任务文件 `BCA-XX_*.md`。以当前仓库的 `docs/INTERFACES.md` 等已确认规范为公共接口基准。先讨论设计和实施方案，随后输出用于 Codex 开发的提示词；公共接口变更提交架构主会话协调。

## 8. 当前进度与接续事项

截至 **2026-11-12**：

1. `BCA-00_Protocol.md` 已执行阶段性交接；同步依据为 `BCA-00_MAIN_SYNC.md`（根据 Codex `BCA-00_HANDOFF.md` 整理）。公共协议采用 `browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2`。
2. Codex 报告 82 项 pytest 测试通过，mypy strict、Ruff、打包和离线安装检查通过；主会话未独立验证实际仓库。
3. 已创建 `BCA-01_Browser.md`（v0.2），可以启动 Browser 子会话，首先核对仓库实际协议，再讨论 CDP 接入和 Provider 实现。
4. 后续安排 Git 初始化、Python 3.12/3.13 运行矩阵及端到端浏览器测试；每阶段同步完成情况、接口变化和实测数据。
5. 若后续需调整公共协议，由架构主会话协调版本、仓库规范和各子会话任务文件。

### 8.1 文件索引

- `BCA_PROJECT_CONTEXT.md` — 全局总纲（本文件，v0.2）。
- `BCA-00_Protocol.md` — BCA-00 原始任务定义。
- `BCA-00_MAIN_SYNC.md` — BCA-00 阶段性交接摘要（证据范围见文件说明）。
- `BCA-01_Browser.md` — BCA-01 任务定义（v0.2）。
- 仓库 `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md` 和 `src/bca/core/` — 实际接口及具体实现。

---

**维护约定：** 由架构主会话维护本总纲。每次更新应修改顶部版本 / 更新日期，并同步“子会话任务地图”和“当前进度”；各子会话以最近更新的共享来源为准。
