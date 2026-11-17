# BCA 公共接口基线 0.2.0 / Protocol 2

方案 A：标准库 Python 类型契约优先。运行时依赖为空；进程内直接传递对象，外部表示通过显式 codec 转换。所有模型为 `@dataclass(frozen=True, kw_only=True)`，只接受关键字参数；不自动把字符串转换成枚举、时间或数字。包版本 `bca.__version__="0.2.0"`，协议常量 `bca.core.protocol.PROTOCOL_VERSION=2`。

## 导入入口与共同规则

下表模型、枚举、类型别名和 codec 均由 `bca.core.protocol` 集中导出。`Model(*, protocol_version: int = 2)` 是公共基类；每个子模型继承此字段并拒绝其他值（包括 bool）。构造时缺失必填参数或未知关键字抛 Python TypeError；字段值或跨字段约束不合法抛 `bca.core.errors.ValidationError`（同时属于 BCAError 和 ValueError）。

`JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]`；`JsonObject = dict[str, JsonValue]`。禁止 bytes、集合、元组、自定义对象、非字符串键、非有限浮点和循环引用。Core 仅验证表示可交换，不解释业务 schema。

所有 ID/来源/名称/版本标识为非空无空白 str。Action.key 是例外：非空 str，允许空格键 `" "`。帧、事件、动作和请求 ID 默认生成 UUID4 文本，调用方也可显式提供，但须自行保证跨会话唯一性；模型只检查格式，不维护去重表。page_id/session_id 由 Browser 提供；plugin_id 由插件声明且由 Plugin Manager 保证注册唯一；action_id 必须由结果原样回填。

所有时间字段为带时区 datetime，默认 UTC 当前时间，JSON 输出 ISO 8601 微秒精度；输入其他明确时区时保留时区和实际时刻，拒绝朴素 datetime、数字时间戳和构造器中的时间字符串。系统时钟精度可能低于微秒。排序依据 Runtime 序号和状态 sequence，不依据墙上时间；延迟/超时使用 `time.monotonic()` 或 `perf_counter()`，不得混用 UTC 时间作单调计时。结果 finished_at 不早于 started_at；Provider 如遇墙上时钟回拨应钳制记录的完成时间，同时用单调时钟计量真实耗时。

## 模型签名与字段

表中未列默认值的字段为必填，所有模型另含 protocol_version。

| 类型 | 字段、类型、默认及校验 |
| --- | --- |
| `Viewport` | `width: float, height: float, capture_width: float, capture_height: float`：正有限 CSS 尺寸；`device_scale_factor: float=1.0` 正有限；`scroll_x/scroll_y: float=0.0` 有限、可负；`capture_x/capture_y: float=0.0` 非负，截图范围不得超出视口。数字字段接受 int/float，拒绝 bool 和数字字符串 |
| `Frame` | `width: int, height: int` 严格正整数截图像素；`data: bytes` 编码截图；`format: ImageFormat`；`viewport: Viewport`；`page_id: str`；`frame_id: str=UUID4`；`captured_at: datetime=UTC now`；`session_id: str|None=None` |
| `ErrorDetail` | `code: str` 无空白错误标识；`message: str` 可空说明；`retryable: bool=False` 严格布尔；`details: JsonObject={}` 每实例独立 |
| `PageState` | `plugin_id: str`；`sequence: int` 非负严格整数；`schema_version: str="1"` 插件数据结构版本；`source_frame_id: str|None=None`；`generated_at: datetime=UTC now`；`data: JsonObject={}`；`recognition_status: RecognitionStatus=OK`；`diagnostics: tuple[ErrorDetail,...]=()` |
| `Command` | `name: str`；`arguments: JsonObject={}`；`request_id: str=UUID4`；`source: str="cli"`。已规范化输入，页面命令语义由插件检查 |
| `Action` | `page_id: str` 必填目标；`type: ActionType`；`action_id: str=UUID4`；`request_id: str|None=None`；`coordinate_space: CoordinateSpace=VIEWPORT_CSS`；`x/y: float|None=None` 非负有限；`button: MouseButton|None=None`；`key/text: str|None=None`，类型相关要求见下表 |
| `ActionResult` | `action_id: str`；`status: ActionStatus`；`started_at/finished_at: datetime`；`error: ErrorDetail|None=None`。成功禁止 error，失败或取消必须有 error；完成时间不得早于开始 |
| `Event` | `type: str` 扩展事件名称；`source: str`；`event_id: str=UUID4`；`timestamp: datetime=UTC now`；`request_id: str|None=None`；`data: JsonObject={}` |

