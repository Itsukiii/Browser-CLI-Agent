# BCA-02 / Runtime 正式跨模块交接

2026-11-17，供架构主会话归档。整合本地实际完成的 BCA-02.1～02.4；当前停在 02.4 交付审查，未启动其他子系统。版本仍为 `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`。HEAD `19df477547c26a4131d96191a8bb8bdb8362a4ea` 仅为 Browser 历史提交，Runtime 仍在未提交工作区；不得仅检出该 HEAD 就认为取得本交接代码。

## 已交付范围及入口

所有公开 Runtime 类型从 `bca.core.runtime` 导入。内部模块只依赖 `.ports` 等实际定义，不反向依赖 Runtime 根导出，避免循环。主要构造签名如下（省略类型的参数仍以源码注解为准）：

```text
StateStore()
EventBus()
Scheduler(operation: Callable[[], Awaitable[None]], *, interval=0.1)
ObservationPipeline(observe, states: StateStore, events=None, *, freshness=None,
                    on_commit=None, observation_timeout=10.0, event_timeout=0.05)
ActionPipeline(provider: InputProvider, context: ActionContextPolicy, events=None, *,
               capacity=32, gate=None, request_refresh=None, event_timeout=0.05)
BrowserFreshness(session: BrowserSession, states: StateStore)
RuntimeController(observe, provider: InputProvider, states: StateStore,
                  context: RuntimeContext, events=None, *, interval=0.1, capacity=32,
                  observation_timeout=10.0, event_timeout=0.05)
```

公开模型/枚举：StateSnapshot、SchedulerState/Stats、ObservationStats、ActionObservationRef、ActionBatch、BatchResult、BatchStatus、ActionChannelState、ActionStats、RuntimeSnapshot。公开策略/端口：StateSink、EventSink、FreshnessPolicy、ActionContextPolicy、RuntimeContext。具体错误为 StateStoreClosedError/EventBusClosedError，继承既有 LifecycleError；不增改 Protocol 2 codec。

## 状态和事件

StateSink 保留 `async publish(state: PageState) -> None`。StateStore 的同步 snapshot() 返回最新 StateSnapshot 或 None，version 初始为 0，每次成功提交加 1；`async wait_for_update(after_version)` 返回大于游标的最新快照，不保证交付每个中间状态。close 唤醒等待者；若有大于游标的已提交状态，先返回它，否则 None。关闭后 publish 抛 StateStoreClosedError，重复 close 幂等。after_version 必须是非负整数，不能传 bool。

每个观察通道独占一个 StateStore 的发布责任。PageState.sequence 是插件业务序号，不等于 Runtime version。冻结模型内部 dict/list 不深复制，生产者和消费者在提交后必须按只读约定使用，不能改原始载荷引用。

EventSink 保留 `async emit(event: Event) -> None`。EventBus.subscribe(max_queue_size=64) 同步返回 EventSubscription；其 get/close 为 async，pending 同步读取。每个订阅者有界 FIFO，任一成员队列满时发布等待；先取得 publish lock，再在 condition 下等待所有成员容量，在无 await 段向提交时仍有效的全部成员追加同一个 Event。无历史回放，不会半广播；等待期间新增成员参与本次提交，退出成员不参与。

Subscription.close 丢弃该句柄未读数据并退订。Bus.close 拒绝新工作、解除阻塞，已交付到句柄的事件仍可排空，之后 get 返回 None。消费者自己拥有消费任务；慢消费者要及时退订或由发布者施加超时。Event 是通知，不是控制权威或消费完成确认；Store.publish 和 EventBus.emit 不是跨组件事务。

## Scheduler 与观察链

Scheduler 提供 async start/pause/resume/stop，sync request_immediate/snapshot，readonly state。默认 100ms 固定周期，错过 tick 跳过不补跑，立即请求布尔合并，同一 worker 内联 await operation，最多一个操作在途。pause 等待当前操作自然完成；取消 pause 等待者不让操作重入，resume 等待 idle 后重置周期基准。stop 先进入 STOPPING，再取消并 await worker，共享关闭任务 shield；终止后不可重启。

