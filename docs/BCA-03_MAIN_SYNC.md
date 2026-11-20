# BCA-03 / Plugin System 跨模块交接

2026-11-20。03.1 与 03.2 已完成实施和验证，**待架构主会话审核，不代替 Accepted**。包版本 browser-cli-agent 0.2.0，PROTOCOL_VERSION=2。

来源为 main / `550cdfa0b042e4cee95f0d7f53e88a7d84d62c43` 及其上的完整本地未提交工作区。该提交仅包含 BCA-02 上游，不能只检出此提交就认为取得插件系统。03.1、03.2 均未 commit/push，用户 PROJECT_CONTEXT 修改保留。

## 公开入口与核心 API

全部从 `bca.core.plugins` 导出：

- 原契约：Plugin、PluginMetadata、PluginConfig、PluginContext。`bca.plugin_sdk.interfaces` 重导出同一对象。
- 运行组件：PluginCatalog、PluginLoader、PluginManager、ProviderLookupView、FreshnessCaptureAdapter、PluginRuntimeHost。
- 本地模型：PluginDescriptor、PluginDiscoveryIssue、CatalogSnapshot、PluginLifecycleState、PluginSnapshot。
- 错误：PluginManifestError、PluginDuplicateIdError、PluginLoadError、PluginCompatibilityError、PluginContractError。

```text
PluginCatalog(roots: Sequence[Path])
  discover() -> CatalogSnapshot
  get(plugin_id: str) -> PluginDescriptor
PluginLoader().load(descriptor: PluginDescriptor) -> Plugin
PluginManager(catalog, *, providers, states, events, logger, loader=None)
  load(plugin_id, *, config: PluginConfig|None=None) -> None
  async initialize/start/stop/close() -> None
  async observe() -> PageState
  parse_command(text, *, source="cli") -> Command
  async handle_command(command) -> tuple[Action,...]
  format_state(state) -> str
  snapshot() -> PluginSnapshot
ProviderLookupView(base, *, overrides: Mapping[str,Provider]|None=None)
  get(str|type[P]) -> Provider|P
  available(str|type[Provider]) -> bool
FreshnessCaptureAdapter(session, raw_capture, policy)
  available: bool
  async start/close() -> None
  async capture(page_id) -> Frame
PluginRuntimeHost(manager, controller, states)
  async start/close() -> None
  async execute_text(text, *, source="cli") -> BatchResult
  snapshot() -> StateSnapshot|None
  format_current_state() -> str|None
```

精确参数类型和模型字段见源码与 [03.1 交接](BCA-03.1_HANDOFF.md)。03.2 没有新增 Core API，没有修改 Protocol、Provider ABC、Browser 或 Runtime 稳定接口。示例中的 Composition、EvidenceController、RegionCapture 不属于稳定库接口。

## 插件目录、Manifest 与信任边界

Catalog 仅扫描显式可信根目录的直属子目录，静态读取 plugin.toml，不执行插件代码。入口为同目录 __init__.py；解析后的目录和文件必须处于对应根目录或插件目录内。重复 ID 的所有候选均拒选，按来源报告诊断，不选择赢家。

```toml
[plugin]
plugin_id = "example"
version = "0.2.0"
protocol_version = 2
required_capabilities = ["capture", "input"]
factory = "create_plugin"
```

factory 默认为 create_plugin，必须同步、支持无参调用，并返回契约正确的新实例。Manifest 与实例 metadata 的 ID、版本、协议、能力逐项一致。协议必须为精确整数 2，不接受 bool，不做版本范围协商。插件 version、PageState.schema_version 与公共协议版本分别维护。

Loader 使用规范化路径摘要生成隔离包名，支持包内相对导入。同路径成功模块缓存在 sys.modules，每次 load 调用工厂；导入失败只回滚本插件新增命名空间。没有热重载、下载或沙箱。可信工厂应无资源副作用；恶意单例、忽略取消及任意 Python 副作用不属于强隔离保证。

