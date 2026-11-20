# BCA-03.2 — 真实浏览器集成、故障回归与正式交接 / Codex 开发提示词

> 任务编号：BCA-03.2  
> 所属子系统：BCA-03 / Plugin System  
> 当前阶段：03.1 已完成 A/B/C/D 并通过阶段交接材料审查；03.2 待 Codex 实施及正式验收  
> 交付基线：**用户本地 `bca/` 未提交的 BCA-03.1 完整工作区**，其上游参考提交为 `main` / `550cdfa0b042e4cee95f0d7f53e88a7d84d62c43`  
> 公共协议：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 仓库：https://github.com/Itsukiii/Browser-CLI-Agent  
> 本阶段交付：`docs/BCA-03.2_HANDOFF.md`、`docs/BCA-03_MAIN_SYNC.md`、真实集成测试/示例、可复核测试与测量证据

## 0. 工作定位与执行原则

你是 BCA-03 / Plugin System 的 Codex 实施工程师。**直接在用户现有的统一 `bca/` 工作目录实施、测试、修复和生成文档**。本轮集中验证 BCA-03.1 已开发的插件系统与真实 Chromium/Edge CDP、Browser Session/Provider、RuntimeController 之间的组合，补足测试证据与必要的 BCA-03 范围内修复，然后形成一次正式交接。

请按 **03.2-A（源码审查）→ 03.2-B（真实闭环）→ 03.2-C（故障/清理/安全边界）→ 03.2-D（质量、性能与交接）** 顺序推进；每批先完成对应测试，再进入下一批。遇到测试缺陷应追溯根因、补充回归，而不以放宽断言替代修复。

### 启动前的工作区核验

1. 在现有仓库执行 `git status --short`、`git branch --show-current`、`git rev-parse HEAD`、`git diff --stat`，并检查 untracked 文件；记录实际分支和工作区来源。**本地未提交的 03.1 源码是本次工作的真实起点**，不能通过 checkout/reset 到 `550cdfa` 丢失它。
2. 阅读 `docs/BCA-03.1_HANDOFF.md`、`docs/PLUGIN_SPEC.md`、`docs/INTERFACES.md`、`docs/RUNTIME.md`、`docs/ARCHITECTURE.md`、`docs/BROWSER.md`、`docs/BCA-01_MAIN_SYNC.md`、`docs/BCA-02_MAIN_SYNC.md`、`docs/BCA-02.4_HANDOFF.md`、`docs/BCA-02.4_CODE_AUDIT.md`、`docs/BCA-02.4_PERFORMANCE.json`；存在路径差异时据仓库实际位置校正。
3. 核对 `src/bca/core/plugins/`、`src/bca/core/browser/`、`src/bca/core/runtime/`、`src/bca/core/providers/`、`plugins/example/`、`examples/plugin_runtime.py`、`examples/plugin_browser.py`、`tests/core/plugins/`，以及 BCA-02 的 `tests/core/runtime/`、`tests/core/runtime/cdp_fault_proxy.py` 和 `examples/runtime_integration.py`。
4. 保留当前用户文件改动与已有测试证据。既有 `docs/md/BCA_PROJECT_CONTEXT.md` 用户修改须与 BCA-03 变更区分；处理格式检查时识别新增问题与历史问题，避免无关文件的批量格式化。未经用户要求不执行 `git commit` / `git push`；交付报告记录建议提交的变更清单及可复用的提交边界。
5. 当前上游公开契约已验收。若验证发现**确须变更 Protocol 2、Provider ABC、Browser/Runtime 已验收稳定接口**，先整理最小变更提案、影响与替代方案，提交架构主会话协调；允许在 BCA-03 自有实现与测试内进行兼容性修复。

### 已有 03.1 交接证据（历史值，非本轮执行结果）

