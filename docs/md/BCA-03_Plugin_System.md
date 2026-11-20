# BCA-03 / Plugin System — 插件发现、加载与运行生命周期

> **任务编号：** BCA-03  
> **子会话名称：** BCA-03 / Plugin System  
> **任务文件版本：** v0.2 · 2026-11-17  
> **阶段状态：** 已确定两阶段实施安排，待子会话核对代码并讨论设计  
> **项目仓库：** https://github.com/Itsukiii/Browser-CLI-Agent  
> **参考代码基线：** `main` / `550cdfa0b042e4cee95f0d7f53e88a7d84d62c43`  
> **公共协议：** `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> **前置阶段：** BCA-00 Protocol、BCA-01 Browser、BCA-02 Runtime 均已验收归档

## 1. 阶段目标

在已完成的 Core 与 Runtime 之上实现通用插件管理能力，使上层应用能够发现候选插件、校验元数据与能力需求、装载一个选定插件、初始化及管理其生命周期，并将插件的观察和命令处理入口规范地接入 Runtime。

BCA-03 的核心交付是**可复用的插件管理器及其组合入口**，以最小示例插件证明插件与 Browser/Runtime 可以协同工作。插件的页面业务逻辑留在具体插件中；Manager 负责可复用的接入流程和故障清理。

本阶段应沿用已经交付的 `Plugin` Protocol、`PluginContext`、`ProviderLookup`、`RuntimeController` 及 Protocol 2，优先复用实际源码契约。

## 2. 必须先读取的文档与源码

1. `BCA_PROJECT_CONTEXT.md`（v0.4）：项目架构、各模块边界、阶段状态与跨会话规则。
2. `BCA-00_MAIN_SYNC.md`：Protocol 2 类型、Provider、Plugin 约定。
3. `BCA-01_MAIN_SYNC.md`、`BCA-01_FINAL_REVIEW.md`：Browser 接口、输入语义和资源所有权。
4. `BCA-02_MAIN_SYNC.md`、`BCA-02.4_HANDOFF.md`：已完成的 Runtime、观察授权、动作协调及取消/清理约定。
5. 仓库 `docs/PLUGIN_SPEC.md`、`docs/INTERFACES.md`、`docs/RUNTIME.md`、`docs/ARCHITECTURE.md`。
6. 仓库 `src/bca/core/plugins/`、`providers/`、`runtime/`、`plugin_sdk/interfaces/`，`plugins/example/` 及现有测试。

实际 API 的完整签名与验证条件以当前仓库源码为准。参考提交只用于固定本阶段起点，开始实施前核对工作区版本。

## 3. 已确认的上游接口

### 3.1 插件契约（BCA-00）

`bca.core.plugins` 已导出：

- `PluginMetadata(plugin_id, version, required_capabilities=(), protocol_version=2)`；
- `PluginConfig(values={}, protocol_version=2)`；
- `PluginContext(providers, states, events, logger, config)`；
- `Plugin` Protocol：
  - `async initialize(context) -> None`
  - `async start() -> None`
  - `async observe() -> PageState`
  - `parse_command(text, *, source="cli") -> Command`（同步）
  - `async handle_command(command) -> tuple[Action, ...]`
  - `format_state(state) -> str`（同步）
  - `async stop() -> None`
  - `async close() -> None`

`metadata.required_capabilities` 用规范化字符串名称声明能力，`protocol_version` 当前为 2。插件可通过只读 `ProviderLookup` 查询能力，插件自身不拥有共享 Provider 的关闭权。

### 3.2 Runtime 与 Browser 契约（BCA-01/02）

- 观察：Runtime 调用插件 `observe()`，插件返回 `PageState`，由 `ObservationPipeline` 完成单次状态提交、提交引用关联和有界事件通知。
- 动作：插件 `handle_command()` 只生成有序 `Action`；上层根据当前 `ActionObservationRef` 构建 `ActionBatch`，由 `RuntimeController.submit()` 串行执行。
- Browser 新鲜度：使用 `BrowserFreshness`，实际截图通过 `policy.capture(raw_capture)` 归属当前观察；需要暴露标准 `CaptureProvider` 时由组合层包装并校验绑定页面。
- 组合协调：观察和动作共用 RuntimeController 的协调门；在生成依赖当前状态的命令时，结合现有 `pause`、StateStore 快照与引用进行正确编排。
- 资源所有权：Application 维护 BrowserSession、Provider、Store/Bus 等外部实例；Runtime 拥有自身任务，插件管理器管理插件实例及插件自身生命周期。`ProviderRegistry` 只注册/查询，不释放实例。
- 执行失败及取消：Runtime 的 `STALE/BLOCKED/FAILED/CANCELLED` 与 Browser 的输入不确定性是权威结果；插件管理器不得改变这些含义。

## 4. 责任范围与建议代码落位

| 落位 | 本阶段职责 |
| --- | --- |
| `src/bca/core/plugins/` | 插件目录、加载器、校验、管理器、生命周期及故障归档 |
| `plugins/example/` | 最小示例插件的适配和完整组合示范 |
| `tests/core/plugins/` | 发现、版本/能力检查、生命周期、清理和失败注入 |
| `tests/integration/` 或现有约定位置 | 插件→Runtime→Provider 的综合测试 |
| `examples/` | 可运行的插件装配和状态/命令闭环 |
| `docs/` | 插件管理、接口和使用流程文档 |

沿用项目既有布局与测试风格，开发前核对实际路径。

## 5. 功能需求

### 5.1 插件发现与装载

- 从明确配置的插件来源发现候选插件，形成可枚举的描述信息（插件 ID、版本、来源、能力需求及当前验证状态）。
- 按 `plugin_id` 显式选择、装载插件；支持项目内 `plugins/example/` 的实际发现与导入。
- 处理重复 ID、缺少入口、模块导入失败、元数据错误等情况，提供明确的诊断和稳定的错误类型。
- 明确插件实例创建方式、实例与模块的缓存边界，避免载入与运行阶段混淆。
- 插件加载属于执行本机 Python 代码的操作，发现来源及导入路径需要有明确配置和信任边界。

**待设计决策：** 使用固定插件目录、Python 导入路径或 entry points 作为初始发现形式；考虑当前业务插件尚未打包发布的现状，以及未来扩展的兼容方式。

### 5.2 元数据、版本与能力检查

- 插件管理器保证当前管理范围内 `plugin_id` 唯一。
- 在初始化前校验 `PluginMetadata` 的公开字段、`protocol_version` 与当前 Protocol 2。
- 检查 `required_capabilities` 能否由 `ProviderLookup` 提供，区分未注册、类型不匹配和暂时未就绪。
- 检查插件实例是否满足 `Plugin` 接口所需的属性和调用签名，运行时在关键结果边界验证类型。
- 插件元数据版本、协议版本、状态 Schema 版本保持独立含义；将兼容策略和错误语义写入文档。

### 5.3 上下文注入与生命周期管理

- 由 Core 创建 PluginContext，注入 `ProviderLookup`、StateSink、EventSink、Logger 和 PluginConfig。
- 统一管理 `load → initialize → start → stop → close`，明确实例状态、幂等、重启/终止行为以及并发调用边界。
- initialize 或 start 中途失败时完成插件自有资源清理，保证可观测的失败状态。
- 支持正常停止、重复停止、部分启动失败、取消与异常传播，并等待插件自行创建的在途任务完成。
- 管理器按调用方的资源所有权协定与 Runtime、Provider 协调清理；生命周期边界不得与 RuntimeController 的实际顺序冲突。

**待设计决策：** 管理一个活动插件还是多个插件；建议第一版按单个 Runtime 观察通道与一个活动插件建立完整契约，再允许目录中多个候选插件供选择。

### 5.4 与 Runtime 的实际组合

- 提供可复用的组合或接入辅助能力，将 `plugin.observe()` 接入 RuntimeController 的观察回调，并使用既有 StateStore/EventBus。
- 处理 BrowserFreshness 的截图来源授权：使用适配器把标准 CaptureProvider 查询与 `policy.capture(raw_capture)` 组合，确保 `source_frame_id` 源于当前有效观察。
- 将插件解析/命令映射与动作执行边界明确划分，提供可供后续 CLI 调用的接口或参考流程。
- 保证规范化动作请求使用生成动作时关联的观察引用；发生 `STALE` 时重新观察并重新生成动作，而不是更新旧批次的引用后直接重发。
- 对插件观察失败、命令错误、格式化异常、初始化中断及关闭失败给出确定的处理与诊断。

### 5.5 可观测性与接口文档

- 提供插件列表、实例生命周期状态、最近错误及基本诊断信息。
- 记录 plugin_id、插件版本、能力需求、状态转换及对应异常类别；保护用户输入与截图载荷。
- 输出公开的插件开发/装载说明，并注明 Runtime、Browser、Provider 的边界和资源 owner。

## 6. 两阶段实施与交接安排（已确定）

BCA-03 采用 **两阶段实施、一次正式验收**。前一阶段完成可供集成的插件系统，后一阶段集中进行真实浏览器闭环、故障回归、质量审查与跨模块交接。阶段划分是交付里程碑，具体开发提示词可以由子会话根据代码核对结果拆为更小的 Codex 执行批次。

### BCA-03.1 — Plugin Core 与 Runtime 接入

**目标：** 在现有 Protocol 2 / Plugin Protocol 上交付可调用的插件管理子系统，并用模拟 Provider/Runtime 完成可靠的功能闭环。

包括：

1. 确定插件来源与创建约定，支持多候选发现、显式选择和插件 ID 唯一性检查；定义装载/导入失败的诊断。
2. 完成协议版本、插件元数据、必需能力和接口形状校验，维护插件实例状态和可观测诊断。
3. 通过 `PluginContext` 注入只读 ProviderLookup、StateSink、EventSink、Logger 与 PluginConfig；管理 initialize/start/stop/close、重复调用、部分启动失败、取消和自有任务清理。
4. 完成插件 observe 与 RuntimeController 的组合，以及插件命令解析/动作生成到 ActionBatch 提交的协调入口或明确可复用的组合模式。
5. 依据 BrowserFreshness 的实际授权机制实现标准 CaptureProvider 适配，使插件的截图经过 `policy.capture(raw_capture)` 并正确关联 `source_frame_id`。
6. 更新核心文档、提供示例和模块级测试，明确各资源所有者与后续 CLI 调用约定。

**完成标准：** 插件可从已配置来源发现并加载；能力校验和生命周期经过测试；使用模拟观察/输入可验证从插件状态产生到 ActionBatch 结果的整条链路；接口与 BCA-00/01/02 保持一致。阶段结束输出 `BCA-03.1_HANDOFF.md`，明确公开入口、实际测试、剩余集成事项及是否影响公共协议。

### BCA-03.2 — 真实集成、回归与正式交接

**目标：** 基于 03.1 已交付的接口，在真实受控 Chromium/Edge 页面验证插件、Browser 与 Runtime 的稳定组合，完成质量与资源验收。

包括：

1. 使用 example 或专门的测试插件，完成真实页面截图 → 插件 observe → PageState/Store/Event → 命令映射 → ActionBatch → 浏览器输入 → 再观察的闭环，并关联 Frame/State/Action/Result ID。
2. 测试页面刷新、导航、滚动、resize、目标换绑、过期引用、Provider 未就绪、插件初始化/运行失败、取消与重复 stop 的处理路径。
3. 验证观察和命令串行约束、输入不确定状态的阻断语义，以及部分初始化/异常退出时插件和 Browser/Runtime 的所有权清理。
4. 记录真实与模拟测试覆盖、耗时和资源检查；执行全量 pytest、mypy strict、Ruff、wheel/sdist 构建，核实接口兼容性和回归结果。
5. 更新 `docs/PLUGIN_SPEC.md`、`docs/INTERFACES.md` 及必要的相关文档，完成代码审查、交付证据和跨模块接入说明。

**完成标准：** 真实插件闭环及故障/清理测试通过，形成 `BCA-03.2_HANDOFF.md` 和 `BCA-03_MAIN_SYNC.md`。其中 MAIN_SYNC 记录最终可依赖的插件发现/激活入口、上下文与生命周期契约、Runtime 组合接口、实际测试结果和 BCA-04/05/06 的接入条件。正式验收由架构主会话在核对交付和代码后作出。

## 7. 重点测试与验收

1. 多候选插件发现、唯一性、显式选择、非法入口、模块导入异常等结果确定且可诊断。
2. 插件 metadata / Protocol 2 / capability 检查可靠，缺少或未就绪能力能够被正确拒绝。
3. `initialize/start/stop/close` 在正常、部分失败、取消、重复调用中正确执行，插件自有任务被等待和清理。
4. Runtime 的观察只提交一次 PageState；Store 的运行时版本与插件业务 sequence 不混同。
5. 标准插件 CaptureProvider 入口能够通过 BrowserFreshness 正确建立真实 Frame 来源授权。
6. 插件命令转为 ActionBatch 后经 Runtime 提交，使用原观察引用，错误和 STALE/BLOCKED 保留正确语义。
7. 受控 Edge 真实插件闭环通过；提交/停止后没有残留的插件任务、Provider 所有权错误或测试 Target。
8. 结果包含实际版本、源码路径、复现实验、检查命令与输出，区分模拟测试和真实集成测试。

## 8. 跨模块协调与交付

- BCA-03 以现有 Plugin Protocol / Runtime / Browser 契约为基线；公共接口如需修改，先向架构主会话提交变更提案。
- SDK 的视觉匹配和素材管理由 BCA-04 实现；BCA-05 将使用插件发现/激活与命令组合接口；BCA-06 在此基础上完成雀魂具体插件。
- 03.1 完成后生成阶段交接报告；03.2 完成后统一生成正式跨模块 SYNC 与验收证据。每次均记录已实现能力、代码落位、测试结果、设计决策及遗留事项。
- 整体完成生成 `BCA-03_MAIN_SYNC.md`，至少包含：插件发现与实例化方式、公开 API、能力/版本检查、生命周期状态与所有权、Runtime 组合与命令流程、异常与取消语义、测试结果及 BCA-04/05/06 接入注意事项。
- 子会话先讨论实施方案和关键选型，再编写交给 Codex 的开发提示词；在统一 `bca/` 仓库开发。

## 9. 当前阶段状态

BCA-00/01/02 已验收。BCA-03 的目标、责任、两阶段实施安排与验收标准已确定，可启动专属子会话进行接口核对及设计讨论；实际实现细节在子会话确认后确定。共享 `BCA_PROJECT_CONTEXT.md` 暂保持 v0.4，待 BCA-03 产生正式交接成果后再同步项目阶段状态。
