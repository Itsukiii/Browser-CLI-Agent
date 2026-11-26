# BCA / BCA-lite — 项目总纲与跨会话共享上下文

> **文件角色：** 项目级共享背景（Project Context），供新旧开发会话读取。
> **版本：** v0.8（BCA-lite LITE-02 正式验收）
> **更新日期：** 2026-11-26
> **当前权威状态：** `lite` 分支 MaaFramework 路线：LITE-00 审计交付、**LITE-01 Accepted（2026-11-24）**、**LITE-02 Accepted（2026-11-26）**，接下来进入 LITE-03 交互式 CLI。`main` 为原 BCA-00～04 历史已验收基线；下方原 BCA 章节为历史资料，接口规划不得覆盖本节和 lite 源码。

## 0. BCA-lite 当前权威设计与交接（2026-11-26）

### 0.1 产品定位和技术路线

用户最初目标是轻量化的浏览器版 MAA：在终端持续阅读指定 Chromium/Edge 页面图像，输出结构化内容，接受手动命令并通过可插拔业务识别插件操作页面。**不自行建设另一套通用自动化框架**。

- 视觉识别、模型/模板资源、任务执行：**MaaFramework v5.16.1**（`maafw==5.16.1`，当前固定版本以隔离绑定私有销毁接口）。
- 浏览器 Target、CDP 截图和输入：复用 `src/bca/core/browser`、`Frame.pixel_to_css()`。
- 适配基础：`src/bca/lite/bridge.py` 的 `CDPBridge` + `ObservationRef`，以及 `maa_controller.py` 的 `MaaCDPController`。
- LITE-02 已交付：`MaaVisionFacade`（Controller/Resource/Tasker + 单 native worker），`BusinessPlugin`（纯业务），`ObservationCoordinator`（串行观察、通知、读取和一轮点击）；真实 Edge/长时/打包已验收，详情见第 0.7 节。
- 未来：LITE-03 交互式 CLI；LITE-04 Quiz Demo；LITE-05 雀魂游戏插件；LITE-06 集成与发布。

### 0.2 已交付与验收状态

| 阶段 | 当前状态 | 权威资料 |
| --- | --- | --- |
| LITE-00 · 基线审计 | 交付完成 | `docs/lite/LITE-00_HANDOFF.md` |
| **LITE-01 · Maa CDP Bridge** | **正式 Accepted（2026-11-24）** | `docs/lite/LITE-01_ACCEPTANCE_2026-11-24.md`、`docs/lite/LITE-01_HANDOFF.md`、`docs/evidence/LITE-01-addendum/final-2026-11-24/` |
| **LITE-02 · Vision & Plugin** | **正式 Accepted（2026-11-26）** | `docs/lite/LITE-02_ACCEPTANCE_2026-11-26.md`、`docs/lite/LITE-02_HANDOFF.md`、`docs/evidence/LITE-02/02.3/` |
| **LITE-03 · Interactive CLI** | **准备开发** | `docs/lite/LITE-03_KICKOFF_2026-11-26.md`、`docs/md/BCA-LITE_MASTER_HANDOFF.md` |
| LITE-04～06 | 按阶段任务规划 | `docs/md/BCA-LITE_MASTER_HANDOFF.md` |

### 0.3 LITE-01 可依赖的准确公共接口

- `CDPBridge(loop, session, capture, input_provider, timeout, max_frame_age, require_authorization=True)`：在浏览器 owner loop 上创建并固定 connection/page/session/generation，借用已经 start 的 Capture/Input。
- `bridge.screencap()`：由 Maa native callback worker 调用，BGR 连续 `numpy.ndarray`；成功后 owner loop 可读 `bridge.observation: ObservationRef | None`。不要在 owner loop 同步等待 native job。
- `await bridge.authorize(ref)`：仅接受同一个当前有效观察对象，无法复制旧引用后重新授权；每次授权最多一个 click。
- `bridge.click(raw_x, raw_y)`：Maa callback 提供原始 Frame 像素，Bridge 经 `Frame.pixel_to_css()` 一次映射；`input_outcome` 为 `not_attempted/rejected/confirmed/unknown`，confirmed 仅证明输入确认。
- `bridge.invalidate()` 任意线程快速停止；`await bridge.aclose()` 排空 owner-loop 的在途 coroutine。`run_native()` 用于一次性 smoke；长期的 Facade 将使用固定单 worker。
- `MaaCDPController` worker 中创建、绑定 Maa 后调用，原始截图模式默认 True；所有 native jobs 结束后 `close()` 显式销毁。使用 `maafw==5.16.1`，升级需复核上游私有 API。
- **安全边界：** 当前授权验证 Frame/几何/URL/Target/时效，不证明同一页面中题目或 Canvas 内容未更新。LITE-02 需要语义签名，LITE-04 需要业务回合及结算验证。

