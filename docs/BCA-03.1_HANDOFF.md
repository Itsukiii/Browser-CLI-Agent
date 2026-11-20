# BCA-03.1 / Plugin Core 与 Runtime 接入交接

日期：2026-11-18。A/B/C/D 四批已完成，停在 **03.1 交付审查**，未进入 03.2。基线为 main / `550cdfa0b042e4cee95f0d7f53e88a7d84d62c43`（BCA-02）。本轮未 commit/push；Protocol 2 和包版本 0.2.0 不变。

## 本轮范围与文件

| 批次 | 实施内容 | 定向验证 |
| --- | --- | --- |
| A | 静态 Manifest/Catalog、重复 ID 拒选、路径边界、隔离包 Loader/缓存/回滚、example 工厂 | 初次 A 专项连同旧 example 测试 18 passed |
| B | 契约与能力校验、单插件 Manager、生命周期/取消/共享终止、返回值边界 | 初次生命周期专项 12 passed |
| C | 只读 Provider View、借用截图适配器、Host 命令暂停与原引用、一次性关闭 | A/B/C 累计模拟专项 37 passed |
| D | 额外边界/竞争回归、无浏览器示例、Browser 装配配方、规范与交接 | 最终 plugins + 旧 example 专项 58 passed |

新增 `src/bca/core/plugins/{contracts,models,errors,catalog,loader,validation,manager,lookup,capture_adapter,host}.py`。原四项 Plugin 契约从 __init__.py 移到 contracts.py，继续原路径导出；AST 与基线完全相同，SDK 的四项重导出未修改。__init__.py 统一导出新增类型。其余 Protocol/Provider/Runtime/Browser 实现不改动。

新增 `plugins/example/plugin.toml`，原 ExamplePlugin 保留，仅增加 create_plugin 工厂。新增 `examples/plugin_runtime.py`、`examples/plugin_browser.py` 和 `tests/core/plugins/{test_catalog_loader,test_manager,test_host}.py`（共 57 项新测试）。更新 README、PLUGIN_SPEC、INTERFACES、ARCHITECTURE、RUNTIME、DEVELOPMENT_PLAN。

保留用户原有 `docs/md/BCA_PROJECT_CONTEXT.md` 修改与 BCA-03_Plugin_System.md。03.1 原任务文档仅由 Ruff 对 Python 代码块补空行，任务内容未改。未删除旧产物，所有测试日志/临时目录仍在 `.test-artifacts/`。

## 实际公开 API

原导出保持：Plugin、PluginMetadata、PluginConfig、PluginContext。新增公开导出：

- PluginCatalog、PluginLoader、PluginManager、ProviderLookupView、FreshnessCaptureAdapter、PluginRuntimeHost。
- PluginDescriptor、PluginDiscoveryIssue、CatalogSnapshot、PluginLifecycleState、PluginSnapshot。
- PluginManifestError、PluginDuplicateIdError、PluginLoadError、PluginCompatibilityError、PluginContractError。