仓库外绝对目录、不同 cwd、实际相对导入和缓存下的新实例已通过 Windows 子进程测试。真实符号链接创建因 WinError 1314 未验证，已有确定性路径解析边界测试保留。

## Context 注入与装配顺序

1. Application 创建 Session、StateStore、EventBus；连接浏览器，创建或显式选择 Target，绑定并等待页面准备完成。
2. 创建 `BrowserFreshness(session, states)`，通过 `policy.create_input_provider()` 创建 Input，启动原始 Capture 和 Input。
3. 创建并启动 `FreshnessCaptureAdapter(session, raw_capture, policy)`。
4. 创建 ProviderLookupView，将 capture 映射至 adapter，input 映射至实际 Input。
5. 创建 Manager、load 插件；创建 `RuntimeController(manager.observe, inputs, states, policy, events)`，最后启动 Host。

View、Manager、Controller 必须使用同一 Input、Store 和策略组合。PluginContext 注入 View、StateSink、EventSink、logger、PluginConfig。一致性由组合入口保证，Host 不通过读取 Runtime 私有属性替换依赖。

插件 observe 只返回 PageState，Runtime 独占 publish；插件不能通过 Context.states 重复提交，也不能自行执行共享 Input。adapter 只调用 `policy.capture(raw_capture)`，不递归调用自身、不改变 Frame。PageState.source_frame_id 必须对应实际 Frame.frame_id。

坐标仅通过 `Frame.pixel_to_css` 从截图像素转换为 viewport CSS；输入端不再叠加 scroll 或 DPR。`examples/plugin_browser.py:assemble` 提供原 example 装配配方，`examples/plugin_integration.py` 是独立真实运行入口。

## Host 命令与执行结果

Host 串行处理命令。如果 Controller 原先 RUNNING，先暂停并等待观察完成，再在同步段读取匹配的 snapshot/reference，调用 parse/handle，使用原引用及 Command.request_id 构造 ActionBatch。原来 PAUSED 时保持暂停。

STALE 不换新引用重试旧动作。SUCCEEDED 只证明输入确认，业务成功仍须由后续 Store 更新和新页面状态验证。FAILED、BLOCKED、CANCELLED 以及真实 ActionResult 保持 Runtime 原义。调用方取消可以抛 CancelledError，不能解释为输入已被撤销。

缺少可信观察时 execute_text 抛 LifecycleError。CLI 应先等待首次状态，使用调用方总超时，并等待取消后的实际清理完成。

## 生命周期、并发与清理诊断

Manager 正常路径为 CREATED → LOADED → INITIALIZING → INITIALIZED → STARTING → RUNNING。stop 经 STOPPING 到 STOPPED，允许再次 start；close 经 CLOSING 到 CLOSED。Host 与 Controller 是一次性组合，关闭后不能重启。

Manager 异步调用串行，跟踪子任务，只请求一次取消并等待插件 finally。stop/close 使用共享任务，取消某个等待者不取消实际清理。initialize/start 失败或取消会等待一次 plugin.close，并保留主错误 last_error。

close 回调失败归档为 cleanup_status=failed、cleanup_error，不覆盖主异常；正常返回的 close 仍可能代表清理失败。**CLOSED 不等于资源释放成功。** Application 必须保留 Manager/Controller 句柄并读取诊断；Host.snapshot 仅返回业务 StateSnapshot。

Host.close 先禁止新命令并停止 Controller，等待输入清理，再结束命令生成或启动流程，最后 Manager.stop/close；关闭期间不恢复观察。插件不得回调自己的调度链，parse/format 应保持轻量。

插件自建任务由插件负责。03.2 故意让 close 在释放任务前失败，实际观测到一个残留任务，随后由测试 owner 补救，明确区分产品清理和测试收尾。Manager 无法发现或强杀任意第三方任务。