枚举与值：

- ImageFormat：PNG=`png`、JPEG=`jpeg`。
- CoordinateSpace：VIEWPORT_CSS=`viewport_css`。其他空间目前拒绝，未来扩展必须显式声明转换。
- RecognitionStatus：OK=`ok`、PARTIAL=`partial`、UNKNOWN=`unknown`、ERROR=`error`。
- MouseButton：LEFT=`left`、MIDDLE=`middle`、RIGHT=`right`。
- ActionStatus：SUCCEEDED=`succeeded`、FAILED=`failed`、CANCELLED=`cancelled`。
- ActionType：MOUSE_CLICK、MOUSE_MOVE、MOUSE_DOWN、MOUSE_UP、KEY_DOWN、KEY_UP、TEXT_INPUT，值为对应小写下划线名称。

Event 不使用封闭枚举，建议 `namespace.event`，如 `runtime.started`、`browser.disconnected`、`plugin.state_updated`、`input.completed`；新事件无需修改模型，订阅者自行选择处理或忽略未知名称。

## Frame 编码、生命周期与坐标

Frame 仅接受编码 PNG/JPEG bytes。PNG 检查八字节签名，JPEG 检查 FF D8 FF 前缀；这只是格式基本检查，不保证图像完整、可解码或声明尺寸正确。解码、实际尺寸和图像完整性由 Browser/视觉层负责，Protocol 不引入图像库。RGB/RGBA 原始矩阵放在视觉层，不能再作为 Frame 传入。

Frame 保留原 bytes 引用，不进行拷贝；对象存活时 bytes 有效，使用者可以跨 await 持有 Frame。禁止复用可变 bytearray/memoryview 或原位修改缓冲。所有模型仅外壳冻结，JsonObject 内部引用保持浅层共享，构造器不深拷贝；交付/发布后生产者及消费者都不得修改载荷或其原始引用。需要修改时复制并构造新状态。默认 dict 使用 default_factory，实例间不共享。

width/height 是截图实际像素；Viewport 的全部空间字段是 CSS 像素。鼠标坐标原点为可见视口左上角，x 向右、y 向下。`Frame.pixel_to_css(x: float, y: float) -> tuple[float,float]` 要求截图点在 `[0,width) × [0,height)`，使用：

```text
css_x = capture_x + x * capture_width / frame.width
css_y = capture_y + y * capture_height / frame.height
```

两个轴独立缩放，兼容非等比截图；capture_x/y 加入裁剪偏移。Browser 必须提供截图时、当前浏览器缩放下的 CSS 截图范围；device_scale_factor 为诊断元信息，不再额外乘除。scroll_x/y 是文档滚动偏移，鼠标视口坐标不加该偏移。模型不接受桌面坐标；视口调整、滚动、页面切换后的动作新鲜度由后续 Runtime/Browser 检查。

## 动作与取消

| 动作 | 必须且仅允许的参数 |
| --- | --- |
| mouse_click | x、y、button |
| mouse_move | x、y |
| mouse_down / mouse_up | x、y、button |
| key_down / key_up | key，非空逻辑键名，例如 Enter、Shift、a、空格 |
| text_input | text，允许空串空操作，不隐含回车 |

InputProvider 在执行时验证 `x < 当前视口宽度`、`y < 当前视口高度`。click 表示一次按下及释放；down/up 为显式输入状态。逻辑键由适配器转换，基础模型不绑定 CDP。

对依次 await 的 execute，Provider 必须按调用顺序执行；并发调用的调度由调用方负责。插件返回 tuple 顺序为动作执行顺序；Core 同页串行，首个失败/取消后停止，未执行项不伪造结果。部分执行失败以 FAILED/ErrorDetail 表达，details 可记录已完成步骤和输入状态，不能宣称回滚。协程取消传播 asyncio.CancelledError，可能已有浏览器副作用；Core 如向上层汇报则记录 CANCELLED/错误详情。输入释放及重连由 BCA-01/02 负责，不自动重放动作。

## 显式序列化

`to_dict(model: Model, *, include_frame_data: bool=False) -> JsonObject`、`to_json(model: Model, *, include_frame_data: bool=False) -> str`；`from_dict[M: Model](model_type: type[M], data: JsonObject) -> M`、`from_json[M: Model](model_type: type[M], text: str) -> M`。

