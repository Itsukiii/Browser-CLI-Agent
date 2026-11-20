# BCA — 项目总纲与跨会话共享上下文

> **文件角色：** 项目级共享背景文件（Project Context）。供 ChatGPT 项目中的全部子会话读取，并作为每份子系统开发任务 MD 的共同前置上下文。
>
> **项目名称：** Browser CLI Agent（BCA）  
> **版本：** v0.5（BCA-03 Plugin System 正式验收基线）  
> **更新日期：** 2026-11-20  
> **当前状态：** BCA-00 / Protocol、BCA-01 / Browser、BCA-02 / Runtime、BCA-03 / Plugin System 均完成阶段验收。BCA-03 交付提交为 GitHub `main` 的 `477c443e0adfd726a9cb77b1093616ed30529ec0`，架构主会话已核对实际源码与交接材料。公共接口基线为 `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`；后续进入 BCA-04 / Vision & Assets 规划。

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
| 主要语言 | Python 3.12+（已在 Windows / Python 3.14.7 测试；3.12/3.13 实机矩阵待验证） |
| 运行平台 | 优先 Windows 开发与使用 |
| 浏览器 | 优先 Chromium / Microsoft Edge |
| 浏览器连接 | 已交付本机回环 Chromium / Edge CDP 适配；BCA-01 实测 Edge 157 / CDP 1.3 |
| 图像处理 | 优先 OpenCV 与 NumPy；具体依赖在视觉模块阶段落实 |
| CLI | 选择支持异步输入与稳定刷新输出的终端组件，具体框架待 CLI 子系统确定 |
| 配置文件 | 项目级配置 TOML；资源 Manifest 使用 JSON；资源 Profile 使用 INI（初步方案） |
| 并发 | 以异步调度为基础；计算密集型识别任务按需要隔离 |
| 测试 | pytest，公共协议单元测试 + 截图样本回归 + 集成测试 |

BCA-01 已完成截图、坐标与输入闭环；BCA-02 在受控 Edge 页面完成截图→识别→状态提交→点击→再观察的真实联调及六类传输故障注入。实际雀魂 WebGL 页面、后台行为、长时间运行及全系统端到端性能留待相应集成阶段评估。

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
- **后续核对：** GitHub 仓库已建立；BCA-01 已完成受控 Edge 页面真实集成测试；Python 3.12/3.13 实机矩阵及真实雀魂 WebGL 场景留待后续验证。

完整字段、校验条件、异常类型及代码位置，以实际仓库 `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md` 和源码为准。


### 5.0.1 已交付 Browser 实现（BCA-01）

- **GitHub：** https://github.com/Itsukiii/Browser-CLI-Agent （默认分支 `main`；2026-11-16 交接审查记录的提交 `19df477547c26a4131d96191a8bb8bdb8362a4ea`）。子会话接入时应核对当前仓库版本，必要时以该已验收提交作为参考。
- **公开入口：** `bca.core.browser.BrowserSession`，异步 `connect/list_targets/bind/refresh_target/unbind/send/close`；明确页面绑定、`session_id`、`generation` 和连接状态。低层 `CDPConnection`、`TargetManager` 供 Browser 内部使用。
- **截图能力：** `BrowserCaptureProvider(session, *, timeout=10.0)`，实现 `capture(page_id)`，并提供 Browser 专属 `capture_region(page_id, *, x, y, width, height)`；实际交付 PNG；Frame 持有不可变编码字节，`width/height` 为 PNG 实际像素尺寸。
- **输入能力：** `BrowserInputProvider(session, *, timeout=10.0)`，实现 `execute(Action)`，支持协议定义的七类动作；报告输入状态、失败诊断及 `input_state_uncertain`。
- **坐标规则：** 统一使用 `Frame.pixel_to_css(px, py)` 转换为 CSS viewport 坐标，再传给 Action；输入端无需再次应用 DPR、滚动偏移或采集缩放。
- **所有权：** 上层拥有 `BrowserSession`，Session 拥有 CDPConnection；Capture/Input Provider 借用 Session，ProviderRegistry 只负责注册与发现。连接、绑定和 Provider 启停由上层显式编排。
- **并发与取消：** 同一 Provider 内调用串行，Capture 与 Input 之间的全局顺序由 Runtime 管理；取消后需等待在途任务结束，按 Input.close → Capture.close → Session.close 收尾。
- **观察新鲜度：** Frame 没有 generation；上层在观察时额外记录连接、会话、generation 与几何上下文，输入前确认仍适用。导航、重绑定、滚动、resize 等变化可触发重新观察。
- **结果语义：** `ActionResult.SUCCEEDED` 表示输入已被确认，不等同于网页状态达到预期。执行结果不确定时由上层处理显式恢复，按已知状态重新建立操作上下文。
- **文档权威来源：** 仓库 `docs/BROWSER.md`、`docs/BCA-01_MAIN_SYNC.md`、`docs/INTERFACES.md` 及 `src/bca/core/browser/` 的实际导出和源代码。