```text
PluginDescriptor(*, plugin_id: str, version: str, protocol_version: int,
                 required_capabilities: tuple[str,...], directory: Path,
                 factory: str="create_plugin")
PluginDiscoveryIssue(*, source: Path, error_type: str, message: str, plugin_id: str|None=None)
CatalogSnapshot(*, candidates: tuple[PluginDescriptor,...]=(),
                issues: tuple[PluginDiscoveryIssue,...]=())
PluginSnapshot(*, plugin_id: str|None, version: str|None, state: PluginLifecycleState,
               required_capabilities: tuple[str,...]=(), last_error: str|None=None,
               cleanup_status: str="not_started", cleanup_error: str|None=None)
PluginCatalog(roots: Sequence[Path])
    discover() -> CatalogSnapshot
    get(plugin_id: str) -> PluginDescriptor
PluginLoader()
    load(descriptor: PluginDescriptor) -> Plugin
PluginManager(catalog: PluginCatalog, *, providers: ProviderLookup, states: StateSink,
              events: EventSink, logger: Logger, loader: PluginLoader|None=None)
    load(plugin_id: str, *, config: PluginConfig|None=None) -> None
    async initialize/start/stop/close() -> None
    async observe() -> PageState
    parse_command(text: str, *, source: str="cli") -> Command
    async handle_command(command: Command) -> tuple[Action,...]
    format_state(state: PageState) -> str
    snapshot() -> PluginSnapshot
ProviderLookupView(base: ProviderLookup, *, overrides: Mapping[str,Provider]|None=None)
    get(capability: str) -> Provider
    get(capability: type[P]) -> P
    available(capability: str|type[Provider]) -> bool
FreshnessCaptureAdapter(session: BrowserSession, raw_capture: CaptureProvider,
                        policy: BrowserFreshness)
    available: bool
    async start/close() -> None
    async capture(page_id: str) -> Frame
PluginRuntimeHost(manager: PluginManager, controller: RuntimeController, states: StateStore)
    async start/close() -> None
    async execute_text(text: str, *, source: str="cli") -> BatchResult
    snapshot() -> StateSnapshot|None
    format_current_state() -> str|None
```

模型为 frozen kw-only 本地 dataclass，不进入 Protocol codec。Manager 的可选 config 是草案的兼容细化；省略时独立构造默认对象。Browser 示例 `assemble(session, raw_capture, inputs, states, events, policy, roots)` 返回 `(PluginRuntimeHost, FreshnessCaptureAdapter)`，Host 未启动、adapter 已启动，调用方拥有返回对象的关闭责任。

## 发现、装载与版本边界

Catalog 仅扫描显式根的直属目录、稳定排序、读取 TOML，__pycache__ 不作为候选。非目录子项忽略；根非目录/不存在、读取失败、入口缺失、非法字段、路径逃逸均形成安全 issue，不阻断其他候选。重复 plugin_id 的每个来源均报 PluginDuplicateIdError，不选赢家；get 只查询最近成功 discover 的候选集合。

协议要求精确 int 2（不接受 bool），Manifest 与实例 metadata 的 ID/version/protocol/capabilities 逐项一致。version 是插件自己的标识，schema_version 是 PageState 业务 schema，均不替代协议版本。实例必须具备规定方法的 async/sync 形式与签名形状；Manager 每次调用继续验证返回值。

Loader 使用规范化路径摘要命名的独立顶层包，设置包搜索目录支持相对导入，不改 cwd/sys.path。同路径成功模块缓存于 sys.modules，每次调用工厂创建实例；失败导入回滚本次新增的该命名空间及子模块。工厂异常以 PluginLoadError 保留 cause，方法契约/metadata 错误分别归 Contract/CompatibilityError。工厂成功导入后的失败不会清掉模块缓存，无热重载支持。

插件为可信本机 Python。目录/Manifest 约束是来源一致性边界，不是安全沙箱；Python 模块仍可导入其他代码。工厂应无资源副作用并返回新实例，资源在 initialize 分配；未返回实例的工厂副作用、恶意单例工厂或私自修改 sys.modules 不在隔离保证范围内。源码内没有插件下载/安装机制，业务插件目录不随 bca wheel 自动发布。

## 生命周期、异常与资源

Manager 的状态表详见 PLUGIN_SPEC。主要路径 CREATED→LOADED→INITIALIZING→INITIALIZED→STARTING→RUNNING，stop 经 STOPPING 到 STOPPED，允许再次 start；close 经 CLOSING 到 CLOSED，终态不可重启。initialize 真正执行一次；重复已完成 initialize、RUNNING start、stop/close 均按规范幂等。FAILED 不能继续使用，必须收尾并重建实例。

