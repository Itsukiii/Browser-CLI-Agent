# BCA-03.1 — Plugin Core 与 Runtime 接入 / Codex 开发提示词

> 任务编号：BCA-03.1  
> 所属子系统：BCA-03 / Plugin System  
> 状态：接口设计已确认，待 Codex 实施与验证  
> 日期：2026-11-18  
> 开发仓库：https://github.com/Itsukiii/Browser-CLI-Agent  
> 固定参考提交：`550cdfa0b042e4cee95f0d7f53e88a7d84d62c43`（`main`，提交名 `BCA-02`）  
> 当前协议：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 本阶段结束产物：`docs/BCA-03.1_HANDOFF.md`

## 0. Codex 角色与工作方式

你是 Browser CLI Agent（BCA）项目的 BCA-03.1 实施工程师。请在**已有的统一 `bca/` 工作仓库**中完成代码、测试、示例与文档。本提示词是已经讨论确定的实施方案；以仓库中实际、已验收的公开接口为准，必要时在新实现内部作合理的局部细化。

开始前执行：

1. 检查 `git status --short`、`git branch --show-current`、`git rev-parse HEAD`，确认当前工作区及变更状态。参考提交用于识别接口基线；尊重当前分支现有合法改动，不覆盖未提交工作。
2. 阅读 `docs/PLUGIN_SPEC.md`、`docs/INTERFACES.md`、`docs/RUNTIME.md`、`docs/ARCHITECTURE.md`、`docs/BCA-01_MAIN_SYNC.md`、`docs/BCA-02_MAIN_SYNC.md`。
3. 核对 `src/bca/core/plugins/`、`providers/`、`runtime/`、`browser/`、`plugin_sdk/interfaces/`，`plugins/example/`、`tests/plugin_sdk/test_example.py`、现有 Runtime 测试与 examples；核对实际类型、异常、构造参数和生命周期。
4. 使用下文 A→B→C→D 四个批次实施，每批先完成功能及定向测试，再进入下一批；最后执行全量验证并形成交接报告。
5. 如果发现确需变更 BCA-00/01/02 的**稳定公共协议或已验收公开接口**，记录独立的架构变更提案及影响，不先行实施破坏性调整；其余 BCA-03 自有接口按本方案开发。

请以**实际命令输出、实际测试数字和实际修改文件**报告结果。不要把静态检查、模拟测试或以往交接数字称为本次已运行的测试。

## 1. 固定架构决策与交付目标

**已确定：**

- 插件来源：**静态 `plugin.toml` Manifest + 显式插件目录**，扫描候选时只读元数据；选中后才导入插件 Python 代码。
- 活动实例：**每个 PluginManager 一个活动插件实例，允许目录存在多个候选**。每个活动插件通过独立的一次性 Runtime 组合运行。
- 插件入口：固定插件目录 `__init__.py`，Manifest 声明无参工厂 `create_plugin`，工厂返回满足现有 `Plugin` Protocol 的新实例。
- 管理与组合分离：`PluginManager` 管理插件实例、Context、生命周期；`PluginRuntimeHost` 管理一次 Runtime 组合、命令协调与有序终止。
- BCA-05 CLI 的主要集成入口：`PluginRuntimeHost.execute_text()`；浏览器新鲜度和动作权限由现有 `RuntimeController` / `BrowserFreshness` 负责。
- Protocol 2、`Plugin/PluginContext/PluginMetadata/PluginConfig`、Provider ABC、RuntimeController 的现有对外调用语义保持兼容。

**03.1 完成目标：** 从配置目录发现并选择 example 插件，加载校验，注入借用 Provider，完成 initialize/start/stop/close；通过模拟 Provider 与 RuntimeController 演示 Plugin.observe → StateStore → Plugin.parse/handle → ActionBatch → BatchResult，验证截图来源授权、状态独占发布、并发、取消与异常清理。

## 2. 已核验的上游契约（按源码复核）