轻量模型转为纯 JSON 数据：枚举值字符串、带时区 ISO 时间、tuple 为数组；反向按指定模型类型恢复。不动态导入外部声明的类。输入必须携带 protocol_version（包括嵌套模型），拒绝未知字段、不支持版本、重复 JSON 键和非有限值。codec 错误统一 SerializationError。构造器仍使用原生类型。

Frame 默认输出元数据，完全省略 data；该字典不能直接重建 Frame，禁止当作完整帧。确需持久化完整帧时显式 `include_frame_data=True`，使用 URL-safe Base64（约增加 1/3 体积并产生编码副本）。解码器严格检查 Base64。codec 复制 JSON 容器，与原载荷脱离；它不序列化 Logger、PluginContext、Provider 或插件实例。禁止直接使用 dataclasses.asdict 当作 JSON 协议，它不处理枚举/时间及帧边界。

```python
from bca.core.protocol import Action, ActionType, MouseButton, from_json, to_json

action = Action(page_id="demo", type=ActionType.MOUSE_CLICK, x=120, y=80, button=MouseButton.LEFT)
assert from_json(Action, to_json(action)) == action
# metadata = to_dict(frame)  # 无图像 bytes
# restored = from_json(Frame, to_json(frame, include_frame_data=True))
```

## Provider 与 Runtime 端口

02.4 未改变本节公共签名或 Protocol 2。Runtime 正式跨模块约束见 [BCA-02_MAIN_SYNC.md](BCA-02_MAIN_SYNC.md)：观察/输入回调不得 await 自身 Controller 的 submit/recover/pause/resume/stop，此类调用明确抛 LifecycleError；BrowserFreshness 仅记录已验证帧 ID，弱引用 Provider 来源，不拥有完整帧或 Provider 生命周期。真实区域截图通过组合层适配 BrowserCaptureProvider.capture_region，未扩展 CaptureProvider ABC。

02.3 新增 Runtime 本地类型 `ActionBatch`、`ActionObservationRef`、`BatchResult`、`BatchStatus`、`ActionStats`、`ActionChannelState`、`ActionContextPolicy`、`ActionPipeline`、`BrowserFreshness`、`RuntimeContext`、`RuntimeController`、`RuntimeSnapshot`，均从 `bca.core.runtime` 导出。这些类型不进入 Protocol 2 codec。Provider/Plugin 公共签名、包版本和协议版本不变。ObservationPipeline 兼容增加仅关键字同步 `on_commit(token, snapshot)`：仅在成功 publish 且核对快照后调用，不在提交与钩子间 await。精确构造及恢复调用见 [RUNTIME.md](RUNTIME.md) 和 [02.3 交接](BCA-02.3_HANDOFF.md)。

入口 `bca.core.providers`：

- `Provider` ABC：`capability: ClassVar[str]`、只读 `available: bool`；`async start() -> None`、`async close() -> None`。start 就绪时幂等；close 在未开始、部分初始化失败及已关闭时幂等。Core 创建并拥有实例；重连可创建新实例。
- `CaptureProvider(Provider)`：capability=`capture`；`async capture(page_id: str) -> Frame`，仅启动后调用；失败抛 ProviderError，不返回空帧。
- `InputProvider(Provider)`：capability=`input`；`async execute(action: Action) -> ActionResult`。参数非法抛 ValidationError；不可用抛 CapabilityUnavailableError；接口执行异常抛 ProviderError；已接收动作的可预期失败返回 FAILED。
- `ProviderLookup(Protocol)`：`get(capability: str) -> Provider` / `get(capability: type[P]) -> P`，`available(capability: str|type[Provider]) -> bool`。供插件注入，只提供查询。
- `ProviderRegistry()`：实现 ProviderLookup；另有 `register(provider: Provider) -> None`、只读 `capabilities: tuple[str,...]`。注册不启动或关闭实例、拒绝重复和非法能力名。类型查询检查实例类型与可用性；名称查询不能获得静态的 capture/execute 方法，需类型化查询。capabilities 含未就绪项。available 是瞬时快照，不保证下一次 I/O 成功；非法查询参数仍抛 ValidationError。

Registry 无跨线程同步，约定单 asyncio 事件循环。新 DOM 能力继承 Provider 并使用独立名称，不修改 Registry 分支。抽象类型用于查询 token，不实例化；mypy 的 type-abstract 提示可在这类查找处局部注明忽略。