- 03.1 A/B/C/D 已新增 Manifest/Catalog、Loader、PluginManager、ProviderLookupView、FreshnessCaptureAdapter、PluginRuntimeHost，保留原 Plugin/SDK 公共契约。
- 03.1 专项 **58 passed**（57 新 + 1 旧）；未配置真机时全量 **495 passed / 12 skipped**；mypy strict、Ruff、sdist/wheel、无浏览器示例报告通过；测试使用了模拟 CDP，未执行 Edge 真机。
- 工作区未 commit/push；GitHub `550cdfa` 只有 BCA-02 基线，**不包含 03.1 的新增源码**。以本地当前源文件、测试运行结果及日志为准。

## 1. BCA-03 已确认的架构及公开入口

### 1.1 插件系统

保持现有 `bca.core.plugins` 导出与语义：

```python
Plugin, PluginMetadata, PluginConfig, PluginContext
PluginCatalog, PluginLoader, PluginManager
ProviderLookupView, FreshnessCaptureAdapter, PluginRuntimeHost
PluginDescriptor, PluginDiscoveryIssue, CatalogSnapshot
PluginLifecycleState, PluginSnapshot
PluginManifestError, PluginDuplicateIdError, PluginLoadError
PluginCompatibilityError, PluginContractError
```

主要接口签名以本地实际源码及 `docs/BCA-03.1_HANDOFF.md` 为权威依据，典型调用如下：

```python
# 前置：Session 已绑定，registry 已注册且 raw_capture / inputs 均已启动；
# inputs 与 policy 关联的具体构造方式以 examples/plugin_browser.py 为准。
policy = BrowserFreshness(session, states)
adapter = FreshnessCaptureAdapter(session, raw_capture, policy)
await adapter.start()
lookup_view = ProviderLookupView(registry, overrides={"capture": adapter})

catalog = PluginCatalog([plugin_root])
catalog.discover()
manager = PluginManager(
    catalog,
    providers=lookup_view,
    states=states,
    events=events,
    logger=logger,
)
manager.load("example", config=PluginConfig(values={"page_id": page_id}))
controller = RuntimeController(manager.observe, inputs, states, policy, events)
host = PluginRuntimeHost(manager, controller, states)
await host.start()
result = await host.execute_text("click 12 23")
await host.close()
```

该片段仅描述对象关系；**实际装配必须先确保 `BrowserSession` 已绑定且 raw Capture/Input Provider 已启动、在 View 中将 `capture` 映射至已启动 adapter，Input 与 Controller 是同一个实例**。优先核对并复用 `examples/plugin_browser.py` 的 `assemble(...)` 和所有权流程，避免对已有实际签名作臆测。

当前插件发现：显式可信插件根目录 → 子目录 `plugin.toml` → 选定后加载 `__init__.py` 的工厂 `create_plugin`；单 Manager 一个活动插件，Host 一次性运行组合。Manifest/metadata 的版本、能力与协议检查保持 03.1 的已测试规则。

### 1.2 Runtime 与 Browser 的关键不变量