- `bca.core.plugins`：现有 `PluginMetadata(plugin_id, version, required_capabilities=(), protocol_version=2)`、`PluginConfig(values={}, protocol_version=2)`、`PluginContext(providers, states, events, logger, config)`；`Plugin` 包含 async `initialize/start/observe/handle_command/stop/close` 与同步 `parse_command/format_state`。`Plugin` 是 `typing.Protocol`，按结构及调用边界校验。
- `bca.core.providers`：`ProviderRegistry.register/get/available`、`ProviderLookup.get/available`；`Provider` 有 `capability`、`available`、`start/close`。`CaptureProvider.capability="capture"`，`InputProvider.capability="input"`。`get()` 可区分 `CapabilityNotFoundError`、`CapabilityTypeError`、`CapabilityUnavailableError`，`available()` 会合并这几种情况。Registry 仅注册与查询，不负责释放。
- `bca.core.runtime`：`StateStore`、`EventBus`、`BrowserFreshness`、`RuntimeController(observe, provider, states, context, events=None, *, interval=0.1, capacity=32, observation_timeout=10.0, event_timeout=0.05)`、`ActionBatch(actions, observation, request_id, ...)`、`ActionObservationRef`、`BatchResult`。`controller.start/pause/resume/submit/stop/recover` 是 async；`controller.reference()`、`states.snapshot()` 是同步查询。Controller.stop 终止且不能再 start。
- `BrowserFreshness(session, states)`：观察必须通过 `await policy.capture(raw_capture)` 记录真实 Frame；`PageState.source_frame_id` 必须匹配该观察实际返回的 Frame；提交之后才能获得可信 `controller.reference()`。引用是本进程对象身份，不可复制字段后冒充；动作前会重新校验绑定/页面/几何/版本。
- 观察由 Runtime 的 `ObservationPipeline` 唯一发布一次；Plugin.observe 只返回 `PageState`。Plugin.handle_command 只返回有序 `tuple[Action, ...]`，由 Controller.submit 顺序执行。`SUCCEEDED` 为浏览器输入已确认；STALE/BLOCKED 等按照 Runtime 原义处理。
- BrowserSession、原始 Capture/Input Provider、StateStore/EventBus 由 Application 组合入口拥有；Runtime 仅拥有自身工作任务；插件只负责自身任务和数据。正常关闭顺序为 Controller → Plugin → Input → Capture → Session → Store/Bus。

注意：当前 `docs/PLUGIN_SPEC.md` 的旧示例演示裸 InputProvider.execute，`docs/RUNTIME.md` 和 `docs/ARCHITECTURE.md` 的部分早期文字仍可能称 ActionPipeline 待实现；更新有关章节，以**已经交付的 RuntimeController 实际行为**为准。

## 3. Batch A：Manifest、Catalog、Loader

### 3.1 插件目录与 Manifest

在 `plugins/example/plugin.toml` 增加静态信息：

```toml
[plugin]
plugin_id = "example"
version = "0.2.0"
protocol_version = 2
required_capabilities = ["capture", "input"]
factory = "create_plugin"
```

约定：一个候选插件占一个 `plugins/<name>/` 目录，入口固定 `__init__.py`；`factory` 为模块内有效标识符、默认推荐 `create_plugin`；示例插件导出：

```python
def create_plugin() -> Plugin:
    return ExamplePlugin()
```

保留已存在的 `ExamplePlugin` 类和已有直接实例化测试。项目顶层 `plugins/` 当前不是 setuptools 自动发布的 `bca` 包；发现过程基于显式 `Path`，不以当前工作目录是否恰好在 `sys.path` 为前提。

### 3.2 公开数据模型（建议）

将新增类型集中置于 `src/bca/core/plugins/models.py`，从 `bca.core.plugins` 重导出。采用 frozen、关键字初始化 dataclass（风格与现有工程一致），可根据实际需求加诊断字段：

```python
@dataclass(frozen=True, kw_only=True)
class PluginDescriptor:
    plugin_id: str
    version: str
    protocol_version: int
    required_capabilities: tuple[str, ...]
    directory: Path
    factory: str


@dataclass(frozen=True, kw_only=True)
class PluginDiscoveryIssue:
    source: Path
    error_type: str
    message: str
    plugin_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class CatalogSnapshot:
    candidates: tuple[PluginDescriptor, ...]
    issues: tuple[PluginDiscoveryIssue, ...]
```

`PluginDescriptor` 是静态候选信息，并不是已执行或已验证的 Plugin 实例。目录和插件 ID 映射保持确定性，Catalog 快照只读。