**验收证据（2026-11-16）：** BCA-01.1～01.4 正式验收 Accepted；Codex 报告 Windows / Python 3.14.7 / Edge 157.0.4341.60 下 pytest **285 passed / 0 skipped**，mypy strict、Ruff、wheel/sdist 通过；真实受控浏览器完成 **18/18** 次 PNG → Frame.pixel_to_css → Action → DOM 闭环（DPR 1/1.5/2、全图及区域截图），最大整数坐标误差 **0.75 CSS px**。含新鲜度/几何检测的观察和点击调用中位数分别为 **62.606 ms / 7.933 ms**，不等于裸 Provider 性能。正式验收已核对 GitHub 源码和交接证据，但架构主会话没有在用户 Windows 机器独立复测。

### 5.0.2 已交付 Runtime 实现（BCA-02）

- **已验收版本与源码：** BCA-02.1～02.4 完成，GitHub `main` 的交付提交 `550cdfa0b042e4cee95f0d7f53e88a7d84d62c43`（提交标题 `BCA-02`）；2026-11-17 架构主会话读取了最新源码及关键回归测试并完成**静态快速审查**，未发现阻塞交接的明显问题。源代码检查不等于重新运行测试；测试数字来自 Codex 交接报告。
- **公开入口：** 从 `bca.core.runtime` 导入 `StateStore`、`EventBus`、`Scheduler`、`ObservationPipeline`、`ActionPipeline`、`BrowserFreshness`、`RuntimeController` 及相关快照、策略、批次模型。精确参数和导出以仓库 `docs/RUNTIME.md`、`docs/INTERFACES.md` 与源码为准。
- **状态存储：** `StateStore.publish(PageState)` 每次成功提交令独立 Runtime `version` 加一；`snapshot()` 获取最新 `StateSnapshot`；`wait_for_update(after_version)` 只保证返回更新后的最新快照，不保证逐版本历史回放。`PageState.sequence` 是插件业务序号，不等于 Runtime 版本。每个观察通道由一方独占发布责任。
- **事件分发：** `EventBus` 按订阅者有界 FIFO 分发，缺少容量时对发布方施加背压；同一次提交对有效订阅者原子广播，订阅者关闭后退出背压集合。事件用于通知，不是业务执行成功证明；状态提交与事件发出并非跨组件事务。
- **调度与观察：** Scheduler 默认 100 ms 周期、单次在途、跳过过期 tick、合并立即请求；支持 `start/pause/resume/stop`。ObservationPipeline 按 `begin → observe → validate → publish → on_commit → notify` 执行，单次有效观察仅提交一次。超时/取消/失败有独立状态与诊断。
- **动作批次：** `ActionBatch`、`ActionObservationRef`、`BatchResult`；ActionPipeline 默认 **32 个等待批次 + 1 个执行批次**，FIFO、逐条 await、首错停止、按观察上下文判定 STALE，取消后等待在途执行和 Provider 清理完成。`SUCCEEDED` 表示输入被确认，后续页面变化仍须观察验证；未知结果不自动重放。
- **观察新鲜度：** `BrowserFreshness` 使用真实 `policy.capture(provider)` 取得的 Frame 及 `source_frame_id` 建立来源关联，提交后生成当前进程有效的动作引用；执行前复核 Store 快照、Session/Target/generation、URL/timeOrigin、视口、DPR、滚动与缩放等上下文。统一通过 `Frame.pixel_to_css()` 转换坐标。指纹不能保证 DOM 完全不变，也不能消除检查与送达间的 TOCTOU。
- **统一协调与生命周期：** `RuntimeController` 通过共享锁协调观察与动作整批执行；`pause` 仅暂停观察，动作通道可独立 READY/BLOCKED。观察或输入回调不得 await 自身 Controller 的生命周期/提交接口，以免形成自锁。Runtime 拥有自己的队列、锁和工作任务，但借用 Browser Session/Provider/Store/Bus，外部组合入口负责资源最终释放。
- **恢复约束：** 未知输入状态保守 BLOCKED；现有 Browser 策略通过来源可证明的**新 Target** 与新 Provider、重新观察的引用进行显式恢复。旧动作队列不因恢复而重新执行；不得将过期令牌换成新令牌后重发旧坐标。
- **建议组合关闭顺序：** Controller.stop 并等待在途清理 → Plugin.stop/close → Input.close → Capture.close → 清理自建目标并 Session.unbind/close → StateStore/EventBus.close 与订阅者收尾。资源由实际 owner 关闭，不通过 Registry 隐式释放。
- **交付测试：** Codex 在 Windows / Python 3.14.7 / Edge 157 环境报告 Runtime **165 passed**、全量 **450 passed / 0 skipped**；mypy strict（51 个源码文件）、Ruff 与 wheel/sdist 构建通过。真实集成包括完整截图→像素识别→点击→再观察，以及 **6 类**传输故障注入；全部退出后无在途任务、新增目标或连接残留。Python 3.12/3.13 与长时压力测试仍待验证。
- **性能依据：** 同条件前后测试的“提交至新状态”中位/p95 **66.78/109.22 ms → 62.01/90.36 ms**，但观察 p95 与持续吞吐变差，**不认定总体加速**。观察默认周期 100 ms 不等于实际稳定 10 Hz。结果参见 `docs/BCA-02.4_PERFORMANCE.json`。
- **权威文档：** GitHub `docs/RUNTIME.md`、`docs/BCA-02_MAIN_SYNC.md`、`docs/BCA-02.4_HANDOFF.md`、`docs/INTERFACES.md` 和 `src/bca/core/runtime/`。交接报告产生时提及的未提交工作区状态已由后续 GitHub `550cdfa` 推送取代。

