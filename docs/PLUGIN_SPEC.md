# 插件开发规范

视觉插件示例为 `examples/plugins/vision_fixture`：initialize 预热 Assets，observe 经标准 CaptureProvider 获取 Frame 并在线程中匹配，handle_command 使用同一 Frame 映射 CSS。歧义不生成动作，输入仍由 Host/Runtime 授权。取消后等待在途原生计算，具体规则见 [VISION.md](VISION.md) 和 [BCA-04_MAIN_SYNC.md](BCA-04_MAIN_SYNC.md)。

核心接口定义在 `bca.core.plugins`；SDK 的 `bca.plugin_sdk.interfaces` 是同一接口的重导出。Plugin 是结构化 typing.Protocol，无须继承某个具体实现。参考 `plugins/example/__init__.py` 和 `tests/plugin_sdk/test_example.py`。

## 元信息与目录

插件提供 `metadata: PluginMetadata`，声明唯一 plugin_id、插件 version、required_capabilities 名称元组。03.1 使用显式可信本机根目录，扫描其直属插件子目录中的 `plugin.toml`，入口固定为 `__init__.py`。setuptools 仅打包 src/bca；业务插件目录和 Manifest 由 Application 单独部署，不自动下载安装或加载。

```toml
[plugin]
plugin_id = "example"
version = "0.2.0"
protocol_version = 2
required_capabilities = ["capture", "input"]
factory = "create_plugin"
```

factory 可省略，默认 create_plugin；其他字段必需，拒绝未知字段、重复能力、布尔协议版本和不兼容协议。版本是非空无空白标识，不做语义版本范围协商。入口导出同步无参工厂，返回新的 Plugin 实例；工厂应只构造对象，资源分配放 initialize 中，Manager 尚不能清理工厂抛异常前未返回的对象。

Catalog 扫描不执行 Python。规范化目录及入口/Manifest 解析后必须仍在允许范围；权限/读取/格式问题归档为 issues，其他候选继续发现；同 ID 的所有冲突来源均不可选。Loader 选中后才以路径摘要命名的独立顶层包导入，支持相对导入，不修改 cwd/sys.path；同路径成功模块进程内复用，每次 load 重新调用工厂。导入失败删除本次新建的该包及子模块，不删除第三方共享依赖。工厂失败不删除已成功导入的模块；无热重载接口，修改代码后应重新启动进程。

插件是可信 Python 代码，加载即执行；目录检查和只读 View 不是恶意插件沙箱。模块/工厂不得私自启动不可回收任务。实例与 Manifest 的四项 metadata 必须一致，方法预检查 async/sync 及可调用签名；实际返回类型仍在每次调用时校验。

## 生命周期和接口

| 方法 | 调用约定 |
| --- | --- |
| `async initialize(context) -> None` | Provider 就绪后调用一次；检查所需能力和配置，取得引用。失败后允许 Core 调用 close 清理部分资源 |
| `async start() -> None` | 初始化后启动，重复启动保持幂等；stop 后可重新 start；close 后禁止启动 |
| `async observe() -> PageState` | 仅运行时调用，插件自行选择 capture 或未来其他能力并解析。Core 发布返回值，插件不再重复发布同一状态 |
| `parse_command(text, *, source="cli") -> Command` | 同步解析，禁止 I/O；非法命令抛 CommandError |
| `async handle_command(command) -> tuple[Action, ...]` | 仅运行时调用，映射成有序动作，可返回空元组；不直接执行浏览器输入 |
| `format_state(state) -> str` | 同步输出格式化，业务展示归插件所有 |
| `async stop() -> None` | 幂等，停止并 await 自有后台任务；保留可重启资源 |
| `async close() -> None` | 幂等，包含 stop，释放插件自有资源；部分初始化失败也必须可清理 |

调用顺序：Core 创建/启动 Provider → 检查 required_capabilities → initialize → start → 串行 observe/handle_command → stop → close → Core 关闭 Provider。Core 关闭时先取消并等待所有在途调用，再关闭资源；清理应在 try/finally 中完成。示例插件没有自有后台任务，重复调用行为由实现和测试展示。