1. `Plugin.observe()` 只返回 `PageState`；`ObservationPipeline` 独占 `StateStore.publish()` 责任，对每个有效观察提交一次，Store.version 与 `PageState.sequence` 是两个独立计数。
2. 浏览器插件获取 Frame 的标准路径：`Plugin → ProviderLookupView.get(CaptureProvider) → FreshnessCaptureAdapter.capture(page_id) → BrowserFreshness.capture(raw_capture)`。返回真实 Frame 的 `frame_id` 必须进入 `PageState.source_frame_id` 并被策略 validate/commit；Runtime 才能产生可信 `ActionObservationRef`。
3. `Plugin.handle_command()` 返回有序 `tuple[Action, ...]`，Host 保存生成动作时的原始引用对象并将其放进 `ActionBatch`，由 `RuntimeController.submit()` 执行。观察/动作互斥、来源及新鲜度检验由现有 Runtime 掌握；输入在 Provider 内串行。
4. Host 保留调用方原先的暂停状态；命令生成、当前 Store 快照/引用读取、动作提交遵循 03.1 既定锁和生命周期。`STALE` 不替旧动作换新引用重新提交；`BLOCKED`、`FAILED`、`CANCELLED` 及 `ActionResult` 保留原语义。
5. `ActionResult.SUCCEEDED` 只证明浏览器输入已确认，须由**后续页面观察**验证页面实际变化。旧引用不能作为新的业务状态证明。坐标通过 `Frame.pixel_to_css(px, py)` 转换为 CSS viewport 输入坐标，输入侧不再次叠加滚动或 DPR。
6. 资源 owner：Application 拥有 BrowserSession、原始 Capture/Input Provider、StateStore/EventBus 及自行创建的 Target；Host 负责 Controller/Manager；Adapter 借用原始 Capture/Session；Registry/View 只提供查询。正常收尾：`host.close → adapter.close → input.close → raw_capture.close → 自有 Target 清理 / session.close → states/events.close`，并等待在途取消及清理结束。
7. 输入结果不确定时保守阻断。BrowserFreshness 已有来源可证明的**新 Target + 新 Provider + 新观察**恢复机制；本阶段若需覆盖此路径，使用现有 Runtime 恢复契约及明确 owner 编排。Provider 替换后检查 View、Manager、Host 与 Controller 的组合一致性，必要时重建运行组合。

## 2. 03.2-A — 对 03.1 新源码做静态审计与基线回归

### 2.1 审计的实际对象

依次审阅：

- `core/plugins/{contracts,models,errors,catalog,loader,validation}.py`：Manifest 校验、冲突 ID、路径身份、包导入与 `sys.modules` 回滚、工厂元数据一致性、方法签名及返回类型。
- `core/plugins/{lookup,capture_adapter}.py`：ProviderLookup 的只读代理、名称/类型查询一致、readiness、Adapter 捕获来源、原始 Provider 借用及嵌套适配保护。
- `core/plugins/{manager,host}.py`：状态机和并发入口、重复调用、锁范围、异常和取消、在途任务跟踪、停止/关闭的共享任务及错误归档、原观察引用、暂停状态恢复。
- `plugins/example/__init__.py` 与 Manifest：工厂创建新实例，示例插件能够在真实 page_id 上运行；测试和示例导入路径应在仓库外 cwd 仍正常。
- `src/bca/plugin_sdk/interfaces/__init__.py`、`core/plugins/__init__.py`：原四项插件接口保持兼容，重导出没有分叉。

重点审查这些有风险的条件（逐项给出源码证据、测试对应关系和结论）：

1. `PluginManager` 的 `initialize/start` 发生部分失败或取消时，已分配的插件自有资源是否真正清理、原异常是否保留；重叠 `stop/close` 与取消 stop 等待者是否可能死锁或二次取消。
2. `Host.close()` 与 `execute_text()`、`host.start()` 竞争时，是否先拒绝新任务、取消/等待已有任务，再关闭 Manager；在 Controller 进入 STOPPING/STOPPED 时不会继续 resume。
3. `Manager.close()` 以 `cleanup_status=failed` 记录清理异常但正常返回时，真实 Host/应用层是否仍能识别收尾失败；检查 Snapshot 与实际资源的一致性。
4. 输入通道是否与注入插件的 `InputProvider` 为同一对象；`Adapter.capture` 是否只调用 `policy.capture(raw_capture)` 而非间接递归；动态新 Target/Provider 之后 View 是否有过期引用风险。
5. Loader 的模块缓存是否稳定复用导入而每次创建独立实例；独立目录下相对导入模块不会串名；失败回滚限定本插件命名空间。
6. `PLUGIN_SPEC`、`RUNTIME`、`INTERFACES` 公开接口描述与源码一致。更新过时文字及示例路径，保留必要的历史交接证据。