### 5.0.3 已交付 Plugin System 实现（BCA-03）

- **验收与来源：** BCA-03.1/03.2 完成，GitHub `main` 提交 `477c443e0adfd726a9cb77b1093616ed30529ec0`（`BCA-03`），2026-11-20 架构主会话审查最新源码和交接文档，结论 **Accepted**。审查为静态核对，报告中的测试数未在主会话运行环境复测。此前“未提交、中文损坏”的审查快照已过时，GitHub 正式交接 MD 经核对为可读中文。
- **公共入口：** `bca.core.plugins` 原有 `Plugin`、`PluginMetadata`、`PluginConfig`、`PluginContext` 继续沿用；新增 `PluginCatalog`、`PluginLoader`、`PluginManager`、`ProviderLookupView`、`FreshnessCaptureAdapter`、`PluginRuntimeHost`，以及 `PluginDescriptor`、`PluginDiscoveryIssue`、`CatalogSnapshot`、`PluginLifecycleState`、`PluginSnapshot` 和插件加载/契约异常类型。准确 API 以 `src/bca/core/plugins/`、`docs/PLUGIN_SPEC.md` 为准。
- **发现与加载：** `PluginCatalog(roots)` 扫描显式可信根目录的直属子目录，静态读取 `plugin.toml`，按唯一 `plugin_id` 选择；重复 ID 的候选一并拒选。Manifest 包含 ID、版本、Protocol 2、能力声明、同步无参工厂。`PluginLoader` 按路径摘要隔离包模块，支持相对导入和失败回滚；装载插件意味着执行可信本机 Python 代码。
- **能力与上下文：** `PluginManager` 验证 Manifest 与实例 metadata 一致及必需 Provider 就绪，注入 `PluginContext(ProviderLookup, StateSink, EventSink, Logger, PluginConfig)`；`ProviderLookupView` 可覆盖特定能力的只读查询，但不拥有 Provider 生命周期。
- **观察来源适配：** `FreshnessCaptureAdapter` 通过 `BrowserFreshness.capture(raw_capture)` 取得真实 Frame，确保 `source_frame_id` 与观察上下文关联；插件只调用标准 CaptureProvider 并返回 PageState，Runtime 独占状态提交。截图像素坐标使用 `Frame.pixel_to_css` 转换。
- **生命周期：** Manager 管理 `load → initialize → start → stop → close`，对并发、取消与部分失败提供安全清理屏障；`PluginSnapshot` 记录状态、last_error、cleanup_status/error。Manager 的 CLOSED 不证明第三方资源一定已释放，Application 仍需核对诊断与插件自建任务。
- **命令与组合：** `PluginRuntimeHost(manager, controller, states)` 提供 `start/close/execute_text/snapshot/format_current_state`，在观察暂停屏障后配对 Store 快照及原始动作引用，通过 Plugin parse/handle 生成 `ActionBatch`，统一交由 RuntimeController 执行。`STALE` 与 `BLOCKED` 保留原有语义；输入确认不等于业务状态成功。
- **资源所有权：** Application 创建/关闭 Session、Capture/Input、Store/Bus、自己拥有的 Target；Host 管理 Controller 与 Manager；Adapter 借用 Capture。正常顺序为 `Host.close → adapter.close → Input.close → Capture.close → 自建 Target 清理 → Session.close → StateStore/EventBus.close`。显式恢复可由 Application 使用新 Target 和全新组合重新观察并提交新命令；旧动作不重放。
- **测试与性能：** Codex 报告 Windows / Python 3.14.7 / Edge 157 下全量 **533 passed / 0 skipped**（36 项显式真机）、无真机 **497 passed / 36 skipped**，mypy strict（66 源码文件）、Ruff 与 wheel/sdist 通过；受控页面三轮共 54 次像素识别点击全部成功，DPR 1/1.5/2、全图/区域及故障注入验证。`execute_text` median/p95 **6.34/18.90 ms**，命令到下一状态 **67.16/96.09 ms**；上述边界不等于原始截图或跨阶段可比基准。
- **仍待验证：** Windows 真实 symlink 权限环境、Python 3.12/3.13、长期压力/native RSS、实际雀魂 WebGL 页面及硬件/系统状态恢复。BrowserFreshness 指纹不能证明局部 DOM 始终不变，也不能消除 TOCTOU。
- **交接权威：** GitHub `docs/BCA-03_MAIN_SYNC.md`、`docs/BCA-03.2_HANDOFF.md`、`docs/BCA-03.1_HANDOFF.md`、`docs/PLUGIN_SPEC.md` 及当前 `src/bca/core/plugins/`。

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
| `BCA-01 / Browser` | 浏览器与底层能力 | CDP 连接、页面绑定、截图、输入、坐标转换 | BCA-00 / Protocol 2 | **正式验收通过（2026-11-16），已归档** |
| `BCA-02 / Runtime` | 调度、事件与状态 | Scheduler、Event Bus、State Store、观察与动作管线、RuntimeController | BCA-00 / Protocol 2；BCA-01 Browser | **正式验收通过（2026-11-17），已归档；静态快速审查通过** |
| `BCA-03 / Plugin System` | 插件管理 | 插件发现、加载、上下文与生命周期及 Runtime 组合 | BCA-00、BCA-01、BCA-02 | **正式验收通过（2026-11-20），已归档** |
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