上下文 providers 类型为只读能力端口 `ProviderLookup`（Protocol），支持名称与类型查询。插件可使用 `context.providers.get(CaptureProvider)` 获得类型化能力，不引用具体浏览器库。Runtime 可注入 ProviderRegistry 或其他实现。插件不得注册、关闭或替换 Core 的共享 Provider；此端口是类型约束，不是安全沙箱。

## 状态、事件和配置

插件定义 PageState.data 的业务 schema，用 schema_version 表明结构版本。sequence 在插件实例生命周期内递增，stop/start 后不重置；重建实例可重新起算，未来 Core 应按实例会话区分。来自截图时填写 source_frame_id；来自其他 Provider 时可不填。识别失败应提交明确的 recognition_status/diagnostics，不能伪造成功状态。

本基线采用唯一标准主路径：Core await observe 后 await context.states.publish。插件不得在 observe 内发布同一状态。PluginContext 保留 StateSink 端口供 Runtime 编排及后续扩展，自有推送任务尚未标准化，须在 BCA-02/03 明确调度方式后接入。插件可 await context.events.emit 发布自定义命名空间事件。发布成功后不再修改模型内部 dict/list，也不得修改构造模型时传入的原始载荷引用。

正式命令入口为 `await host.execute_text("click 12 23")`。PluginRuntimeHost 通过 Controller 暂停观察、取得已提交快照和原引用、调用 parse/handle、提交 ActionBatch，最后仅恢复自己暂停的观察。不要在产品路径绕过 Host 直接执行 InputProvider；旧的 SDK 直接实例化测试仅验证底层 Plugin Protocol 兼容。无需浏览器的完整例子为 `examples/plugin_runtime.py`。

当前数据模型为关键字参数 dataclass，枚举显式传入，不进行字符串自动转换；插件元信息和配置也遵循此约定。模型非法参数抛 `bca.core.errors.ValidationError`，命令语义错误抛 CommandError；如需 JSON 交换使用 protocol 的独立 codec。

PluginConfig.values 是 JSON 兼容配置；插件负责业务配置验证。示例使用 page_id（默认 demo）。Logger 由 Application/Core 注入，插件不配置全局日志。

## 示例行为

ExamplePlugin 需要 capture 和 input；observe 捕获指定页面并报告图像宽高。`click 12 23` 转换成以 CSS 视口坐标定位的左键点击 Action，携带原请求 ID。Core 执行动作并收集结果。该示例没有识别算法、截图坐标自动定位或真实浏览器依赖。

## 03.1 公开管理接口

以下类型均从 `bca.core.plugins` 导出；原 Plugin/PluginMetadata/PluginConfig/PluginContext 的定义移至内部 contracts.py，原导入路径和 SDK 四项重导出不变。新模型不进入 Protocol 2 codec。

```text
PluginDescriptor(*, plugin_id: str, version: str, protocol_version: int,
                 required_capabilities: tuple[str,...], directory: Path,
                 factory: str="create_plugin")
PluginDiscoveryIssue(*, source: Path, error_type: str, message: str, plugin_id=None)
CatalogSnapshot(*, candidates=(), issues=())
PluginSnapshot(*, plugin_id, version, state: PluginLifecycleState,
               required_capabilities=(), last_error=None,
               cleanup_status="not_started", cleanup_error=None)
PluginCatalog(roots: Sequence[Path])
    discover() -> CatalogSnapshot
    get(plugin_id: str) -> PluginDescriptor
PluginLoader()
    load(descriptor: PluginDescriptor) -> Plugin
PluginManager(catalog, *, providers, states, events, logger, loader=None)
    load(plugin_id: str, *, config: PluginConfig | None=None) -> None
    async initialize/start/stop/close() -> None
    async observe() -> PageState
    parse_command(text: str, *, source="cli") -> Command
    async handle_command(command: Command) -> tuple[Action,...]
    format_state(state: PageState) -> str
    snapshot() -> PluginSnapshot
ProviderLookupView(base: ProviderLookup, *, overrides: Mapping[str,Provider] | None=None)
    get(str | type[P]) -> Provider | P
    available(str | type[Provider]) -> bool
FreshnessCaptureAdapter(session, raw_capture: CaptureProvider, policy: BrowserFreshness)
    available: bool
    async start/close() -> None
    async capture(page_id: str) -> Frame
PluginRuntimeHost(manager, controller: RuntimeController, states: StateStore)
    async start/close() -> None
    async execute_text(text: str, *, source="cli") -> BatchResult
    snapshot() -> StateSnapshot | None
    format_current_state() -> str | None
```