对于发现的真实缺陷，写最小复现测试后进行 BCA-03 局部修复；审计结论收录于 03.2 HANDOFF 的「源码审计」章节，标记已验证/已修复/未能验证及具体原因。

### 2.2 基线测试

先执行现有 03.1 插件专项与无浏览器全量测试，记录实际数字（不要求等于历史数字，但要说明差异及因果），作为 03.2 变更前基线。保持原有测试覆盖，不修改既有失败为跳过或 xfail 来获得表面通过。

## 3. 03.2-B — 真正的 Edge / Chromium 插件闭环

### 3.1 真机测试入口与隔离

使用 **真实 Edge/Chromium 进程**、其真实 CDP endpoint 和单独的受控 HTML 页面。与 03.1 模拟 HTTP/WebSocket/CDP Peer 严格区分。沿用项目现有 opt-in 机制（例如 `BCA_CDP_ENDPOINT`、`@pytest.mark.browser_integration`），测试入口名称、环境变量和命令以仓库实际用法为准。

- 由用户显式提供隔离的测试 CDP 端点。推荐本机回环独立端口和独立 `user-data-dir` 的有窗口浏览器实例；先确认端点对应测试实例。不要主动使用用户日常 9222 会话或枚举后随意点击预存网页。
- 记录启动前 `list_targets()` 得到的原有 Target ID 集合；测试自行 `Target.createTarget` 创建的页面由测试明确登记 owner，退出只关闭本次自建 Target。测试前后对比预存 Target 的保留情况。
- 提供独立可复现的 `examples/plugin_browser.py` 真实运行入口（或新增 `examples/plugin_integration.py`，择一维护）；支持 endpoint、输出目录、合理的样本/时长选项，默认路径无需依赖固定的 `D:` 盘符。控制范围限定在测试页面。
- 新增 `tests/core/plugins/test_real_integration.py` 等真机入口；测试未 opt-in 时可按既有规范跳过，显式配置真机的正式验收运行时必须记录实际执行数，不能把 skipped 视作真机覆盖。

### 3.2 可测的 HTML fixture 与插件观测

使用可控、确定性、无需登录的 HTML 测试页，例如固定位置、不同颜色的可点击 marker（可滚动内容），点击后切换颜色并递增 DOM 计数。真实插件的观察结果应能反映**截图像素的实际变化**，以证明动作后的新观察，而不仅是读出宽高。

优先以 example 插件证明公开接口不变；为需要识别 marker 颜色、定位像素及状态翻转的真实闭环，可新增仅用于测试/示例的极简插件或 fixture helper，通过现有 Pillow 读取 PNG 并返回业务测试 `PageState`。这只作为集成测试的可验证识别逻辑，不扩展 BCA-04 的通用视觉 SDK。

完整链路至少验证：

1. 真实 `BrowserSession.connect → 自建 Target → bind → raw Capture/Input.start`，通过 `BrowserFreshness` 构造 Input（如适用）和 `FreshnessCaptureAdapter`，建立 View、Manager、Controller、Host。
2. 从 `plugins/example`（或新增测试插件）通过 Catalog 发现、Manifest 验证、Loader 导入并初始化启动；输出实际插件 ID、版本、能力请求及状态快照。
3. Host 启动后等待第一份 `StateStore` 新快照：真实 PNG Frame 已通过 Adapter / policy.capture 记录；`PageState.source_frame_id` 与来源一致，Store.version 有且仅有本次提交的递增，Controller.reference() 非空。
4. 从真实 PNG 中识别受控 marker 的位置或状态，使用 `Frame.pixel_to_css`（全图/区域均正确映射）产生可执行 CSS 坐标；通过插件 `parse_command → handle_command` 生成 `Action`，经 `host.execute_text()` 提交。`Command.request_id`、`Action.request_id/action_id`、`ActionBatch/BatchResult` 关联可追踪。
5. 浏览器 CDP 确认动作后，用 DOM 的点击计数/目标状态作独立核验；同时等待 Store.version 增大并核验下一次 **真实截图像素对应的 PageState 改变**。DOM 只作为测试 oracle，不作为视觉插件的默认观察来源。
6. 执行多次受控操作，验证动作顺序和状态序号；测试记录每次输入所基于的观察版本、帧 ID、请求/动作 ID、结果类别、前后状态及目标验证。