## 资源所有权与显式恢复

正常关闭顺序：Host.close（Controller/Manager）→ adapter.close → Input.close → raw Capture.close → 关闭自有 Target → Session.close → StateStore/EventBus.close。Registry/View 只查询，adapter 借用原始资源。即使插件 stop 抛错，Application 仍应在 finally 中完成其余 owner 清理。

真实文本输入响应丢失后，旧动作通道 BLOCKED，不重发。03.2 验证了退役整个运行组合的恢复路径：

1. 等待原调用清理，关闭旧 Host、adapter 和 Input。
2. 调用旧策略的 `create_recovery_target()` 创建不同 ID 的新目标，unbind/bind，准备页面。
3. 新建 Store、Bus、策略、Input、View、Manager、Controller、Host，取得新可信观察。
4. 仅提交新命令。旧 Controller 保持 STOPPED，旧批次不恢复、不重放。

不得把新 Provider 塞进仍引用旧 Input 的 View。复用原始 Capture 时由 Application 确认当前绑定。继续使用同一 Controller 的 recover 接口仍由原 Runtime 提供，其真机测试已随全量复跑；本轮全组合重建没有冒充对旧 Controller 调用 recover。

## 后续模块接入

- **BCA-04 Vision**：沿用 SDK 四项契约，识别实际 PNG、填 source_frame_id、使用 Frame.pixel_to_css。pixel_fixture 只识别受控红蓝色块，不是通用视觉 SDK。
- **BCA-05 CLI**：通过 Host.execute_text 接命令，以 BatchResult 和后续状态反馈结果；保留 Manager 诊断，管理独立资源 owner。日志默认只输出类别、ID、统计，未知输入不得自动重发。
- **BCA-06 Majsoul**：实现业务 schema、置信度、命令语义和动作后条件。本轮没有真实雀魂页面证据；动画、局部 DOM 变化仍需业务层验证。

BrowserFreshness 指纹不等于 DOM 版本，也不提供页面事务。保持 href/timeOrigin/几何不变的局部文档替换，以及检查后发生的页面变化，不属于本轮已证明可拒绝的情形。

## 证据、性能与剩余限制

环境为 Windows / Python 3.14.7 / Edge 157.0.4341.60 / 隔离端口 9341。基线插件专项 58 passed，全量 495 passed、12 skipped；新增 24 项真机插件测试和 2 项部署测试后：

- 全量含真机：**533 passed、0 skipped**，其中 36 项真机、497 项非真机。
- 无真机配置：**497 passed、36 skipped**。
- mypy：66 个源码文件通过；Ruff、格式检查、0.2.0 wheel/sdist 通过。

矩阵覆盖 DPR 1/1.5/2、全图/区域、像素状态、DOM 计数和 Frame/版本/请求/Action ID。故障覆盖丢响应、断连、取消、启动失败、并发关闭与清理诊断。

正式三轮共 54 次矩阵点击：execute_text median/p95 为 6.34/18.90 ms，命令至新状态为 67.16/96.09 ms。每轮另有五次新鲜度恢复点击及约三秒持续观察。不宣称稳定 10Hz、总体性能提升或长期无泄漏。Python tracemalloc、Edge 进程 CPU、Renderer JS heap 均按边界报告，不等于 native/Edge RSS。

证据见 [03.2 实施交接](BCA-03.2_HANDOFF.md)、[性能 JSON](BCA-03.2_PERFORMANCE.json) 和 `.test-artifacts/03.2/plugin-integration-report.json`。最终专用浏览器进程及端口均已退出。

仍待验证：Windows 真实 symlink 权限环境、Python 3.12/3.13、长期压力、native/Edge RSS、生产页面及硬件状态恢复。没有本轮必须修改稳定协议才能完成的协调项。同目标恢复证明、DOM-only 授权、热换插件/Provider、进程沙箱或跨层合并测量若需实现，应另行提交主会话设计。