Manager config 可省略，每个 Manager 新建独立默认 PluginConfig。get 仅查询最近 discover 的快照，不隐式重新扫描。上面的集合和诊断模型为 frozen kw-only dataclass，Path 为已解析实际来源；数据模型不可变不意味着对 Python 插件安全隔离。

新增错误均继承 PluginError：PluginManifestError（plugin.manifest）、PluginDuplicateIdError（plugin.duplicate_id，同时继承 ManifestError）、PluginLoadError（plugin.load）、PluginCompatibilityError（plugin.compatibility）、PluginContractError（plugin.contract）。非法生命周期使用 LifecycleError；调用插件抛出的普通异常原样传播，诊断仅保存类名。Manifest 逐项问题保留安全类别，不将原始 TOML/异常文本写入诊断。Loader import/factory 包装错误保留 cause。能力验证在 initialize 前对 capture/input 使用 ABC 类型查询，其他能力按名称查询；保留 CapabilityNotFoundError/TypeError/UnavailableError 原类别，并附 plugin_id。

## 插件自有资产（04.1）

插件可在 initialize 创建 `bca.plugin_sdk.assets.AssetStore`，按语义 ID 和场景获取只读 LoadedTemplate，在 close 关闭 Store。AssetStore 只管理自己的模板缓存，不发布状态或关闭共享 Provider；同步文件 I/O 和解码应在初始化预热或由上层明确安排线程。公开规则与 04.2 输入契约见 [ASSETS.md](ASSETS.md)，实际验证见 [04.1 交接](BCA-04.1_HANDOFF.md)。

## Manager 状态与取消

| 当前状态/操作 | 成功结果 | 失败/取消 |
| --- | --- | --- |
| CREATED / load | LOADED | 保持 CREATED，可修复候选后重试，last_error 记录 |
| LOADED / initialize | INITIALIZING→INITIALIZED | FAILED，等待一次部分 close，保留原异常 |
| INITIALIZED 或 STOPPED / start | STARTING→RUNNING | FAILED，等待一次部分 close |
| RUNNING / start、已初始化 / initialize | 幂等 | CLOSED/FAILED 等不允许重复初始化 |
| RUNNING/STARTING/INITIALIZING / stop | STOPPING→STOPPED；若启动被取消并已 close 则 FAILED | stop 失败记录原异常并 close |
| CREATED/LOADED/INITIALIZED/STOPPED/FAILED / stop | 无操作 | 不凭空把未初始化实例变为可启动 |
| 任意状态 / close | CLOSING→CLOSED | close 回调失败仍 CLOSED，cleanup_status=failed、cleanup_error 保存类别 |

每个 Manager 仅选择一个插件，不提供 unload/替换；新激活创建新 Manager。STOPPED 插件可 start，但 Host/Controller 为一次性组合，已关闭的 Host 不能重启。close 依 Plugin Protocol 调用插件自身 close（其负责 stop），Host 正常关闭会先显式 Manager.stop，再 close。

Manager 用同一个锁串行 initialize/start/observe/handle/stop/close；每次插件异步调用用一个受跟踪任务，在取消时只请求一次取消并等待其 finally 清理。stop/close 先改变接纳状态，再等待锁；多个等待者共享终止任务，取消某个等待者不会取消清理。插件回调不能 await 自身 Manager 生命周期/操作，直接拒绝以免自锁。同步 parse/format 不执行 I/O；组合入口负责与异步工作协调，CLI 应只通过 Host 发命令。

初始化/启动失败时的 close 错误不会掩盖主异常；snapshot 同时保留 last_error 和 cleanup_error。正常 close 的回调异常归档到 snapshot，不重新抛出；stop 的主异常会传播，Host 仍在 finally 中 close。FAILED 后不能继续使用实例。第三方若忽略取消或永不结束清理，Manager 不强杀；插件自建任务仍由插件负责取消并 await，Manager 只追踪自身发起的调用。

## Browser/Runtime 组合与所有权