测试中要保持 Runtime 对观察提交的独占所有权：插件 observe 不直接 publish；不能在 Controller 协调门外并发输入同一目标。

### 3.3 几何与新鲜度矩阵

延续 BCA-01/02 已有真实几何基线，至少测试：

| 场景 | 关键断言 |
| --- | --- |
| DPR = 1 / 1.5 / 2（可通过实际测试浏览器选项或独立子场景配置） | `Frame` 的 PNG 实际尺寸与视口、Pixel→CSS 还原值一致；点击真实落点正确 |
| 全图与区域截图 | 适配器、来源 ID 和区域偏移一致；区域入口使用已有 Browser 扩展的组合包装，不扩展 Provider ABC |
| 滚动与 resize | 旧引用或旧坐标失效返回 STALE / 拒绝动作；重新观察后可重新生成动作 |
| 页面导航、文档替换 | URL/timeOrigin 等指纹变化时原动作不获授权；后续获得新观察 |
| unbind/rebind / Target 关闭 | 原身份失效，旧请求停止；观察/输入按现有错误与生命周期语义处理 |
| 观察版本改变但旧动作仍在等待 | 不换引用，不误发旧动作；按 Runtime 规则返回 STALE |

测试前明确观察、命令和页面变化的时序，使用事件/同步栅栏减少脆弱的固定 sleep。无法从同一浏览器实例可靠切换 DPR 时按现有 BCA-02 的方式分别运行独立测试场景，并如实记录覆盖情况。

## 4. 03.2-C — 故障注入、取消与资源清理回归

### 4.1 在真实 CDP 传输上注入故障

复用/适配 `tests/core/runtime/cdp_fault_proxy.py` 及 BCA-02 的传输故障经验：**真实 Edge 处理命令，测试中继在可验证的传输阶段故意丢响应或切断连接**。模拟 Provider 抛异常可补充单元覆盖，但不能冒充真实响应丢失测试。

至少覆盖以下可重复场景，并对每项保存故障触发点及测试证据：

1. 输入命令发出后 CDP 响应丢失/延迟到超时；可能已经产生浏览器副作用。检查 Provider 的 `input_state_uncertain`、Host 的 `BatchResult`（若已返回）、Controller 的 BLOCKED 状态以及不自动重发。
2. 鼠标/键盘多步骤输入中途断开；已发步骤可能留下浏览器状态。验证 best-effort 释放的等待、失败诊断及保守阻断行为，避免简单把取消解释成撤销。
3. 截图命令处理中断或返回异常，插件 observe 失败；Store 不提交伪造的新状态，Scheduler 和 Host 有合理错误诊断与后续行为。
4. Runtime 指纹测量、Target 关闭或 Session 断连与 `observe`、`handle_command`、`execute_text` 并发；旧身份绝不重用于新的 Target。
5. `host.close()` 在捕获、命令生成、动作排队或执行中触发，并发两个关闭等待者；已开始的工作需等待真实清理，最后各组件达到确定终态。
6. 插件 `initialize/start/stop/close` 故意失败或取消；分别检查 Manager `last_error`、`cleanup_status`、`cleanup_error` 与真实在途任务，确保诊断不等于完成清理的假象。

原始输入敏感内容、截图 bytes、完整 CDP payload 和未经清理的异常消息不写入默认结构化日志/交接报告。

### 4.2 恢复与资源所有权