ObservationPipeline.run_once() 返回 None；观察串行、最多一次提交，顺序为 begin→observe→validate→publish→核对实际快照→同步 on_commit→有界通知。observation_timeout 覆盖 begin 至提交关联，锁等待不包含在该预算，event_timeout 独立。UNKNOWN/PARTIAL/ERROR 等合法识别状态保留，不由 Runtime 推断业务可操作性。freshness=None 不保护 Browser 新鲜度。

FreshnessPolicy 为 async begin()→object、validate(token, state)→bool。同步 on_commit(token, StateSnapshot) 仅在提交成功后调用；publish 后与钩子间没有 await。钩子须轻量、同步、不重新发布；通知失败不能回滚状态或重复提交。LifecycleError 使 Scheduler 停止，普通观察异常/超时记诊断后允许下一轮。

## 动作批次与并发

```text
ActionObservationRef(*, version: int, token: object)
ActionBatch(*, actions: tuple[Action,...], observation=None, request_id=None,
            batch_id=<automatic UUID>)
BatchResult(*, batch_id, request_id, status, results: tuple[ActionResult,...],
            queued_at, started_at, finished_at, failed_index=None, error_type=None)
```

批次拒绝重复 Action ID、混合 page_id 等非法参数；空元组为成功空操作。非空动作必须有可信引用，不能把自填版本/Frame ID 当授权；复制 ActionObservationRef 字段也不通过 Browser 策略的对象身份校验。这些引用是本进程上下文，不持久化、不通过 Protocol JSON 交换。

ActionPipeline 的 async start/submit/stop/recover、sync snapshot/inhibit 和 state 已交付。默认 **32 个等待批次 + 最多 1 个执行批次**；admission lock 的成功入队点确定 FIFO。没有每个队列元素对应的后台执行任务；worker 只创建当前批次执行任务。每批严格逐条 await InputProvider.execute，首错停止，真实返回结果保留，ActionResult ID 必须匹配。SUCCEEDED 只证明输入被确认，不证明网页业务完成。

取消容量等待不占位置；取消已排队项移除并释放容量；取消执行项仅发一次取消请求，等待 Provider 释放/清理后才向调用方抛 CancelledError。重复取消和 stop 不第二次中断清理。调用方 `asyncio.timeout()` 可覆盖提交至结果总等待，但超时返回可能等待清理，不能解释为未执行或可安全重试。

确认 FAILED 且 Provider 可用、无不确定状态、上下文仍有效时，后续批次可继续。绑定丢失、连接失败、意外异常、输入结果未知、错误结果 ID 或取消时可能产生副作用则保守阻断，清空等待批次并记录终态。STALE 拒绝当前动作并同步 request_immediate，不重放；批次完成也请求新观察。控制状态先改变，通知独立受 50ms 预算约束，慢 Bus 不拖住阻断决策。

## BrowserFreshness 与统一协调门

RuntimeController 创建并拥有 Scheduler、ObservationPipeline、ActionPipeline 和一个跨观察/输入的 asyncio.Lock。观察 begin 至发布和关联引用、以及动作整批执行均在同一门内。逐动作在门内重新核对 Store 快照/引用、connection/page/session/generation、文档 URL/timeOrigin、visual/layout 尺寸与滚动、DPR/zoom/offset 等。BrowserInput 仍在真正输入时做自身 geometry/generation 检查；双方不是相同生命周期的重复检查，02.4 审计保留它们。

实际观察应通过 `await policy.capture(capture_provider)` 获取 Frame，并返回对应 source_frame_id。策略检查真实返回帧绑定，记录 ID 集合，不保留完整 PNG；commit 配对 Store 快照之后才生成引用。区域截图是具体 BrowserCaptureProvider 扩展，可由组合入口用 CaptureProvider 适配器封装后交给 policy.capture，示例已有完整实现。独立重新截图或 DOM-only 观察目前不能取得该 Browser 策略的动作授权；键盘动作也遵循相同来源约束。