Application 先启动 Session/raw_capture/input，创建 Store/Bus 和 `BrowserFreshness(session, states)`，Input 推荐使用 policy.create_input_provider 获取恢复来源。创建并启动 FreshnessCaptureAdapter；给 Manager 注入 ProviderLookupView，capture override 为 adapter、input override 为与 Controller **同一个** Input 对象。Controller 的 observe 必须是 manager.observe，使用同一个 states/policy。Host.start 依序 initialize→plugin.start→controller.start。

这些引用的一致性是组合入口的前置条件；Host 不通过读取 Runtime 私有属性反查/替换注入对象。`examples/plugin_browser.py:assemble` 提供显式装配函数，返回未启动 Host 与已启动 adapter；由 Application 先 await host.close，再 adapter.close，然后 input→raw_capture→session→Store/Bus。Host 仅拥有 Manager/Controller，不隐式关闭适配器或原始资源。

View 只复制 override 映射，不复制或拥有 Provider；字符串/类型查询取得同一实际对象，类型与就绪校验沿用 Registry 分类，非法查询仍抛 ValidationError。adapter.start/close 仅变更自己状态；capture 检查当前页面及 readiness 后只调用 policy.capture(raw_capture)，返回原 Frame，不递归注入自身、不关闭原资源。

Host 命令锁一次只处理一条命令；如果原 Controller RUNNING，先 pause 并等待观察完成，在同一无 await 段取得 snapshot/ref。必须有匹配版本及当前插件身份，再 parse/handle；ActionBatch 使用原 ref 与 Command.request_id。观察生成期间暂停，外部改状态导致 STALE 也不能换新 ref 重投。原 Controller PAUSED 时 Host 不自行恢复。缺少观察抛 LifecycleError；调用方等待新状态后重新生成命令。

execute_text 取消会取消本条工作并等待 Manager/Runtime 清理，排队取消不影响已执行命令。close 先禁止新工作，Controller.stop 先结束实际输入，再取消并 await 正在解析/生成动作的 Host 命令，最后 Manager.stop/close；关闭期间 finally 不恢复观察。Host 被取消的 start 会启动完整有序关闭并等待，关闭等待者自身取消不撤销共享终止。插件回调和 Input.execute 不得回调 Host.execute_text/close，命令由外部发起。

Runtime 的 STALE/FAILED/BLOCKED/CANCELLED、输入 uncertain、首错停止和新目标恢复规则不变。Host 返回 BatchResult 原对象；ActionStatus.CANCELLED 的 Provider 结果仍由 Runtime 决定批次终态，Host 不重解释。恢复涉及 Provider 更换时应由 Application 重新组装一致的 Manager/View/Host，或在未来独立设计的恢复流程中协调全部引用；本阶段不新增 Host 热替换 API。

03.1 仅完成模拟 Provider 与本机模拟 CDP 验收；真实 Edge、实际传输故障和性能验证属于 03.2，不使用此前 Runtime 真机数字冒充本阶段结果。完整交接见 [BCA-03.1_HANDOFF.md](BCA-03.1_HANDOFF.md)。


## ???????????03.2?

```powershell
$env:BCA_CDP_ENDPOINT='http://127.0.0.1:9341' # ???????????
.\.venv\Scripts\python.exe examples/plugin_integration.py --endpoint $env:BCA_CDP_ENDPOINT --output .test-artifacts/03.2/example --samples 3 --duration 3
.\.venv\Scripts\python.exe -m pytest tests/core/plugins -m browser_integration -v -W error --basetemp=.test-artifacts/pytest-plugins-edge
```

?????????????????????? cwd ???`examples/plugins/pixel_fixture` ???????? marker ??????????????????? PNG ??? Frame.pixel_to_css ?????DOM ??????? oracle?????? SDK ???????? Composition?RegionCapture?EvidenceController ?????????? Core ?? API?

Application ???????? manager/controller ???`host.snapshot()` ???????????????????? `manager.snapshot().cleanup_status/cleanup_error` ? `controller.snapshot()`??????????????????? close ????????????Manager ????????????????????????????? owner ?????? CLOSED ????????

?????????????????????? ? ??? Host/adapter ? ??? Input ? `old_policy.create_recovery_target()` ? unbind/bind ??? ? ???? ? ? Store/Bus/policy/Input/View/Manager/Controller/Host ? ????? ? ????? Controller ?? STOPPED???????????????? Controller ? recover ?????? Runtime ???????????????????? Capture ??? Application ????????????????????? Input ?? View?