真实故障后至少验证一种完整的显式恢复路径：通过现有 BrowserFreshness 创建受控**新目标**并按 BCA-02 约定完成新绑定、新 Input Provider 和新观察授权；若 03.1 Host 当前一次性组合设计适合重建 Host/Manager/View，则采用明确的上层新组合方式并验证资源 owner。旧批次绝不能自动重新提交到新目标。此路径应与旧 Controller 的实际 BLOCKED 状态及终止顺序相协调。

异常退出以及正常退出后，逐项检查：

- PluginSnapshot 的真实终态和 `cleanup_status`，Host/Controller 的 STOPPED 状态及内部队列/活动任务终结；
- Input Provider 和 Capture Provider 的关闭顺序、Adapter 不释放借用的原始资源；
- CDP 连接 pending request、reader task、Session 连接状态；
- 本轮 owner 创建的 Target 全部清理，测试开始前就存在的 Target 均保留；
- 测试创建的 plugin 自有后台任务、Host 命令任务和 Runtime worker 均不存在残留；
- 多次关闭、部分启动失败、异常中断时，仍有与正常收尾相同的资源证据。

不要仅凭 `close()` 没有抛异常判定成功，应同时检查 snapshot、任务和浏览器对象。清理本身异常时在报告中标识失败及实际资源结果。

### 4.3 插件加载的实际部署边界

在真实 Windows 工作区校验：插件目录位于仓库外且使用绝对路径时仍能被发现和导入；从不同 cwd 启动示例仍可用；有效相对导入正常；非法入口、重复 ID、缺少文件以及在权限支持时的真实符号链接逃逸均能形成可归类诊断。权限不允许创建 symlink 时说明环境原因，保留已有确定性路径边界单元测试。

## 5. 03.2-D — 测量、回归、文档与正式交接

### 5.1 性能测量方案

在固定的受控 Edge 页面、明确浏览器参数和尽可能一致的 CPU/系统负载条件下，至少收集：

- `Host.start` 到首个有效 `StateSnapshot` 提交的耗时；
- 一轮真实观察（Plugin + Adapter + Capture + BrowserFreshness + Store）的耗时；
- `host.execute_text` 从调用到 `BatchResult` 的耗时（分别记录解析/生成、排队与输入部分，如现有统计可获取）；
- 一次动作发出到**下一份验证状态提交**的端到端耗时；
- 固定时间段内成功观察/点击数、skipped ticks、动作 STALE/FAILED/BLOCKED、峰值排队等 Runtime 统计；
- 启动/持续/停止的 Python 内存指标与 Edge 资源指标（能够可靠获取的分别报告；`tracemalloc` 不等于 Python native/Edge RSS）；
- 关闭后的 Target、pending CDP、reader、asyncio Task 残留数。

报告每项的样本量、median、p95、最大值、采集边界与运行环境。合理做少量重复测量，排除测试自身写文件/DOM oracle 等附加耗时或明确标注。对照 BCA-02 数据时仅在测量边界等价时比较；否则分别展示，不声称无证据的加速或稳定 10Hz。记录观察和命令之间是否存在测量所致额外开销。

### 5.2 测试组织和运行命令

建议新增/完善 `tests/core/plugins/test_real_integration.py`、`test_real_faults.py`、`test_real_lifecycle.py`，并复用既有测试 fixture/故障代理；最终以实际文件名为准。真机测试应有可靠的 opt-in 门槛和短时间、有限样本的默认值。

使用 PowerShell / 当前 venv 执行，记录准确命令和结果；以下命令仅作规范示例，路径、端点和测试名称以实际实现为准：