### 3.3 PluginCatalog

```python
class PluginCatalog:
    def __init__(self, roots: Sequence[Path]) -> None: ...
    def discover(self) -> CatalogSnapshot: ...
    def get(self, plugin_id: str) -> PluginDescriptor: ...
```

行为：

1. 同步扫描**已配置的本机可信根目录**下的直属候选插件子目录，读取 `plugin.toml`；按规范化路径稳定排序；使用标准库 `tomllib` 解析。
2. 逐项检查 Manifest 的名称、类型、必需字段、协议版本及 `required_capabilities` 唯一性；目录下必须存在 `__init__.py`。验证规范化路径与符号链接解析后仍在允许的插件根下；合理处理非目录、权限与读取失败。
3. 当多个候选声明相同 `plugin_id`，所有冲突项均标记为不可选，输出包含所有冲突来源的诊断；不以路径顺序决定胜者。其他合法候选继续可用。
4. 非法候选进入 `issues`，不导致全部扫描失败。`get` 只能返回该次已发现且无冲突的候选，对缺失/歧义 ID 抛明确错误。
5. 扫描阶段没有插件导入或工厂调用；用户可枚举插件 ID、版本、所需能力、来源与验证结果。

### 3.4 PluginLoader

```python
class PluginLoader:
    def load(self, descriptor: PluginDescriptor) -> Plugin: ...
```

- 以 `importlib.util.spec_from_file_location` 装载固定 `__init__.py`，启用包目录的 `submodule_search_locations`，支持插件包内部相对导入（如 `from .worker import ...`）。
- 给每个规范化源路径建立稳定且唯一的内部模块命名空间（例如路径摘要），按 Python 包规则建立父包并维护 `sys.modules`，避免相同 basename 的不同插件相互覆盖。不得依赖全局切换 `cwd` 或长期修改 `sys.path`。
- **模块缓存**：成功导入的同一路径模块在本进程复用；每次 `load` 都调用工厂获得新实例；导入失败回滚本次产生的父/子模块记录，避免半初始化包残留。
- 验证工厂存在、可调用且为约定的无参调用形式；工厂抛出异常时返回可诊断 `PluginLoadError`，保留原始异常链供开发定位（安全日志只记录类型）。
- 校验实例拥有正确 `PluginMetadata`、必需方法及签名形状；Manifest 与实例 metadata 的 `plugin_id/version/protocol_version/required_capabilities` 必须逐项一致。预检查异步/同步约定，实际返回值在每次方法调用边界继续检查。
- 明确插件来源为**可信本机 Python 代码**，加载是代码执行；文件读取时防止路径逃逸是一致性边界，并不构成恶意代码的安全沙箱。

## 4. Batch B：Validation、PluginManager 与生命周期

### 4.1 版本及能力校验

- `protocol_version` 与 `bca.core.protocol.PROTOCOL_VERSION` 精确相等；拒绝布尔值和不兼容版本。插件自身 `version` 是独立版本标识，`PageState.schema_version` 是业务数据版本，不互作兼容依据。
- 在 `initialize()` 前通过实际注入的 `ProviderLookup.get()` 校验所需能力；对 `capture`、`input` 使用 `get(CaptureProvider)`、`get(InputProvider)` 验证类型和就绪状态；其他能力通过字符串 token 查询。保留未注册、类型错误、未就绪三个错误类别及关联 plugin_id。
- PluginConfig 沿用既有 `JsonObject` 校验，业务配置规则由具体插件处理。未传的配置使用独立默认 `PluginConfig()`，Context 持有原配置且按不可变约定使用。

### 4.2 错误与诊断

在 BCA-03 内定义稳定的错误类并导出，推荐继承 `bca.core.errors.PluginError`：

- `PluginManifestError`
- `PluginDuplicateIdError`
- `PluginLoadError`
- `PluginCompatibilityError`
- `PluginContractError`

非法生命周期沿用 `LifecycleError`；已有 Provider 能力错误分类保留。`PluginSnapshot` 包含 `plugin_id/version/state/required_capabilities/last_error/cleanup_status`（可根据源码风格微调字段，文档须给出准确签名），`last_error` 仅记录安全错误类别。可记录合理的状态转换与耗时，日志不输出用户输入正文、图片字节、敏感键序列或完整未知异常内容。