生命周期与 observe/handle 共用一个操作锁，插件异步调用用受跟踪任务；终止先改变接纳状态再取消一次并 await 在途回调，避免二次取消打断 finally。共享 stop/close 任务受 shield 保护，取消某个等待者不终止清理。initialize/start 失败或取消会等待一次 close；cleanup 错误单独保存，不覆盖主异常。正常 close 的回调错误归档而不重抛，CLOSED + cleanup_status=failed 明确表示清理不成功；stop 失败仍可抛原错误，Host 保证 finally close。

observe 只能返回本插件 PageState；parse 返回 Command；handle 返回 tuple[Action,...]；format 返回 str；生命周期返回 None。非法嵌套 coroutine 返回值关闭后报 ContractError，避免未等待警告。Manager 自身不 publish/execute。last_error/cleanup_error 仅存类别，不存用户命令、图像或原始异常内容；异常链保留开发定位能力，调用方不要将任意异常文本直接写日志。

能力在 initialize 前通过实际注入 View 校验。capture/input 使用 ABC 类型查询，保留未注册/类型错/未就绪三种已有类别并关联 plugin_id；View 的名称/类型查询返回同对象，类型与 availability 检查与 Registry 一致。View 不启动/关闭 Provider，adapter 启停仅改变自身状态。

## Host 与来源授权

装配顺序为 Session/raw Capture/Input ready → Store/Bus/BrowserFreshness → FreshnessCaptureAdapter.start → View overrides → Manager.load → RuntimeController(manager.observe, 同一个 Input/Store/policy) → Host.start。真实策略的 Input 建议来自 policy.create_input_provider，保留既有新目标恢复资格。

adapter.capture 校验 page_id 和当前绑定、readiness 后只调用 policy.capture(raw_capture)，不变更返回 Frame。Mock CDP 测试证明首次有效观察仅一次 screenshot/一次 Store 版本提交且 source_frame_id 存在；未记录来源的状态不会产生可信引用。嵌套 adapter 拒绝，避免递归。

Host 用命令锁串行；原本 RUNNING 时 pause 并等待观察完成，同步成对读取 snapshot/ref，检查版本和插件归属，再 parse/handle/submit。动作生成时保存的原 ref 不替换，外部更新 Store 会令批次 STALE，不重放。原来 PAUSED 则保留上层暂停意图。异常/取消 finally 只恢复 Host 自己暂停的观察，关闭期间不恢复 STOPPING/STOPPED Controller。

close 先禁止新命令，Controller.stop 取消并等待实际输入；随后取消并 await 尚在动作生成的命令/启动流程；最后 Manager.stop/close。Host 拥有 Manager/Controller，不拥有 Session、raw Capture/Input、Store/Bus，也不隐式拥有传入的 adapter。Application 依次 host.close → adapter.close → Input.close → raw Capture.close → Session.close → Store/Bus.close。返回 BatchResult 原义不变，动作取消不代表撤销；不可用/未知输入仍由 Runtime 阻断。

Manager/Host 不为忽略取消的插件提供强制杀死能力；插件自建任务归插件 close。插件回调不能 await 自身 Manager/Host 调度链或直接回调 Controller/Input，外部命令只经 Host。Host 构造的对象一致性是组合入口前置条件，示例明示该装配；未为验证注入身份破坏现有 Runtime 公共 API。

## 本轮实测

平台 Windows / PowerShell，Python **3.14.7**，pytest 9.2.0。未安装新依赖，现有 venv 已满足配置；未启动 Edge，未连接日常或测试 CDP 端口。测试中 InputPeer 为同进程回环 HTTP/WebSocket **模拟 CDP**，真实 BrowserSession/Capture/Input/BrowserFreshness 代码连接该替身；这不是实际 Edge 验收。

