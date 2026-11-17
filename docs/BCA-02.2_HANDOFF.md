# BCA-02.2 Scheduler / Observation Pipeline 交接

2026-11-17：开发与本轮验证完成，停在 **02.2 交付审查**，没有进入 02.3。实际分支 main、HEAD `19df477547c26a4131d96191a8bb8bdb8362a4ea`。02.1 是已验收的本地未提交实现，本轮基于这些实际文件增量开发，没有回退到 Git HEAD 的旧 Runtime。未创建 Git 提交。

## 变更文件与契约

- 新增 runtime/scheduler.py：Scheduler，无新 Browser 全局锁，独立管理一个调度任务。
- 新增 runtime/observation.py：ObservationPipeline 与 FreshnessPolicy，单轮观察、校验、提交和通知。
- 新增 runtime/diagnostics.py：SchedulerState、SchedulerStats、ObservationStats 和安全异常类别辅助。
- 新增 runtime/ports.py：原 StateSink/EventSink 定义移入该内部文件，由 runtime/__init__.py 保持原公开导入重导出，避免具体组件反向导入包引起循环。类型签名、PluginContext/Plugin、Provider ABC、Protocol 2 均未改变。
- 新增 tests/core/runtime/test_scheduler.py、test_observation.py、test_scheduler_integration.py，共 62 项新测试；原 02.1 的 30 项保持通过。
- 新增 examples/runtime_observation.py；更新 RUNTIME、INTERFACES、ARCHITECTURE、DEVELOPMENT_PLAN、README 和本报告。02.2 任务文档仅按 Ruff 调整 Python 示例换行/空行，需求语义不变。

保留用户的 docs/md/BCA_PROJECT_CONTEXT.md 修改、browser-artifacts-manual 和已有全部未提交 02.1 内容。未运行或操作用户浏览器。

## 稳定入口与生命周期

从 bca.core.runtime 导入：

| 入口 | 实际签名/职责 |
| --- | --- |
| Scheduler | Scheduler(operation: Callable[[], Awaitable[None]], *, interval: float = 0.1) |
| 调度方法 | async start/pause/resume/stop() -> None；同步 request_immediate() -> None、snapshot() -> SchedulerStats；只读 state |
| SchedulerState | CREATED、RUNNING、PAUSED、STOPPING、STOPPED |
| ObservationPipeline | ObservationPipeline(observe: Callable[[], Awaitable[PageState]], states: StateStore, events: EventSink \| None = None, *, freshness: FreshnessPolicy \| None = None, observation_timeout: float = 10.0, event_timeout: float = 0.05) |
| 观察方法 | async run_once() -> None；snapshot() -> ObservationStats |
| FreshnessPolicy | async begin() -> object；async validate(token: object, state: PageState) -> bool |

所有间隔/预算要求正有限数，拒绝 bool/0/NaN/inf。统计为 frozen、kw_only 本地快照，不加入公共 codec。详细字段、累计口径及调用示例见 [RUNTIME.md](RUNTIME.md)。

start 首轮尽快执行，RUNNING 重复 start/resume 幂等；PAUSED 必须 resume，CREATED 的 pause/resume 非法。立即请求在 CREATED/PAUSED 合并保留一位，在 RUNNING 唤醒，在终止状态抛 LifecycleError。stop 不可逆、幂等且 CREATED 可直接停止；终止后不能重新 start。

pause 先阻止新轮次，再等待在途 operation 自然结束；取消 pause 等待者不撤销暂停。PAUSED 枚举本身不是“旧操作已经完成”的屏障，应 await pause。resume 会等旧操作完成、立即一轮并重设 epoch。stop 不等待 pause/resume 的生命周期锁，优先阻止新工作；通过共享取消屏蔽任务取消并 await worker。排队 resume 不会覆盖 STOPPED。operation 不允许 await 自己 Scheduler 的生命周期方法，以免自等待死锁。

## 固定周期、提交与错误策略

运行 epoch 的锚点来自 loop.time，计划点为 t0+n×interval。轮次完成后跳过严格早于当前时刻的未执行 tick，恰好到点可运行（tick 比值 1e-9 等值容差）；不补跑积压 tick、不按完成时刻重新累加周期。立即请求与到点周期只开一轮并计 periodic_runs；忙时 1/10/100 个请求合并成一轮额外机会，暂停门控优先。每轮主动让出事件循环，避免同步完成的操作连续触发无 await 忙循环。

Pipeline 的运行锁覆盖观察与通知，外部并发调用不会重入插件。等待锁不计 attempt，也不属于 observation_timeout；需要排队总预算时由外部施加 timeout。单轮在 observation_timeout 内执行 begin→observe→类型检查→validate→publish；通知另用 event_timeout，不占观察预算。