### 4.3 PluginManager 公开接口

```python
class PluginManager:
    def __init__(
        self,
        catalog: PluginCatalog,
        *,
        providers: ProviderLookup,
        states: StateSink,
        events: EventSink,
        logger: Logger,
        loader: PluginLoader | None = None,
    ) -> None: ...

    def load(self, plugin_id: str, *, config: PluginConfig) -> None: ...
    async def initialize(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def close(self) -> None: ...
    async def observe(self) -> PageState: ...
    def parse_command(self, text: str, *, source: str = "cli") -> Command: ...
    async def handle_command(self, command: Command) -> tuple[Action, ...]: ...
    def format_state(self, state: PageState) -> str: ...
    def snapshot(self) -> PluginSnapshot: ...
```

- 一个 Manager 选择并持有一个活动插件实例；Catalog 列出多个候选。装载完成后创建由 Core 提供的 `PluginContext(providers, states, events, logger, config)`，按规定顺序调用插件。
- 状态覆盖 `CREATED → LOADED → INITIALIZING → INITIALIZED → STARTING → RUNNING → STOPPING → STOPPED → CLOSING → CLOSED`；部分失败可进入 `FAILED`，但仍要执行适当清理并记录结果。定义 `PluginLifecycleState(StrEnum)` 与明确的转换表。
- `initialize` 仅真正调用一次；`start` 在 RUNNING 幂等，插件 STOPPED 可再次 start（符合既有 Plugin Protocol）；`stop` 和 `close` 幂等；CLOSED 终态。初始化失败或启动失败执行部分资源 `close`，清理异常不掩盖主错误，并能够读取清理结果。
- 通过生命周期锁、共享终止任务、可等待的在途工作跟踪，处理同时 stop/close、取消任一等待者、observe/handle 与终止竞争。不能持有互相等待的锁造成关闭死锁。可对插件 observe 与 handle_command 使用同一异步操作锁，保证实例方法不与其生命周期终止交错。
- Manager 自己不发布 `PageState`、不执行 `Action`；其 `observe()` 仅返回且检查 `PageState.plugin_id == metadata.plugin_id`，`handle_command()` 仅返回且验证 `tuple[Action, ...]`，`parse_command()` 检查 `Command`，`format_state()` 检查 `str`；生命周期方法检查按协议返回 `None`。异常保留适当分类并记录诊断。
- 插件自建任务由插件 `stop/close` 负责取消并 await；Manager 在终止插件前确保它自己已发起的 observe/handle 调用得到处理。对协作取消的插件作完整测试，避免假设可强行终止忽略取消的第三方代码。

## 5. Batch C：ProviderLookupView、FreshnessCaptureAdapter、PluginRuntimeHost

### 5.1 ProviderLookupView

实现一个满足 `ProviderLookup` 的只读对象，仅公开 `get()` 与 `available()`：

```python
class ProviderLookupView:
    def __init__(
        self,
        base: ProviderLookup,
        *,
        overrides: Mapping[str, Provider] | None = None,
    ) -> None: ...
```

它可为 `capture` 等指定能力覆盖查询结果，其余委托原 ProviderLookup。字符串查询和类型查询必须获得相同能力的对应实际对象；类型查询需要 `isinstance(provider, requested_type)` 验证；`available()` 与既有 Registry 语义一致（非法输入仍抛校验异常）。覆盖时检查 capability 名称匹配及资源实际 readiness，不复制/拥有 Provider，保持 Runtime 依赖对象身份一致。

### 5.2 FreshnessCaptureAdapter

```python
class FreshnessCaptureAdapter(CaptureProvider):
    def __init__(
        self,
        session: BrowserSession,
        raw_capture: CaptureProvider,
        policy: BrowserFreshness,
    ) -> None: ...

    @property
    def available(self) -> bool: ...
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def capture(self, page_id: str) -> Frame: ...
```

