# Runtime 状态、观察与动作编排（BCA-02.1～02.4）

正式跨模块入口、资源所有权和后续接入规则见 [BCA-02_MAIN_SYNC.md](BCA-02_MAIN_SYNC.md)。02.4 实际集成、故障注入与性能结果见 [交接报告](BCA-02.4_HANDOFF.md)；历史小节保留各阶段背景，以当前源码及正式交接为准。

03.1 已提供正式插件组合入口 PluginRuntimeHost：以 manager.observe 构造 Controller，通过 execute_text 串行生成命令、保存原观察引用并提交 ActionBatch；不改变 Runtime 公共行为。FreshnessCaptureAdapter 将插件 CaptureProvider 查询接到 policy.capture(raw_capture)。具体装配见 [PLUGIN_SPEC.md](PLUGIN_SPEC.md) 和 examples/plugin_browser.py；本阶段以模拟 CDP 验证，真实插件集成待 03.2。

当前实现 StateStore、EventBus、Scheduler 和 ObservationPipeline。StateSink/EventSink、Plugin.observe 及 Protocol 2 签名不变；Action Pipeline 和 Controller 尚未实现。包 0.2.0 / Protocol 2 保持不变，公开入口和签名见 [INTERFACES.md](INTERFACES.md#provider-与-runtime-端口)。

## State Store

一个 Store 对应一条观察通道，初始无快照、version=0。每次 publish(PageState) 成功提交形成新 StateSnapshot 并将 version 加一；相同状态也计数。不解释识别状态或业务数据，不与插件 sequence、schema_version 混用。插件重建后 sequence 可以重置，Store 游标继续递增。

snapshot() 无 I/O，返回当前冻结快照；旧快照仍可由消费者持有，Store 自己只引用最新一个。wait_for_update(after_version) 在当前版本严格更大时返回最新快照，否则异步等待；慢消费者跳过中间版本，未来游标等待被超过或关闭。Condition 将检查与注册等待协调，避免丢失唤醒；一个等待者取消不会取消其他等待者。

close 幂等，拒绝新 publish，唤醒所有等待者。已有满足游标条件的快照优先返回，否则 None。快照不是持久化对象或协议新模型，不自动支持 Protocol codec；需序列化 PageState 时使用既有 codec，Runtime 游标由上层显式组织。

## Event Bus

通过 subscribe(max_queue_size=64) 获取独立句柄，不直接构造 EventSubscription。每个句柄一个有界 FIFO；pending 是尚未消费的事件数。get 返回最早事件，空时等待。订阅从创建后成功提交的事件开始接收，无历史回放。

发布者通过 asyncio.Lock 串行协调，使用共享 Condition 等待所有活跃队列都有空间。等待容量时 Condition 释放锁，因此消费、退订、Bus.close 可以继续；发布锁只约束发布者。满足容量后无 await 地向所有目标队列追加同一 Event 对象，再通知等待者。不存在逐队列 await put 导致的半发布。并发调用的顺序以实际取得发布锁、成功提交的顺序为准，不依赖事件时间戳。

成员资格在提交时确定：等待期间新增订阅者会接收该事件，退订者不接收；例如 A 队列满而 B 空，E 等待，C 此时订阅，随后 A 退订，E 将同时提交给 B/C。subscribe 是单事件循环上的同步修改，不会插入无 await 的提交区间；新增空队列也不会把当前受阻的容量条件变成可提交，因此不需要额外唤醒任务。

可以用 asyncio.timeout 包住 emit，预算包括发布锁与容量等待。提交前的取消/超时不投递到任何队列；提交之后不能解释成回滚。没有额外工作线程或后台广播任务，也不自动重试。任一慢订阅者都会阻塞全局发布，应由其所有者按生命周期退订或由发布方施加预算。

- Subscription.close：注销、丢弃未读队列、解除背压，等待读取及后续 get 返回 None。
- Bus.close：阻止 subscribe/emit，唤醒受阻发布者抛 EventBusClosedError；保留句柄中的已提交队列供 FIFO 排空，空后 get 返回 None。总线释放订阅集合引用，消费者仍应结束自己的任务和句柄。
- 重复 close 无害；取消 get 只取消该次等待，不关闭句柄；多个 get 竞争同一句柄时，每条事件只被其中一个领取。

这些行为基于单个 asyncio 事件循环的协作调度，不承诺跨线程、跨进程同步或发生内存耗尽时的事务保障。

## 所有权、控制与组件协作

PageState/Event/StateSnapshot 是冻结外壳，data 等内部 dict/list 不深复制。提交后发布方（包括原载荷引用持有者）不再修改，读取方也按只读使用。状态最新快照是状态权威来源，事件通知不是持久日志或消费者完成确认。

关键控制直接执行，Event Bus 只通知。例如浏览器断开时，动作通道在发现 Provider/绑定不可用后先阻断输入、处理待执行请求，再尝试有限预算 emit。不要在通知队列满时延迟停止动作；StateStore/EventBus 本身不替调用方执行控制。

StateStore 和 EventBus 不构成跨组件事务；state publish 成功后即使 emit 失败，状态仍已更新。02.2 的 ObservationPipeline 将 observe→publish 作为单通道串行路径，只发布一次。事件版本在本通道独占发布责任下关联本次提交；不能在多个独立发布者并发后随意读取 store.version，否则可能关联到另一状态。现有 publish()->None 不变，不引入隐藏的返回值或新公共提交接口。

## 可执行示例与验证

```powershell
.\.venv\Scripts\python.exe examples/runtime_basics.py
.\.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.1
```

示例发布一个 PageState、等待最新快照，并让两个订阅者收到同一个 Event，最后关闭两个独立组件。它只演示 02.1 基础设施，02.2 调度观察示例见下文。没有浏览器依赖。02.1 历史结果与 Git 基线见 [BCA-02.1_HANDOFF.md](BCA-02.1_HANDOFF.md)。

## Scheduler（02.2）

公开入口均从 bca.core.runtime 导入。`Scheduler(operation: Callable[[], Awaitable[None]], *, interval: float = 0.1)`，interval 接受正有限数，拒绝 bool、0、负数、NaN/inf。operation 应响应协程取消。

| 接口 | 行为 |
| --- | --- |
| async start() -> None | CREATED 启动唯一调度任务并尽快执行首轮；RUNNING 幂等；PAUSED 要求使用 resume；终止后抛 LifecycleError |
| request_immediate() -> None | 同步设置一位 pending；CREATED 合并进首轮，PAUSED 保留，RUNNING 唤醒；STOPPING/STOPPED 抛 LifecycleError |
| async pause() -> None | 先关闭新观察入口，再等待已运行操作自然结束；返回时无在途观察；重复调用幂等；CREATED 抛 LifecycleError |
| async resume() -> None | PAUSED 恢复时立即一轮并重设周期锚点，保留请求与首轮合并；RUNNING 幂等；CREATED/终止后抛 LifecycleError |
| async stop() -> None | 不可逆终止；取消并 await 调度任务及其内联 operation；多调用者共享取消屏蔽的终止任务，幂等；CREATED 也可直接停止 |
| snapshot() -> SchedulerStats | 冻结的累计统计快照，无 I/O |
| state: SchedulerState | CREATED / RUNNING / PAUSED / STOPPING / STOPPED；PAUSED 也可能正在等待旧观察自然完成，须 await pause 才是完成屏障 |

start/resume 的单调时刻作为 epoch 锚点 t0，计划点为 t0+n×interval。每轮结束后跳过严格早于完成时刻的未执行 tick；恰好位于下一个点可立即执行，不跳过。仅对 tick 比值使用 1e-9 的浮点等值容差。短操作等待下个计划点，不使用“结束后再睡 interval”的累积漂移方式；长操作不连续补跑过期 tick。暂停时间不积压周期，恢复重设锚点。

周期到点与 pending 同时存在时，仅执行一轮，计入 periodic_runs 并清除 pending。观察中到来的多个立即请求合并为一个，完成后尽快再观察；若此时下个周期已到，仍只运行一轮。空闲立即请求触发额外一轮，不改变原周期锚点。每轮至少主动让出一次事件循环，避免快速回调连续请求造成无 await 忙循环。

pause/resume/start 通过生命周期锁协调；取消 pause 等待者不撤销 PAUSED 状态。resume 即使遇到被取消的 pause，也会先等待旧观察结束。stop 不等待此锁，优先进入 STOPPING、取消当前 operation；pause 会等待安全退出，排队的 resume 不能覆盖终止状态。取消一个 stop 调用者不取消实际终止任务，之后可再次 await stop。operation 不能 await 自己 Scheduler 的 start/pause/resume/stop，否则抛 LifecycleError 并停止，避免自等待死锁；它可以 request_immediate。

普通 callback 异常记录类别后继续下一计划点；LifecycleError（含 StateStoreClosedError）视为 fatal，停止并保留 last_error。operation 的 CancelledError 不吞成成功，结束调度任务；stop 内部消费其任务取消结果完成资源收尾。调度循环自身故障也停止，不遗留额外操作任务。stop 的完成时限依赖被调用协程响应取消；无法强杀忽略取消的插件，不承诺此类协程有固定停止上限。

## ObservationPipeline（02.2）

```python
ObservationPipeline(
    observe,
    states,
    events=None,
    freshness=None,
    observation_timeout=10.0,
    event_timeout=0.05,
)
```

`observe: Callable[[], Awaitable[PageState]]`，`states: StateStore`，`events: EventSink | None`；后三个配置是仅关键字参数。提供 `async run_once() -> None`、`snapshot() -> ObservationStats`。正有限预算校验和错误配置抛 ValidationError。

`FreshnessPolicy` 为独立结构化策略接口：`async begin() -> object`，`async validate(token: object, state: PageState) -> bool`。02.2 未实现 Browser 策略；02.3 的 BrowserFreshness 见下文。freshness=None 仅跳过额外校验，**不保证导航、绑定或几何新鲜度**。

run_once 锁覆盖整轮观察和通知，即使外部同时调用也不会重入 observe。等待此锁不计入 attempt 和 observation_timeout；排队调用可由上层取消或设置总预算。持锁后执行 begin→observe→检查 PageState 类型→validate→publish 恰好一次。observation_timeout 覆盖上述路径，通知使用单独 event_timeout。UNKNOWN、PARTIAL、ERROR 等合法识别状态均可发布，Runtime 不按业务状态擅自丢弃。

本 Pipeline 是其 Store 的唯一发布者；插件不能在 observe 内重复发布，其他 Pipeline/写入者不能同时写该 Store。publish 前记录游标，成功返回后立即读取 snapshot，检查 state 对象身份以及 version=previous+1，再构造通知。该检查能发现可观察的版本配对异常，不能替代独占写入契约，也不是新的跨 Pipeline 事务。未改动 StateStore.publish()->None。

成功提交至多尝试一条 runtime.observation_completed（version、plugin_id、source_frame_id、observation_duration_ms）；stale 不提交，至多一条 runtime.observation_stale；普通异常/超时不提交，至多一条 runtime.observation_failed（安全 error_type、耗时）。不携带 PageState.data、异常消息或网页内容。每次通知均有独立预算，队列满、Bus 关闭或其他通知失败只更新诊断，不重试发布/通知，不回滚 Store。

普通观察错误/超时/stale 作为已处理的单轮结果返回 None，Scheduler 可继续下一周期；stale 不自行密集重试。LifecycleError 记录 failed 后直接传播，不等待诊断通知；例如 Store 关闭或版本配对失效会使 Scheduler 停止。CancelledError 记录后原样传播，包括提交后的通知取消；已提交状态仍存在。Publisher/Sink 和插件必须配合取消，asyncio.timeout 也无法强制停止吞掉取消的协程。

## 诊断计数口径

SchedulerStats 和 ObservationStats 均为 frozen、kw_only dataclass，本地诊断，不加入 Protocol codec。统计在对象生命周期内累加，pause/resume 不 reset；last_error 保留最近一次异常的**类型名字符串**，无异常消息。单调时钟统计持续时间，不使用 UTC。

- Scheduler.started：真正开始的 operation 数；completed：正常返回数（含 Pipeline 已处理的可恢复失败）；failed：callback 抛出的普通或 fatal 异常数；cancelled：运行中 callback 被取消数。等待周期时 stop 不算 cancelled。
- periodic_runs 包含 start/resume 的首轮和到点轮；immediate_runs 仅表示非到点的额外轮；两者之和为 started。skipped_ticks 统计每轮完成后错过的计划点；coalesced_requests 统计 pending 已为真时再次请求的次数。last_run_duration_ms 包含 operation 的通知/清理时间。
- Pipeline.attempts：取得运行锁后的轮数；published：publish 正常返回次数；stale：策略返回 False 次数；failed：观察类型错误/普通异常/超时/fatal 次数；timed_out 是 failed 的子集；cancelled：已取得锁的轮次取消数，排队取消不计入。
- event_emit_failed：尝试通知但异常、超时或取消次数；events=None 不计数。提交后取消会同时计 published 与 cancelled；提交后版本配对失败可同时计 published 与 failed，所以这些指标不是互斥分组。
- last_observe_duration_ms：本轮 begin→observe→validate 的时间（失败则到该阶段退出）；last_publish_duration_ms：publish 及配对检查时间；两者不含通知或排队时间。每次 attempt 重设这两个本轮数值，未到 publish 则为 0。

## 示例及 02.3 所有权交接

```powershell
.\.venv\Scripts\python.exe examples/runtime_observation.py
.\.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.2
```

模拟示例运行默认 100ms 周期、一次立即请求、pause/resume、读取最新状态和通知，最后 stop 并由外部关闭订阅、Bus、Store。不启动浏览器。

Scheduler/Pipeline 不 start/stop 插件，不关闭 Store/Bus/Provider/Session。02.3 Controller 先关闭接收入口、stop 并 await 本阶段任务，再由调用方按所有权清理外部组件。关键控制直接执行，通知是有界附属步骤；已提交状态不能因通知失败回滚。

## ActionPipeline 与 Controller（02.3）

所有类型均从 `bca.core.runtime` 导出，Runtime 本地模型为冻结 dataclass，不修改 Protocol 2 codec。完整可运行示例为 `examples/runtime_actions.py`（模拟）和 `examples/runtime_browser.py`（显式本机 CDP）。

```python
ActionPipeline(provider, context, events=None, *, capacity=32, gate=None,
               request_refresh=None, event_timeout=0.05)
RuntimeController(observe, provider, states, context, events=None, *,
                  interval=0.1, capacity=32, observation_timeout=10.0,
                  event_timeout=0.05)
```

Controller 创建并拥有两条工作路径和协调门；`observation`、`scheduler`、`actions` 用于读取诊断，上层生命周期应通过 Controller 调用，不能绕过协调门直接 run_once/execute。`start/pause/resume/submit/stop/recover` 为 async；`reference()` 返回最新可信观察引用或 None；`snapshot()` 为冻结 RuntimeSnapshot。其 state 使用既有 SchedulerState 五种枚举，action_state 独立使用 CREATED/READY/BLOCKED/STOPPING/STOPPED。pause 仅暂停观察并等待当前观察自然完成，动作仍可提交且必须通过新鲜度校验。阻断动作不停止观察。终止不可重启，重复 stop 幂等，共享停止任务不受某个等待者取消影响。

ActionBatch 字段：`actions: tuple[Action,...]`、`observation: ActionObservationRef|None=None`、`request_id: str|None=None`、自动 UUID `batch_id`。拒绝非 tuple、重复 action_id、混合 page_id、非法引用类型和空 ID。空批次为 SUCCEEDED 空操作，不调用 Input；非空批次缺少可信引用返回 STALE。ActionObservationRef 为 `version: int` 与隐藏 repr 的不透明 `token: object`，调用方应保存并传递原引用对象，复制字段不能获得授权。

BatchResult 保留实际返回的 `results: tuple[ActionResult,...]`，以及 batch_id/request_id、status、failed_index、error_type、queued_at/started_at/finished_at。status 为 SUCCEEDED/FAILED/STALE/CANCELLED/BLOCKED。异常不会伪造 ActionResult；返回 ID 错配会保留该实际结果、标记失败并阻断。SUCCEEDED 只表示输入确认，不表示网页业务完成。

### 队列、取消及停止

容量默认 32 个**待执行**批次，另有最多一个执行批次。成功 append 是接纳点，popleft 是出队/开始点；两处均在单事件循环的无 await 段内完成。容量等待由公平 admission Lock 排序，等待者不创建后台批次任务；成功接纳顺序即 FIFO。工作任务只为当前批次创建一个执行任务，整批不与其他批次交错。

调用方可以 `async with asyncio.timeout(total_seconds): await controller.submit(batch)` 覆盖容量、排队和执行总等待。入队前取消不占位；已入队取消立即移除并释放名额；执行中取消只发送一次 Task.cancel，并等待真实 Provider 清理和批次归档后再向调用方抛 CancelledError。重复取消或同时 stop 不会再次取消释放流程。TimeoutError 可能在清理完成后才返回，不能据此推断输入未发生。完成结果已归档与调用方取消竞争时，统计保留实际完成情况，调用方仍可能收到取消。

`stop` 先同步设置 STOPPING、终结排队请求并唤醒容量等待，再取消和 await 当前任务。已接纳但未执行的批次返回 CANCELLED，尚未接纳者抛 LifecycleError；stop 后无新执行。事件通知不在控制决策前，独立预算默认 50ms；已阻断/停止状态不等待慢订阅者才生效。Provider 必须配合取消并最终完成清理；Runtime 不强杀忽略取消的第三方协程。

首个失败停止本批剩余动作。已确认 FAILED 且 Provider 仍可用、无不确定状态、上下文仍有效时允许后续批次执行。TargetLost、断连、意外异常、错误结果 ID、不可用 Provider 或不确定输入会阻断通道并结束排队批次。执行中取消或执行部分动作后取消也保守阻断。STALE 请求同步 request_immediate，绝不自动重放旧批次；所有活动批次结束后均请求新观察，Scheduler 自行合并。通知包含 ID、类别、耗时，不含输入文本、键盘序列、CDP 内容或异常消息。BatchResult 中真实 Provider 错误仍按其契约保留，日志应只输出统计或安全 error_type。

### 已提交观察与 Browser 来源

`BrowserFreshness(session, states)` 通过公开 Session.send 读取 connection/page/session/generation、URL/timeOrigin、visual/layout 尺寸与滚动、scale/offset/zoom、DPR 和窗口尺寸。不导入内部 geometry，不做坐标变换。

observe 必须使用 `frame = await policy.capture(capture_provider)`，并返回 `PageState(source_frame_id=frame.frame_id, ...)`。适配器记录实际返回 Frame，检查 page/session 及观察前后指纹。外部 Provider 应与此 Session 属于同一组合器，不能绕过协调门并发截图、输入或更换绑定。插件自行重新截图或无法提供来源关联时，观察不获授权；本阶段对键盘动作也采用同样严格来源要求，不默许 DOM 观察代替图像关联。

ObservationPipeline 兼容新增同步 `on_commit: Callable[[object, StateSnapshot], None]|None`。顺序为 begin→observe→validate→publish→核对实际快照→commit。publish 后与 commit 间无 await，且 Controller 在整个路径持有协调门，因此状态版本与 token 配对在一个不可交错提交段中完成。钩子必须同步、轻量且不抛异常；不可自行再次发布。状态提交后通知失败不回滚引用。

动作获得同一协调门后，在每条输入前检查原引用对象、当前 Store 快照、来源帧、Browser 指纹和 page_id。版本更替、导航、滚动、视口或绑定变化返回 STALE；连接不可用则阻断。Frame.pixel_to_css 仍由识别/插件负责，Runtime 不重复乘 DPR 或加 scroll。此机制只防护可检测变化：DOM 可以在检查与输入之间改变，也可以在相同指纹下局部更新，不能视为网页事务或 DOM 版本跟踪。

### 显式恢复和所有权

不提供 reset_uncertain；仅重建 Provider 或重新绑定同一目标不会恢复。Browser 策略目前仅接受**新建目标**的保守恢复路径；同目标人工恢复尚无可靠证明接口。初始和替换 InputProvider 均用 `policy.create_input_provider()` 创建以记录绑定来源，由外部调用 start/close。如果初始 Provider 不是这个工厂创建，允许正常执行，但该策略无法证明旧目标身份，recover 拒绝。

外部 owner 在通道已 BLOCKED 且在途清理完成后执行：

```python
await controller.pause()
await old_input.close()
new_page = await policy.create_recovery_target()  # 显式创建 about:blank，调用方负责关闭
await session.unbind()
await session.bind(new_page)
# 如有需要，外部在此导航到业务页面，并等待页面准备完成。
new_input = policy.create_input_provider()
await new_input.start()
version = states.version
await controller.resume()
await states.wait_for_update(version)
await controller.pause()
reference = controller.reference()
assert reference is not None
await controller.recover(new_input, reference)
await controller.resume()
```

新目标与旧目标必须不同，目标必须由上述显式 API 创建，替换 Provider 必须绑定当前身份、可用且无不确定标记，观察必须是新目标的新提交。恢复凭据一次使用；旧队列已经结束，不会自动恢复。owner 不得在恢复验证之外向新目标发送输入，尤其不能先留下按键/鼠标按下状态。Runtime 不恢复旧业务页面操作副作用。

结束顺序由资源 owner 负责：Controller.stop → Plugin stop/close → Input.close → Capture.close → 自有目标关闭及 Session.unbind/close → Store/Bus.close。Controller 只停止自有工作任务，不关闭借用对象。调用方总超时应覆盖新观察等待；不要在 observe 或 Input.execute 中等待自身 Controller/ActionPipeline 的 stop 或 submit。

### 统计口径

ActionStats 的 accepted 为成功接纳数；executed 为出队数（含在协调门前取消）；completed 仅统计 SUCCEEDED；failed/stale/cancelled/blocked 为互斥终态数，因此其和等于已归档接纳数。pending 只统计等待队列。full_waits 为取得 admission Lock 时确实发现队列满的次数；尚在 admission Lock 外等待者不重复计数。first_error_stops 统计实际非成功 ActionResult 导致的首错停止；uncertain 统计进入不确定输入处理的批次。event_emit_failed 为有界通知失败次数。last_capacity_wait_ms 包含 admission Lock 等待，last_queue_wait_ms 截止出队，last_execution_ms 包含协调门和逐条检查/输入等待。耗时均为 loop.time，UTC 时间仅用于结果归档。last_error 只保存安全类别，不保存异常消息。观察/Scheduler 统计保持 02.2 原义。


## 03.2 ??????

`examples/plugin_integration.py` ? `tests/core/plugins/test_real_*` ????? Edge ???Plugin ? adapter ? policy.capture(raw) ? PageState ? ObservationPipeline ?? publish/commit ? Host ????? ? Input ? ???????????? Runtime API?Manager ????? Application ?? PluginSnapshot?Host.snapshot ???? StateSnapshot??????????????????? [BCA-03_MAIN_SYNC.md](BCA-03_MAIN_SYNC.md)???????????????? Host ???? BatchResult??????????????????