Pipeline 独占其 Store 写入，publish 正常返回后立即检查 snapshot 的 state 身份和 previous+1 版本，再构造通知。检测到版本配对异常抛 LifecycleError；此检查不替代单写入者责任，也不构成跨组件事务。插件不得在 observe 内另行 publish，多个 Pipeline 不可竞争同一 Store。UNKNOWN/PARTIAL/ERROR 等合法 PageState 均可正常提交。

普通错误/超时记录 failed（超时同时计 timed_out）；stale 记录 stale 并丢弃状态，下一计划 tick 或已合并请求再观察。每轮至多尝试一条 completed/failed/stale 通知；通知满队列超时、关闭或异常只计 event_emit_failed，不回滚、重试或重复提交。事件只含版本、关联 ID、类别与耗时，不包含状态 data 或异常消息。

LifecycleError（含关闭 Store、可检测的版本关联失效）作为 fatal 传播，无需等待通知，Scheduler 停止并保留 last_error 类型名。普通 operation 异常则记录后继续；Pipeline 内已处理的普通失败对 Scheduler 来说是一次正常返回。CancelledError 原样传播，不伪造成成功；提交后的通知取消可同时计 published/cancelled，状态仍然存在。

freshness=None 不提供任何额外 Browser 导航/几何/身份保护。本阶段仅有通用策略接口及模拟测试，真实策略按计划在 02.3/02.4 集成。所有权不变：Scheduler/Pipeline 不管理或关闭 Plugin、Provider、BrowserSession、StateStore、EventBus。

## 实际质量检查

Windows / Python 3.14.7 / pytest 9.2.0，使用仓库 .venv。下列为本轮结果：

| 命令 | 结果 |
| --- | --- |
| python examples/runtime_observation.py | 成功，最新版本 4，通知版本 [1, 2, 3, 4] |
| python -m pytest tests/core/runtime -q -W error --basetemp=.test-artifacts/pytest-02.2 | **92 passed / 0.31s** |
| python -m pytest -W error -q --basetemp=.test-artifacts/pytest-02.2 | **373 passed / 4 skipped / 10.12s** |
| python -m mypy | 44 source files，无错误 |
| python -m ruff check . / format --check . | 通过 |
| python -m build | wheel/sdist 成功，日志 .test-artifacts/build-02.2.log |

命令中的 python 实际为 `.venv\Scripts\python.exe`。全量检查仅在命令进程里清除 BCA_CDP_ENDPOINT；4 个 skipped 均为原有 Browser opt-in 真实入口。本阶段不依赖浏览器，不宣称复测 Browser 真实验收。仓库内 basetemp 沿用代理环境的临时目录权限适配。

示例本轮关键输出：Scheduler started=4、completed=4、periodic_runs=3、immediate_runs=1、skipped_ticks=0；Pipeline attempts=4、published=4，stale/failed/timed_out/cancelled/event_emit_failed 均为 0。时间字段由单调时钟产生，仅诊断，不作为性能承诺。

关键测试包含：默认周期/非法配置、短操作与超 1～3 个周期的固定锚点、精确到点不跳过、立即合并 1/10/100 次与周期重合、自然暂停/恢复新锚点、暂停调用者取消、等待恢复时 stop 优先、stop 调用者取消不破坏收尾、回调禁止自等待；有效识别状态、返回类型错误、策略 begin/validate 错误及四阶段超时/取消、并发观察串行配对、提交后通知取消不重发、严格 EventBus 背压下继续观察、超时清理后才开始下一轮、Store 关闭导致 fatal 停止和资源不被越权关闭。

周期测试使用受控单调时钟和 Event 屏障，精确检查计划点；只对真实 asyncio.timeout 做短预算测试，不用固定 sleep 猜测事件发生时刻。完整分层/循环依赖和插件回归通过，原 02.1 行为保持。

## 已知边界与 02.3 交接

未专项验证 Python 3.12/3.13、跨线程/进程、长时负载、真实浏览器观察和业务插件。asyncio 的 timeout/stop 依赖被调用协程合作取消，不能强杀吞掉取消的插件；没有声称固定停机上限。控制器、动作队列和 Browser freshness 未在本阶段实现。

02.3 应先直接变更关键控制状态，再进行有界通知；不得等待 EventBus 空间后才禁用动作。先 stop 并 await Scheduler 任务，再按外部所有权结束 Plugin/Provider/Session/Store/Bus。使用 Pipeline.run_once 作为观察回调，明确每通道唯一 Store 写入者，并在 Browser 接入时实现相应 freshness 策略。事件成功只是被 Sink 接受，不等于消费完成或业务成功。

当前没有需要架构主会话协调的公共 Protocol、Provider 或 Plugin 变更；保持基线继续接入即可。所有本轮变更留在工作区，未创建提交。