### 0.4 已验证的真实证据与未扩大声称

- 平台：Windows 11，Python 3.14.7，Edge 158/CDP 1.3，MaaFW Python/native v5.16.1。
- 原始控制器测试：12 个 DPR×ROI×raw 条件，**36 次真实 Edge 点击**，误差最大 0.667 CSS px；真实 Target 失效矩阵以及 native 模拟故障验证。
- 最终补证：Edge 实际桌面 80%/100%/125% × raw/non-raw 六组，误差最大 **0.993598 CSS px**，重复点击和旧缩放引用拒绝；真实 Edge ACK 丢失、断连和 native 回调关闭竞争三种故障，无重发、无泄漏、保持原有 Target。
- 2026-11-24：整个 lite 测试集合 **29 passed / 0 skipped**；另有 2026-11-23 离线 **786 passed / 50 skipped**、Browser 定向 **113 passed**、mypy/Ruff/build 通过的单独记录。29 是整个 lite 集合数量，非 29 项 Edge 场景。
- 证据为仓库原始日志/JSON，架构主会话完成静态/记录复核，但没有独立在用户 Windows 机器重跑。Maa OCR 与真实 Edge 长时指标已在 LITE-02 验证；完整 CLI、Quiz Demo 和实际雀魂仍按后续阶段验收。

### 0.5 LITE-02 已批准的设计及验收边界

设计文件 `docs/lite/LITE-02_DESIGN.md` 审核通过，以附加架构意见为实施约束。**默认使用一次 Maa screencap + 多次 `Tasker.post_recognition(type, dataclass, image)`；单节点 Pipeline 仅用于 API/来源验证。** 真实 TemplateMatch 和 OCR、模型资产许可证与校验、ROI 全图坐标、结果详情惰性物化，先在 02.1 实测。

- BusinessPlugin 使用纯业务的 plan/observe/format_state/parse_command/resolve/close；插件不直接持有 Controller/Tasker/Session。
- Coordinator 持有唯一序列化门；状态去重采用业务 signature，操作回合采用 interaction_revision，来源授权采用精确 `ObservationRef`；三者不能混淆。
- 只读查询触发新截图；写操作重新观察、唯一视觉候选、逐步授权、输入确认后再次视觉验证。
- 真实 OCR 模型必须记录来源、许可证、文件哈希；未授权不可打包转发。识别错误与未命中不同，歧义结果不能猜测性点击。
- LITE-02.1 原生 Vision 结果；02.2 插件/观察协调；02.3 Edge/持续运行与分发回归。验收资料、目标和完成度不得用原 BCA 的 Vision 测试替代。

### 0.6 开发职责与同步规则

- Codex 在用户本机 `lite` 工作目录实现、测试、提交阶段内容；架构主会话审查、定义接口并正式 Accepted。主会话无需修改产品源码。
- **每个正式大阶段 Accepted 后更新本文件和 `lite` 分支 README。** 不因设计审查或中途开发反复改状态。
- 子阶段交接中分别记录 `Git SHA`、运行环境、可复现测试命令、原始日志、失效/取消/资源回收和未覆盖事项；不擅自合并至 `main`。

### 0.7 LITE-02 正式验收基线（2026-11-26）

**决定：LITE-02.1 / 02.2 / 02.3 通过源码与原始证据复核，LITE-02 整体 Accepted。** 权威记录：`docs/lite/LITE-02_ACCEPTANCE_2026-11-26.md`；功能代码基线 `5b107e463c85292cd8ecb5653dce54ebd341a164`；归档提交 `984c61c8a9a05c22aaa96c54e40a2083714dfdd4`；不依赖旧 BCA-04 的视觉 SDK 承担 lite 主路线。