- `capture` 验证请求 `page_id` 与当前 Session 绑定一致、适配器及原始 Provider 可用，随后只执行 `await policy.capture(raw_capture)`，将实际返回 Frame 原样交给插件；新鲜度与 Frame 来源校验继续由 policy 负责。
- 适配器启停只改变自己持有的可用状态；原始 BrowserCaptureProvider 由外部 owner 启动/关闭。`close` 不关闭借来的 Session/Provider；调用方按照 Runtime 退出顺序先等待观察结束再关闭适配器与原始资源。
- 注入给插件的 `get(CaptureProvider)` 与 `get("capture")` 必须返回本适配器；policy.capture 的参数必须是原始 Provider，以免适配器递归调用自身。
- `InputProvider` 查询必须与构造 RuntimeController 时传入的实际 Provider 为同一对象（Browser 恢复 provenance 及统一动作通道）。BrowserFreshness 的输入 Provider 初次创建推荐通过 `policy.create_input_provider()` 取得并由 owner start/close，以支持既有显式恢复来源校验。

### 5.3 PluginRuntimeHost 公开接口

```python
class PluginRuntimeHost:
    def __init__(
        self,
        manager: PluginManager,
        controller: RuntimeController,
        states: StateStore,
    ) -> None: ...

    async def start(self) -> None: ...
    async def execute_text(self, text: str, *, source: str = "cli") -> BatchResult: ...
    def snapshot(self) -> StateSnapshot | None: ...
    def format_current_state(self) -> str | None: ...
    async def close(self) -> None: ...
```

Host 是**一次激活使用的一次性组合**。构造时 Controller 尚未启动，`observe` 回调绑定到 `manager.observe`，Controller 使用同一 `StateStore` 与来自 BrowserFreshness 的 RuntimeContext；Host.start 的前置条件是外部资源 ready、适配器 ready、必要 Provider 经验证。由 Host 完成 `manager.initialize → manager.start → controller.start`，失败时执行其已拥有组件的有序关闭。

明确提供一个示例/工厂函数演示完整装配，而不依赖隐藏全局单例：

```text
BrowserSession ready / raw_capture ready / input_provider ready
    → StateStore + EventBus + BrowserFreshness(session, states)
    → FreshnessCaptureAdapter(session, raw_capture, policy).start()
    → ProviderLookupView(..., overrides={"capture": adapter, "input": input_provider})
    → PluginManager(..., providers=view, states=states, events=events, logger=logger)
    → manager.load("example", config=PluginConfig(values={"page_id": page_id}))
    → RuntimeController(manager.observe, input_provider, states, policy, events)
    → PluginRuntimeHost(manager, controller, states)
    → host.start()
```

**命令路径（`execute_text`）**：

1. 获取 Host 命令锁；确认 Host 接受新工作、Manager 活动且 Controller 可用。同步标记执行中的命令，便于 close 协调。
2. 若 Controller 正在 RUNNING，则 `await controller.pause()` 并等待当前观察结束；若本来由上层 PAUSED，保留原暂停意图。
3. 在同一无 await 片段取得 `snapshot = states.snapshot()`、`ref = controller.reference()`；验证都有值、`snapshot.version == ref.version`、`snapshot.state.plugin_id` 属于当前插件。缺少可信观察时返回明确的前置状态错误，待新观察生成后由调用方重新生成命令。
4. 调用 `command = manager.parse_command(text, source=source)`；`actions = await manager.handle_command(command)`；在动作生成完成前保持观察暂停。检查返回数据满足公共 Command/Action 契约。
5. 使用**刚才保存的原始 ref 对象**构造 `ActionBatch(actions=actions, observation=ref, request_id=command.request_id)`；`await controller.submit(batch)`，将 `BatchResult` 原样返回；空 Action 元组按 Runtime 原语义提交。
6. 在 `finally` 中释放协调锁，并仅在 Host 自己暂停过且 Controller 尚处于可恢复运行状态时恢复观察；异常或取消不改变 Runtime 的 STALE/BLOCKED/CANCELLED/FAILED 决策。不换引用重投旧动作。