截至 **2026-11-20**：

1. **BCA-00 / Protocol 已验收。** 公共基线为 `browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2`。
2. **BCA-01 / Browser 已验收。** CDP Session、PNG 全图/区域截图、七类输入与坐标映射已交付，参考提交 `19df477`。
3. **BCA-02 / Runtime 已验收。** StateStore、EventBus、Scheduler、ObservationPipeline、ActionPipeline、BrowserFreshness、RuntimeController 已交付，参考提交 `550cdfa`；交接报告记录 Runtime 165 项与全量 450 项测试通过。
4. **BCA-03 / Plugin System 已正式验收。** Catalog/Loader/Manager/ProviderLookupView/FreshnessCaptureAdapter/PluginRuntimeHost 可供下游依赖；交付提交 `477c443e0adfd726a9cb77b1093616ed30529ec0`，报告记录全量 533 项通过、24 项新增插件真机专项及 54 次矩阵点击成功。正式跨模块说明为 `docs/BCA-03_MAIN_SYNC.md`。
5. **下一步：BCA-04 / Vision & Assets。** 依据已验收的插件与 Runtime 公共接口，规划视觉解码、Manifest/Profile、模板与素材组织；BCA-05 CLI 随后可基于 PluginRuntimeHost 接入。
6. **后续验证关注点：** Python 3.12/3.13、长期压力和 native/Edge RSS、真实雀魂 WebGL 页面、后台操作以及跨模块真实性能测量。阶段测试报告仅对应其实际环境和测量边界。