```powershell
# 1) 03.1 新旧插件专项
.\.venv\Scripts\python.exe -m pytest tests/core/plugins tests/plugin_sdk/test_example.py -q -W error --basetemp=.test-artifacts/pytest-03.2-plugins

# 2) 配置隔离 Edge endpoint 后，定向执行新增真实插件集成
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9341"
.\.venv\Scripts\python.exe -m pytest tests/core/plugins -m browser_integration -v -W error --basetemp=.test-artifacts/pytest-03.2-edge

# 3) 含真机入口的全量回归（应实际执行所有可用真机测试）
.\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-artifacts/pytest-03.2-full-edge

# 4) 无真机配置的可重复测试集（记录预期 skips）
Remove-Item Env:BCA_CDP_ENDPOINT -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-artifacts/pytest-03.2-full-local

# 5) 静态检查与发布构建
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

Windows `ruff format --check` 和 `git diff --check` 的结果须区分 BCA-03 新增问题与用户原先文件的差异；若发现新增内容有格式问题应修正。正式真机验收需要**实际创建 Edge CDP 实例并执行对应测试**；如环境没有浏览器、端点或权限，记录明确阻塞和缺失证据，不以模拟结果代替。

如果可用 Python 3.12 或 3.13，补充可运行性检查；若仍只有 3.14.7，记录实际执行矩阵和剩余验证项，不凭配置声明代替执行证据。

### 5.3 文档同步

审查并更新 `docs/PLUGIN_SPEC.md`、`docs/INTERFACES.md`、`docs/RUNTIME.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_PLAN.md` 与 README 中直接涉及 BCA-03 的部分，使实际模块与示例/文档一致；保留已完成 BCA-00/01/02 的历史报告内容和原有接口。说明：

- Manifest 格式、候选扫描、冲突诊断、路径/信任边界、工厂及缓存语义；
- 插件状态机、Manager/Host API、异常与返回值；
- ProviderLookupView 与 Adapter 如何把真实 Capture 绑定到 BrowserFreshness；
- Host 命令输入、观察引用、执行结果及 CLI 接入模式；
- 哪一层拥有哪个对象、真实退出/恢复顺序、失败诊断读取；
- 真机测试启动、测试页面和结果证据的复现方式。

### 5.4 正式交付文档

**A. `docs/BCA-03.2_HANDOFF.md` — 最终实施及验收证据**

须包含：

1. 当前 Git 分支、HEAD、03.1 本地未提交工作区的承接方式、实际代码变更/新增清单（包含 untracked），及是否 commit/push 的真实状态。
2. 03.2-A～D 的完成情况；新增/修改文件与动机、问题根因及修复方式、代码审计表。
3. 真实 Edge/CDP 的版本、系统、Python、端点及测试隔离方式；真实测试数、mock 测试数、跳过数、失败数及测试入口。
4. 每个真实闭环及故障注入场景的复现步骤、原始证据位置、观察/动作关联 ID、预期/实际判定。
5. 性能统计及测量边界，包含样本量、median、p95、最大值和资源统计；有前后对照时解释可比性。
6. 资源 owner、清理后实际状态和异常清理的检查结果；覆盖取消、并发关闭、启动失败与断连。
7. pytest、mypy、Ruff、wheel/sdist、示例运行的具体命令与**实际输出**；已知平台限制及未覆盖项。
8. 公共协议及已验收模块接口兼容性结论，若发现协议变更需求列出待主会话协调事项。

**B. `docs/BCA-03_MAIN_SYNC.md` — 架构主会话正式跨模块同步**

须简洁但足够精确，重点包含：

1. BCA-03（03.1+03.2）最终状态、版本、来源提交/工作区与实际证据边界。
2. `bca.core.plugins` 的公开导出与核心 API；Catalog/Loader/Manager/Host 的调用方式、插件目录和 Manifest 规则。
3. PluginContext 注入、ProviderLookupView、Capture Adapter、BrowserFreshness 及 Controller 的装配顺序和对象一致性要求。
4. Manager/Host 状态机、并发/取消/失败传播、清理错误可观测性与 Browser/Runtime 资源所有权。
5. Host `execute_text` 的同步观察引用与动作结果语义，Plugin.observe 唯一提交及新鲜度授权约束。
6. BCA-04 Vision、BCA-05 CLI、BCA-06 Majsoul 的直接接入指引；贴近实际包路径和真实测试示例。
7. 真机/模拟回归统计、性能测量范围、正式可依赖接口、遗留问题和需架构主会话审批事项。

同步文件须以**实际源码和已执行测试**为准，避免把「03.2 开发完成」直接写成「架构主会话已正式验收」；最终 Accepted 由主会话审核后确认。

### 5.5 结构化测试产物

优先生成可机器读取的 JSON 汇总（例如 `.test-artifacts/03.2/plugin-integration-report.json`，路径可调整），包含：版本和运行环境、真实/模拟证据标识、每个场景 pass/fail/skip、观察帧 ID/Store version/命令请求 ID/Action ID/Batch status、性能统计以及清理状态。截图/DOM 检查证据可按需存储在隔离输出目录，不在默认控制台或报告中直接打印 PNG bytes。JSON 与 Markdown 两种交接内容应可相互核对。

## 6. BCA-03.2 正式进入验收的判定条件

由 Codex 对照以下标准输出逐项结论及证据：

1. **源码契约**：03.1 的发现/加载/管理/Context/Host 公开接口已完成静态复核；已知竞态问题有复现和回归，Protocol 2、Browser/Runtime 稳定接口保持兼容。
2. **真机链路**：确实使用独立 Edge/Chromium，真实插件完成截图像素观察 → PageState/Store/可信引用 → 插件命令映射 → ActionBatch → Browser Input → 新截图状态验证；关联 ID 一致。
3. **来源和新鲜度**：DPR、全图/区域、滚动、resize、导航、rebind/关闭与过期版本场景中正确拒绝不适用的操作；新观察后可生成新动作。
4. **未知结果**：在真实 CDP 传输故障及中途取消下保留 BLOCKED/STALE/FAILED/CANCELLED 原义，可能已经执行的动作不盲目重放，释放/清理被等待。
5. **生命周期**：插件初始化、启动、运行、停止、关闭和异常终止的资源检查通过；借用资源由其真实 owner 关闭，预存浏览器目标保留，测试自建目标与任务无残留。
6. **可靠性和性能**：测试有实际样本、测量边界、统计范围、资源检查与可复现命令，模拟与真机证据清晰分开。
7. **质量**：专项、含真机的全量 pytest、mypy strict、Ruff、构建和示例通过或有清楚定位的阻塞/失败报告；没有以缺少 opt-in 产生的 skip 充当真机验收。
8. **交接**：`BCA-03.2_HANDOFF.md`、`BCA-03_MAIN_SYNC.md` 与源码和测试一致，并列出供架构主会话复核的测试产物与待协调点。

如果某个条件确因环境不可验证，保留该项「待验证」及阻塞证据。优先完成所有可开展的实施与测试，并真实报告剩余内容。

## 7. 本轮最终回复格式

完成 Codex 工作后，在回复中按以下结构汇报：

1. **版本与工作区**：分支、HEAD、是否包含 03.1 未提交文件、git status、commit/push 状态。
2. **03.2-A～D 实施摘要**：真实修改/新增文件，静态审查发现的问题及修复。
3. **真机闭环和故障验证**：测试环境、场景数、真实输入/DOM/截图证据、STALE/BLOCKED/FAILED/CANCELLED 等实际结果与成功判定（按现有枚举与返回类型准确记录）。
4. **质量和性能**：pytest passed/failed/skipped（区分真实/模拟）、mypy、Ruff、build、性能和清理统计。
5. **交付文件**：`docs/BCA-03.2_HANDOFF.md`、`docs/BCA-03_MAIN_SYNC.md`、测试/示例/JSON 产物位置。
6. **结论和待主会话协调项**：是否满足提交正式验收条件，证据缺口及建议。

请直接完成 BCA-03.2 的代码核验、需要的 BCA-03 局部修复、真机测试和交接文件；最终判断以真实代码和测试证据为准。