Frame.pixel_to_css 是唯一标准图像坐标转换，Runtime 不重复加 scroll 或乘 DPR。上述指纹不代表 DOM 版本，不能阻止相同指纹下局部更新，也不能保证检查与输入送达之间的页面事务性。外部直接访问同一目标不受 Controller 门锁保护；禁止绕过组合器并发输入或更换绑定。

Controller async start/pause/resume/submit/recover/stop，sync reference/snapshot。pause 只暂停观察，动作仍可提交并正常校验；动作 BLOCKED 不强制停止观察。RuntimeSnapshot.state 使用 SchedulerState，action_state 使用 ActionChannelState，两者独立。snapshot 不执行 I/O，不能只看 Controller RUNNING 推断 Browser 可用或所有内部任务健康，还要读子组件状态/统计及实际返回结果。

observe/Input.execute 回调不得 await 自身 Controller 的 submit/recover/pause/resume/stop。统一私有检查在拿 lifecycle 锁前抛 LifecycleError，防止自己等待自己；需要刷新只调用同步 request_immediate。暴露的 scheduler/observation/actions 便于诊断，但组合运行中不得绕过 Controller 门锁直接执行 run_once 或输入。

## 显式恢复及资源所有权

没有 reset_uncertain，没有自动重放。Browser 策略只支持可证明来源的**新目标**恢复，不支持通过重建同页面 Provider 清零未知状态。初始及替换 InputProvider 使用 `policy.create_input_provider(timeout=10.0)`，由调用方 start/close；策略弱引用记录绑定，不拥有 Provider。未通过该工厂创建的 Provider 可以执行，但恢复时缺少旧绑定来源证明，会被拒绝。

外部 owner：等待当前批次清理结束、暂停观察、close 旧 Input；显式 `await policy.create_recovery_target()` 创建受控新目标；unbind/bind 新目标、按需导航并准备页面；创建/start 新 Input；resume 并等待新 Store 版本、pause；取当前 reference，调用 `await controller.recover(new_input, reference)`；随后 resume。新页面 ID 必须不同，工厂 Provider 绑定必须匹配，引用须来自新提交；恢复凭据一次使用。恢复前不得绕过通道给新目标留下按键/鼠标按下状态。旧动作队列已终结，不会因恢复继续。

资源所有权：Application 拥有 Session，Session 拥有 CDP 连接；Capture/Input 借用 Session；Registry 只查找；插件只拥有自己的任务/数据；Runtime 仅拥有自建队列/锁/工作任务。关闭顺序：

1. Controller.stop 先禁止新提交，停止 Scheduler 和 ActionPipeline 并等待在途清理；重复 stop 幂等，某个等待者取消不会撤销共享终止。
2. Plugin.stop/close，等待插件自有任务。
3. Input.close → Capture.close。
4. 仅关闭 owner 自建目标，Session.unbind/close。
5. StateStore/EventBus.close，结束订阅消费任务。

初始化部分失败也由各自 owner 清理。Runtime 不默认关闭传入 Store/Bus/Provider/Plugin/Session。取消需要协程合作，不承诺强杀忽略取消或永不结束的第三方清理。

## 事件、统计与错误输出

观察事件：runtime.observation_completed/failed/stale；动作事件：runtime.action_completed/failed/stale/cancelled/blocked。LifecycleError 等终止路径可能只有组件状态/统计，无事件承诺；当前没有将 stopping 事件作为稳定必发接口。事件不保证与 Store 同时提交，消费者掉线也没有重放。

SchedulerStats 记录 started/completed、periodic/immediate/skipped/coalesced、failed/cancelled、最后时长/安全类别；ObservationStats 记录 attempts/published/stale/failed/timed_out/cancelled/event_emit_failed、观察和发布时长。ActionStats 记录 accepted/executed、completed/failed/stale/cancelled/blocked、pending/full_waits、first_error_stops/uncertain、容量等待/队列等待/执行时长及通知失败。completed 仅指 SUCCEEDED，所有终态计数之和等于已归档 accepted；executed 是出队数，含等待协调门时取消。详细计数定义见 RUNTIME。