入口 `bca.core.runtime`：`StateSink(Protocol).publish(state: PageState) -> None` 和 `EventSink(Protocol).emit(event: Event) -> None` 均 async；await 返回表示已接收并提供背压，异常原样传播，不保证持久化。BCA-02.1 已实现以下兼容这两个端口的结构化类型，无需改动 PluginContext：

| 入口 | 签名与语义 |
| --- | --- |
| `StateSnapshot` | `@dataclass(frozen=True, kw_only=True)`，`version: int` 正整数、`state: PageState`；内部快照封装，不是新增 Protocol 2 Model/codec 类型 |
| `StateStore()` | `async publish(state: PageState) -> None`；`snapshot() -> StateSnapshot | None`；`async wait_for_update(after_version: int) -> StateSnapshot | None`；`async close() -> None`；只读 version、closed |
| `EventBus()` | `subscribe(*, max_queue_size: int = 64) -> EventSubscription`；`async emit(event: Event) -> None`；`async close() -> None`；只读 closed |
| `EventSubscription` | 通过 bus.subscribe 创建；`async get() -> Event | None`、`async close() -> None`；只读 pending |
| `StateStoreClosedError` | LifecycleError 子类，code=`runtime.state_store_closed`；关闭后 publish |
| `EventBusClosedError` | LifecycleError 子类，code=`runtime.event_bus_closed`；关闭后 subscribe/emit，及关闭唤醒的待提交 emit |

组件仅供单 asyncio 事件循环使用，不支持跨线程共享。非法 PageState/Event、游标和容量抛 ValidationError；游标要求非负 int，容量要求正 int，拒绝 bool。先校验参数，再检查生命周期。没有 start/reopen；close 幂等，不创建后台任务。

StateStore 初始 version=0、snapshot=None，每次接纳状态版本加一（包括相同对象/内容），只保留最新快照；不修改 PageState.sequence 或 schema_version。wait_for_update 返回严格大于游标的最新快照，未来游标也可等待；关闭后若已有符合条件快照仍返回，否则 None。取消只影响该等待者。

EventBus 每订阅者一个有界 FIFO，满时等待。并发发布通过单独发布锁确定顺序；**提交时仍活跃的全部订阅者**都具备容量后，在无 await 临界区同时加入同一 Event 对象。等待期间新订阅者参与该次提交，退订者排除；不回放已提交历史事件。无订阅者也成功。提交前取消/外部 asyncio.timeout 不产生部分广播，提交完成后不撤销消息。

Subscription.close 注销并丢弃未读事件，解除背压、唤醒 get 返回 None；Bus.close 阻止新工作、唤醒待提交 emit 抛关闭异常，但允许订阅者排空已提交事件再返回 None。get 释放容量和退订会通知等待发布者；发布等待不阻塞消费/关闭。

快照和事件只冻结外壳，嵌套 dict/list 按只读共享，发布方提交后及读取方均不得修改，不进行深复制。StateStore 是最新状态权威来源，EventBus 只是通知；两者不构成事务，通知失败不回滚状态。关键运行控制应先直接执行再通知，不能等待事件队列腾空后才停用动作。后续观察管线需串行协调 publish 和本次版本关联，不可在并发 publish 后误把全局最新版本当作自己的提交版本。详见 [RUNTIME.md](RUNTIME.md)。