| 命令 | 实际结果 |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest tests/core/plugins tests/plugin_sdk/test_example.py -q -W error --basetemp=.test-artifacts/pytest-03.1-plugins` | **58 passed，0.56s**（57 新 + 1 旧 example） |
| `Remove-Item Env:BCA_CDP_ENDPOINT -ErrorAction SilentlyContinue` 后 `.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-artifacts/pytest-03.1-full` | **495 passed / 12 skipped，12.41s** |
| `.venv\Scripts\python.exe -m mypy` | **63 source files，无问题** |
| `.venv\Scripts\python.exe -m ruff check .` | All checks passed |
| `.venv\Scripts\python.exe -m ruff format --check .` | 通过，新增交接文件后再复核 |
| `.venv\Scripts\python.exe -m build` | 0.2.0 sdist/wheel 成功 |
| `.venv\Scripts\python.exe examples/plugin_runtime.py` | simulated、candidates=1、status=succeeded、version=1，返回真实生成的 request_id/action_id 及 example 格式化字符串 |
| 原契约 AST 对照 | contracts.py 与 HEAD 原 plugins/__init__.py 定义 AST 完全一致 |

12 项跳过全部为已有显式真机 opt-in：Browser 4、Runtime 8；本轮新测试无跳过。没有使用 02.4 的 450 真机结果充作本轮测试。Python 3.12/3.13 实机矩阵未验证，mypy/语法配置维持 3.12+。

日志为 `.test-artifacts/03.1-plugins.log`、`03.1-full.log`、`03.1-build.log`，定向临时目录为 pytest-03.1-A/B/C/D/plugins/full。

测试覆盖：多候选静态扫描、冲突拒选、字段/协议/缺失/读取失败、解析后路径逃逸、独立同名相对导入包、缓存新实例、导入回滚、工厂/实例/metadata/签名错误；能力三种分类；默认 Config 隔离；重复启停重启；初始化/启动/停止/关闭失败和取消；多关闭等待者；observe/handle 清理等待；每类返回契约及嵌套 coroutine；Frame 来源和单次提交；原引用过期；原暂停保留；并发命令顺序；取消排队/暂停/生成/执行；FAILED/不确定阻断/Provider CANCELLED 结果；空批次；借用资源不关闭、连接 pending/reader 清理和无残留任务。Windows 符号链接逃逸通过对 Path.resolve 的确定注入验证解析边界，未冒充真实 symlink 权限环境测试。

## 工作区与后续接入

本轮修改 tracked 文件为 README、ARCHITECTURE、DEVELOPMENT_PLAN、INTERFACES、PLUGIN_SPEC、RUNTIME、example/__init__、core/plugins/__init__；新增模块/测试/示例/Manifest/交接均未提交。PROJECT_CONTEXT 为用户已有修改，本轮未改。普通 git diff 不含 untracked，不能作为新增规模。`git diff --check` 仅报告用户 PROJECT_CONTEXT 第 6/7 行既有 Markdown 尾空格；排除该文件后通过。

03.2 应运行真实 Host→Plugin→BrowserFreshness 闭环、实际 CDP 响应丢失/断连、在途 Capture/Input/插件取消、关闭与资源残留、DPR/区域坐标和持续性能；还应验证实际部署插件目录、Windows symlink/权限、启动失败后资源清理。工厂模块缓存不热重载、Python 无沙箱、协作取消限制仍保留。

04 SDK 继续复用原四项 Plugin 契约，识别与资源工具不得自行发布或输入；05 CLI 主要调用 host.execute_text，使用调用方总超时，按 BatchResult 及快照诊断，不能换 ref 重试旧动作；06 业务插件负责 schema/识别置信度/命令语义，使用 Frame.pixel_to_css，无真实雀魂业务验证。Browser Provider 替换恢复时建议 Application 重建一致的 View/Manager/Host 组合，本阶段没有 Host 热恢复/热换插件接口。

没有实施或提出阻塞本阶段的稳定协议变更。需要同目标恢复证明、DOM-only 来源授权、跨进程沙箱或热重载时，另行交架构主会话协调。本交接只作为进入 03.2 设计与实施的依据。