**公共接口（Codex 在 LITE-03 中应复用）：**

- `MaaVisionFacade.start() / recognize(tuple|plan) / click(batch,key,index) / aclose()`；使用真正的 Maa Controller、Resource、Tasker。一个 native worker；无法证明释放时不关闭其依赖。
- `BusinessPlugin` 为轻量同步纯业务契约：`plan(image_size) → observe(batch) → format_state(state) → parse_command(text) → resolve(intent,state) → close()`；冻结结果和不可变 payload，插件不触碰 CDP/Native。
- `ObservationCoordinator.start()/stop()/refresh()/execute_text()/execute_intent()/take_change()/aclose()`；唯一业务门，真实新帧查询，业务 signature 去重、视觉回合 revision、精确 ObservationRef、单步确认及后置观察。
- `CDPBridge.authorize(ref)` 重置本次 action outcome；`finish_native_click(succeeded)` 同时要求**本次** Maa Job 成功、**本次** CDP 输入确认、有效绑定，才能返回 confirmed，否则 unknown 并退役组合，禁止重放。
- `fixture_bundle()` / `fixture_html()` 和 `src/bca/lite/resources/fixture` 是 wheel 内自制受控测试资产；Windows 示例 `examples/lite_vision.py`。OCR 模型独立显式设置、版本/许可/文件 SHA256 校验，模型二进制不打包。

**最新原始实测：**

- 真 Edge 12 组 DPR×raw×ROI，真实桌面 80/100/125%（实际 DPR 1.2/1.5/1.875），字体/负数/多位数、目标缺失/双候选、点击 DOM oracle、来源/取消/关闭通过。全图 OCR 5/12 初始条件发生图案误识别，均安全拒绝，显式 ROI 重新观察后恢复；额外字体 36 样本 33 MATCHED/3 AMBIGUOUS。
- 独立 Edge 持续 **185.0128s**：245 完成、239 有效、**1.2918Hz**（目标 >=1Hz），6 次 NOT_FOUND 是主动隐藏目标；5 条业务状态变化通知，0 丢通知，0 skipped tick；总识别闭环 median/p95 **139.71/187.32ms**；结束 Tasker/Controller/Resource 释放，原有 Target 保留、pending=0、reader=false。
- 测试进程树约185.97s 的平均 CPU 使用 **325.63%（约3.26逻辑核）**，峰值 RSS **164.60MiB**，峰值 PrivateBytes **619.14MiB**；另行统计隔离 Edge。此 CPU 成本需在 LITE-03、LITE-06 针对实际部署硬件继续量化和优化，不能笼统称为低负载。
- 旧 OpenCV 4096×4096 decode access violation 在 3×4 配置的12次独立进程复查中未复现，**根因未知/未声称修复**。本次另记录 Maa stop succeeded 但 running 短暂为 true；新增 <=1s 的 bounded idle 等待，无法确认 idle 时仍不 Destroy。
- 干净 Windows venv/wheel[lite] 安装、跨 cwd 模板/模型校验及 Edge 点击通过，wheel/sdist 包完整性已核对；最终离线 **878 passed / 57 deselected**，browser_integration 另行真机测试；Ruff、mypy strict、build 通过。

**LITE-03 接续限制：** 终端必须只通过 Coordinator 输入与观察，不绕过 Facade；将低 CPU、ROI 选择、超时/歧义提示、Ctrl+C/EOF、unknown 重建边界纳入验收；CLI 的人机交互、Quiz 10s 回合及雀魂 WebGL 未在 LITE-02 声称完成。

---

## 历史资料说明

**以下第 1～8 节保留原 BCA 架构的历史记录，部分阶段文字和待办状态停留在 2026-11-20。与 BCA-lite 冲突时，以第 0 节、`docs/md/BCA-LITE_MASTER_HANDOFF.md`、`docs/lite/LITE-02_DESIGN_REVIEW_2026-11-24.md` 和 `lite` 实际源码为准。**


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