02.2 从 `bca.core.runtime` 增量导出 `Scheduler`、`SchedulerState`、`SchedulerStats`、`ObservationPipeline`、`ObservationStats`、`FreshnessPolicy`。Scheduler 接受无参 async operation，默认 interval=0.1，提供 start/request_immediate/pause/resume/stop/snapshot/state；固定周期跳过错过 tick，立即请求合并，暂停等待自然完成，stop 取消并等待。Pipeline 接受 observe、StateStore、可选 EventSink 及仅关键字 freshness/observation_timeout/event_timeout，提供 run_once/snapshot；同通道独占发布、至多一次状态提交和一次有界通知。完整签名、统计口径与错误边界见 [RUNTIME.md](RUNTIME.md#scheduler022)。

FreshnessPolicy.begin()->object、validate(token, state)->bool 均 async；None 不提供 Browser 新鲜度保证。公开 StateSink/EventSink 签名和导入路径不变，仅将定义移至内部 runtime/ports.py 后由包重导出以避免循环依赖。StateSnapshot 与新增统计不是 Protocol 2 Model；不改变 Plugin.observe、PluginContext 或既有 codec。

## Plugin 与上下文

入口 `bca.core.plugins`，也从 `bca.plugin_sdk.interfaces` 重导出：

- `PluginMetadata(*, plugin_id: str, version: str, required_capabilities: tuple[str,...]=(), protocol_version: int=2)`：验证 ID/版本/能力 token，拒绝重复能力。
- `PluginConfig(*, values: JsonObject={}, protocol_version: int=2)`：独立默认配置字典，插件负责业务语义。
- `PluginContext(providers: ProviderLookup, states: StateSink, events: EventSink, logger: logging.Logger, config: PluginConfig)`：冻结 dataclass，可位置或关键字构造，不做 JSON 序列化。
- `Plugin(Protocol)`：metadata 属性；`async initialize(context: PluginContext)`、`async start()`、`async observe() -> PageState`、`parse_command(text: str, *, source: str="cli") -> Command`、`async handle_command(command: Command) -> tuple[Action,...]`、`format_state(state: PageState) -> str`、`async stop()`、`async close()`，未注明返回值的生命周期方法返回 None。

标准状态路径：Runtime 调用 observe，插件主动选择 Provider 取数并返回状态，Runtime 发布一次；observe 不重复发布。Context 保留 StateSink 供运行编排，未来推送模式需另行定义，当前不支持混用。sequence 在插件实例内递增，schema_version 表示业务结构，不等同状态序号或协议版本。生命周期、初始化失败清理和可执行示例见 PLUGIN_SPEC.md 及插件测试。

## 错误分类与日志

入口 `bca.core.errors`，所有异常属于 BCAError，并有类属性 code：

| 类型 | code / 场景 |
| --- | --- |
| BCAError | bca.error，统一基类 |
| ValidationError | protocol.invalid，非法字段/参数，亦继承 ValueError |
| SerializationError | protocol.serialization，继承 ValidationError |
| CapabilityUnavailableError | provider.unavailable，已注册但未就绪/关闭 |
| CapabilityNotFoundError | provider.not_found，未注册；继承 CapabilityUnavailableError 以保留宽泛捕获兼容性 |
| CapabilityTypeError | provider.type_mismatch，能力名对应类型不符；继承 CapabilityUnavailableError |
| ProviderRegistrationError | provider.registration，重复/非法注册 |
| ProviderError | provider.failure，接口执行异常 |
| PluginError | plugin.failure，插件执行异常 |
| CommandError | command.invalid，继承 PluginError，命令语义非法 |
| LifecycleError | lifecycle.invalid，阶段调用错误 |

边界层按 code、str(exc) 转换为 ErrorDetail，不把异常实例放进 JSON。取消不转成一般异常。库 import 不配置 root logger；Application 显式调用 `bca.app.logging.configure_logging(level: str="INFO") -> None`。插件使用 context.logger。日志可带关联 ID，不输出图像字节和敏感输入文本。`configs/default.toml` 为示例，配置加载属于 BCA-05。

## 兼容策略

首次 0.1.0 / Protocol 1 基于 Pydantic，本轮批准的方案 A 是破坏性 Python API 调整，包提升到 0.2.0、公共信封版本到 2。移除 model_validate/model_dump 系列方法，改用原生构造器或显式 codec；移除 RGB8/RGBA8 Frame 格式；构造器不再自动转换字符串。旧 JSON 不自动迁移，尤其裸像素需图像层先编码；调用方需按已知类型显式迁移并重新验证，不能仅修改版本号。

兼容内部修复采用补丁版本；破坏性字段、类型、坐标、生命周期和编码边界变更需递增基线与协议版本并同步所有使用模块。codec 当前拒绝未知字段，新增可交换字段也不能假定旧读者兼容。插件 version、schema_version 和公共协议版本独立维护。没有加载器版本协商实现，不承诺跨版本运行。

## BCA-01 Browser 实现入口

Protocol 2 保持上述契约不变。`bca.core.browser` 已提供 CDPConnection、TargetManager、BrowserSession、BrowserTarget、CDPEvent、SessionState、BrowserCaptureProvider 和 BrowserInputProvider。实际签名、generation/目标身份、PNG 坐标及输入不确定状态见 [BROWSER.md](BROWSER.md)；正式跨模块接入及本轮 01.4 验收见 [BCA-01_MAIN_SYNC.md](BCA-01_MAIN_SYNC.md)。Registry 注册不启动 Provider，Session 连接由上层拥有，Input/Capture 只借用会话。