### 8.1 已验收 Browser / Runtime / Plugin 对后续模块的交接重点

| 下游模块 | 接入要点 |
| --- | --- |
| BCA-02 / Runtime | 已完成并归档；为下游提供状态版本、事件背压、观察/动作编排、新鲜度授权与显式恢复接口 |
| BCA-03 / Plugin System | 已完成并归档；通过 Catalog/Loader 选择插件、Manager 注入 Context 并管理生命周期、Adapter 包装可信截图、Host 协调观察引用与命令提交。依赖契约见 `BCA-03_MAIN_SYNC.md` |
| BCA-04 / Vision & Assets | 解码不可变 PNG Frame，按真实像素识别；调用 `Frame.pixel_to_css()` 映射点击坐标 |
| BCA-05 / CLI | 显式选择 CDP endpoint/Target，配置插件可信目录和激活对象；通过 PluginRuntimeHost.execute_text 提交命令、读取 BatchResult 与后续状态；保留 Manager 清理诊断和 Application 资源 owner，STALE/BLOCKED 不自动重放 |
| BCA-06 / Majsoul | 插件负责识别、置信度、业务状态及动作映射；帧来源用 source_frame_id，坐标通过 Frame.pixel_to_css；须另做真实游戏场景验证 |
| BCA-07 / Integration | 扩展真实页面、后台行为、长时负载、native RSS/Edge 资源占用、多 Python 版本和跨模块性能测试 |

### 8.2 文件与仓库索引

- `BCA_PROJECT_CONTEXT.md` — 全局总纲（本文件，v0.5）。
- `BCA-00_Protocol.md` — BCA-00 原始任务定义。
- `BCA-00_MAIN_SYNC.md` — BCA-00 阶段交接摘要。
- `BCA-01_Browser.md` — BCA-01 原始任务定义（已完成）。
- `BCA-01_MAIN_SYNC.md` — BCA-01 正式跨模块交接说明。
- `BCA-01_FINAL_REVIEW.md` — BCA-01 正式验收结论与证据说明。
- GitHub `docs/BROWSER.md` — Browser 模块实际接口、键名表和实现细节。
- GitHub `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`src/bca/core/` — 当前公共契约及实现。
- GitHub `docs/BCA-01.4_HANDOFF.md`、`browser-artifacts/browser-integration-report.json` — BCA-01 交付与真实浏览器测试证据。
- `BCA-02_Runtime.md` — BCA-02 原始任务文件（已完成）。
- `BCA-02_MAIN_SYNC.md` — Runtime 正式跨模块交接契约。
- GitHub `docs/RUNTIME.md`、`src/bca/core/runtime/` — Runtime 实际导出和源码。
- GitHub `docs/BCA-02.4_HANDOFF.md`、`docs/BCA-02.4_CODE_AUDIT.md`、`docs/BCA-02.4_PERFORMANCE.json` — 交付、审计及性能证据（GitHub 提交 `550cdfa`）。
- `BCA-03_Plugin_System.md` — BCA-03 两阶段任务定义（已完成）。
- `BCA-03_MAIN_SYNC.md` — BCA-03 正式跨模块交接契约。
- GitHub `docs/PLUGIN_SPEC.md`、`src/bca/core/plugins/` — Plugin System 当前实现与接口。
- GitHub `docs/BCA-03.1_HANDOFF.md`、`docs/BCA-03.2_HANDOFF.md`、`docs/BCA-03.2_PERFORMANCE.json` — 插件阶段交接、测试与性能资料（提交 `477c443`）。

---

**维护约定：** 由架构主会话维护本总纲。每次更新应修改顶部版本 / 更新日期，并同步“子会话任务地图”和“当前进度”；各子会话以最近更新的共享来源为准。