单调时钟用于耗时，UTC aware datetime 用于批次归档。事件只携带 ID、类别、时长和观察版本，不写输入文本、按键序列、截图或原始异常消息。原始 ActionResult 按 Provider 契约保留，CLI 日志默认显示统计/error_type，不直接 dump 任意 Provider 错误详情或批次 Action.text。

## BCA-03 / 05 / 06 接入约定

**03 Plugin System：** 管理器负责 Provider ready→plugin.initialize/start→controller.start。Plugin.observe 只返回 PageState，不重复 publish；handle_command 只返回 Action tuple，不自行 execute。为了保持 Plugin 与 Browser 解耦，组合器可在 Registry 注入 CaptureProvider 包装器，其 capture(page_id) 内调用 policy.capture(raw_capture)，并检查请求页面为当前绑定；插件仍只依赖 CaptureProvider。包装器的资源 start/close 由 Core owner 管理，插件不得关闭共享资源。不要把 policy.capture 再指向同一个包装器造成递归。Registry 不承担关闭。

**05 CLI：** 一个通道按序处理命令；对插件 observe/handle_command 的串行要求，可在生成命令期间 await controller.pause，取得同一无 await 段中的 Store snapshot/reference，再 await plugin.handle_command，构造 ActionBatch 并 submit，最后 resume。暂停动作仍可工作，不要从 observe 回调发起这套流程。保存产生动作时的原引用，不临执行时偷换成最新 reference；STALE 应重新观察后重新生成命令/坐标，不能简单换令牌重发旧动作。总超时包括排队和执行，取消不是撤销；BLOCKED 给出显式恢复步骤并等待外部操作。CLI 不从 Event 反推执行必然成功，以 BatchResult 和后续状态为准。

**06 Majsoul：** 业务识别、置信度/UNKNOWN 处置、command 语义与策略归插件；基于实际 Frame 生成坐标并填写 source_frame_id，使用 Frame.pixel_to_css。Runtime 不保证游戏状态不变、不实现牌局重试或自动恢复业务语义。本轮只操作受控测试页，未验证真实雀魂页面/账户，必须另做业务阶段验收。

DOM-only 授权、同目标已知状态恢复证明、跨模块合并测量、插件发现/配置和 CLI 产品层均不在本交付内。没有需要先修改稳定接口才能完成当前 Runtime 的阻塞项；未来涉及这些契约需主会话协调。

## 验收证据与边界

02.4 本轮重新执行原样全量 435 passed；定向修改后 Runtime **165 passed**，全量 **450 passed / 0 skipped**（显式专用 CDP），未配置 CDP 的 Runtime **157 passed / 8 skipped**。mypy strict、Ruff、sdist/wheel 通过。15 项新测试不重复计算旧阶段成果；6 项真实传输故障注入与 1 项真实闭环、8 项模拟审计回归分别标识。

真实闭环覆盖 DPR 1/1.5/2、全图/区域、像素定位点击再观察、滚动/resize/导航/重绑/目标销毁、慢通知和清理；六种中继故障在 Edge 实际处理命令后截留响应或断开连接，验证未知输入不会重发、释放被等待、资源无残留。前后各 30 个正常点击样本和 10 秒持续段；没有用 retire Provider 冒充丢响应证据。

前后观察仍 9 个 page CDP 请求，点击仍 6 个；端到端 median/p95 66.78/109.22→62.01/90.36ms，但观察 p95 与持续吞吐变差，因此不宣称总体加速。默认 100ms 不代表截图实际达到 10Hz。Python 内存为 tracemalloc、含报告样本，不代表 native/Edge RSS；两次结束均 pending=0、reader=false、connected=false、新任务/目标残留=0。Python 3.12/3.13、长时间压力与生产页面仍未验证。

可复现入口与完整原始产物位置见 [02.4 HANDOFF](BCA-02.4_HANDOFF.md)；代码防线审计见 [CODE_AUDIT](BCA-02.4_CODE_AUDIT.md)，机器可读指标见 [PERFORMANCE.json](BCA-02.4_PERFORMANCE.json)。历史 02.1/02.2/02.3 报告保留历史时点，本文件和源码为当前 Runtime 交接依据。