**并发与关闭**：Host.close 先拒绝新命令，再停止 Controller（使在途输入按照 Runtime 协议取消并 await 清理）、协调/取消尚在插件解析或动作生成阶段的 Host 命令并 await 结束，最后 Manager.stop/close。使用共享可等待关闭任务使重复 close 和被取消的关闭等待者不会重复终止；恢复观察的 `finally` 不得在 Host 正在关闭时对 STOPPING/STOPPED Controller 执行 resume 或掩盖原异常。Host 本身只关闭 Manager/Controller/自建适配器等**明确拥有**的组件；外部 Session、原始 Provider、Store、Bus 由组合入口按既有顺序收尾。

Manager 或插件的 observe/Input.execute 回调不能 await 自身 Controller 的生命周期或 submit 接口；新命令必须从 Host 的外部调用者发起。`format_current_state()` 读取最新 Store 快照并交给活动插件同步格式化，遵循单个插件身份和业务格式化异常的诊断规则。

## 6. Batch D：示例、文档与测试

### 6.1 推荐文件落位

```text
src/bca/core/plugins/
    __init__.py          # 保留原 Plugin/Metadata/Config/Context/Protocol 导出，新增公开导出
    models.py            # Descriptor、Issue、Snapshot、LifecycleState
    catalog.py           # Manifest 扫描与候选集合
    loader.py            # Python 模块/工厂装载
    validation.py        # metadata、能力及接口形状检查
    manager.py           # 单插件实例与生命周期
    lookup.py            # ProviderLookupView
    capture_adapter.py   # FreshnessCaptureAdapter
    host.py              # PluginRuntimeHost
    errors.py            # BCA-03 自有异常（或按仓库风格并入合适位置）
plugins/example/
    plugin.toml
    __init__.py          # 增加 create_plugin 工厂，保留原类
examples/
    plugin_runtime.py    # 无真实 CDP 依赖的示例运行组合
    plugin_browser.py    # 可选的实际 Browser 装配示例骨架/入口，真实回归在 03.2
 tests/core/plugins/     # 单元、故障注入、模拟 Runtime 组合
 docs/
    PLUGIN_SPEC.md
    INTERFACES.md
    ARCHITECTURE.md
    RUNTIME.md            # 仅修正已过时的描述，维持既有公共契约
    BCA-03.1_HANDOFF.md
```

可根据实际目录和风格整合文件，重要的是上述职责和公开入口保持清楚；`plugin_sdk/interfaces/__init__.py` 继续重导出既有 Plugin Protocol 基线，保持原测试兼容。

### 6.2 必测用例与通过条件

**发现/加载：**

- 多候选静态发现且扫描阶段没有 import 副作用；多个根、稳定排序与 ID 查询。
- Manifest 缺失、语法错误、字段非法、协议错误、目录缺少 `__init__.py`、路径/符号链接越界、读取失败的稳定诊断；某项错误不影响其他候选。
- 重复 ID 各来源一律被拒绝选择；不同来源但包名相同能正确加载自身的相对导入模块。
- 不存在工厂、非无参工厂、导入抛错、工厂抛错、返回错误实例、metadata 与 Manifest 不一致；失败不留下本次半导入缓存。
- 同一模块成功缓存、多次工厂调用返回不同插件实例；发现后不依赖当前工作目录。

**校验/生命周期：**

- Protocol 2 精确校验；插件版本与 schema 版本各自独立；能力未注册、类型不符、暂未就绪分别可诊断。
- 初始化成功、重复初始化、启动停止、STOPPED 后插件重新启动、重复 stop/close、CLOSED 终态。
- initialize/start 中途异常、取消、close 抛错、同时 close、多等待者取消；错误可观察，清理等待可重复；不误关闭共享 Provider。
- observe/parse/handle/format 返回错误类型，PageState.plugin_id 错配、Action 元组含非法成员；运行与关闭竞争不遗留 manager 自身工作。

**Runtime/Provider 接入：**

- View 的字符串/类型查询一致，返回正确适配器和实际 Input 实例；借用资源正常关闭后仍由 owner 存活。
- 使用替身 `BrowserFreshness` 或已有模拟 CDP 同行测试证明：实际截图仅经 `policy.capture(raw_capture)`，Frame 不被改写，`source_frame_id` 正确，单次有效 observe 仅一次 Store.publish，版本正确。
- `host.execute_text()` 基于原始 `ActionObservationRef` 生成动作并提交，结果及 request_id/action_id 正确；没有有效引用时报明确前置条件错误。
- STALE、FAILED、BLOCKED、CANCELLED 与输入不确定状态沿用 Runtime 结果；动作生成时状态被其他参与者改变也不能使用替换的新引用直接提交旧动作。
- 并发多命令、observe/handle 与 stop/close 竞争、取消 pause 等待者、取消排队/执行命令、重复关闭，都保证在途任务有确定结束/清理路径；不发生死锁或在关闭后继续提交动作。

**回归与质量：**

- 保留并通过 `tests/plugin_sdk/test_example.py` 与已有 BCA-00/01/02 测试。
- 使用无需浏览器的模拟闭环：Catalog → Loader → Manager → Host → Plugin.observe → StateStore → parse/handle → ActionBatch → BatchResult → 收尾。
- 精确记录测试执行方式、跳过数和运行平台；本阶段主要以模拟 Provider/Runtime 验收，真实 Edge 浏览器故障/回归属于 BCA-03.2。
- 使用 Python 3.12+ 语法和项目现有 mypy strict、Ruff 规则，保证 wheel/sdist 构建可用。

### 6.3 建议实际检查命令

按仓库解释器与工作系统调整 Python 可执行路径、临时测试目录及环境变量：

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/core/plugins tests/plugin_sdk/test_example.py -q
python -m pytest -q
python -m mypy
python -m ruff check .
python -m ruff format --check .
python -m build
```

真实浏览器测试若需显式 CDP endpoint，按现有 `pytest` marker/环境约定执行并在报告中单列。可增加 `python examples/plugin_runtime.py` 作为无需浏览器的 smoke test。

## 7. 对外交接与文档更新

完成后更新 `docs/PLUGIN_SPEC.md`：

- 插件目录/Manifest 字段、可信来源、加载与工厂约定；安装打包边界。
- PluginCatalog、Loader、Manager、ProviderLookupView、FreshnessCaptureAdapter、PluginRuntimeHost 的实际可导入入口、准确签名及错误类型。
- 版本、能力、插件实例生命周期、取消、资源 owner、Host 关闭顺序及示例。
- 插件状态与 Runtime version 的关系、观察来源授权、一次提交和动作 BatchResult 的语义。
- CLI 如何使用 Host，以及动作引用来源/恢复边界。

对 `docs/INTERFACES.md` 只补充新的 BCA-03 扩展入口和兼容约定；`docs/ARCHITECTURE.md`、`docs/RUNTIME.md` 的历史“未实现”文字与实际交付源码对齐。保留相关 BCA-00/01/02 的已验收接口和过去报告。

新建 `docs/BCA-03.1_HANDOFF.md`，至少包括：

1. 任务范围与是否完成（A/B/C/D 各批次）；实际提交或工作区状态。
2. 新增及修改的文件列表、全部公开导出与准确签名。
3. Manifest/Loader 模块缓存、版本与能力检查、管理状态机和错误类型的最终选择。
4. RuntimeController/BrowserFreshness 组合步骤、真正的 Provider/Session/Store/Bus owner、输入新鲜度和取消/恢复语义。
5. 测试命令、Python/操作系统版本、通过/失败/跳过数字、mypy/Ruff/构建输出、模拟案例覆盖范围。
6. 仍需 BCA-03.2 验证的真实浏览器闭环、故障注入、资源清理与性能项目。
7. 对 BCA-04/05/06 的接入说明、任何公共协议变更提案与未决问题。

## 8. Codex 最终回复格式

完成实现后按如下顺序汇报：

1. **执行状态：** A/B/C/D 完成情况；仓库 commit/branch/工作区状态。
2. **主要代码与 API：** 新增/修改文件、稳定导出、关键决策。
3. **实测结果：** 逐条命令及结果，注明测试是否模拟/是否需要浏览器。
4. **异常与资源验证：** 失败/取消/重复关闭以及新鲜度授权的可复现证据。
5. **交付文件：** 指出 `docs/BCA-03.1_HANDOFF.md`。
6. **遗留事项：** 03.2 的真实集成清单及需主架构协调的公共契约调整。

**本次只执行 BCA-03.1 的实际开发与模拟集成验收；完成后以交接报告作为进入 BCA-03.2 设计与实施的依据。**
