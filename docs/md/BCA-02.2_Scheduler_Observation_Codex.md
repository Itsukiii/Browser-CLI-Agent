# BCA-02.2 — Scheduler & Observation Pipeline 开发任务（Codex）

> 项目：Browser CLI Agent（BCA）  
> 阶段：BCA-02.2 / Runtime 观察调度与状态发布  
> 日期：2026-11-17  
> 工程基线：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 实现目录：统一工作区 `D:\Project\BCA`（仓库根目录 `bca/`）  
> 当前阶段：**设计已确认，等待 Codex 开发与测试**。本文件不是实现报告。

## 1. 上游依据与开工检查

先阅读实际工作区：

1. `docs/md/BCA_PROJECT_CONTEXT.md`、`docs/md/BCA-02_Runtime.md`（若本地位置不同，按实际文件确认）；
2. `docs/BCA-02.1_HANDOFF.md`、`docs/RUNTIME.md`；
3. `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/BROWSER.md`；
4. `src/bca/core/runtime/`、`src/bca/core/protocol/`、`src/bca/core/plugins/`、`src/bca/core/providers/`；
5. 既有 `tests/core/runtime/` 和 `examples/runtime_basics.py`。

开工时输出简要工作区状态及真实 API 核对结果（`git status --short`、HEAD、现有类型签名），保留用户已有工作区内容。**02.1 是已验收的本地未提交实现**；不得仅凭 GitHub HEAD `19df477...` 代替本地 02.1 代码。公共 Protocol、Provider、Plugin 契约若确需改动，应先形成建议交架构主会话协调。

已知 02.1 接口：

```python
from bca.core.runtime import StateSink, EventSink, StateStore, StateSnapshot, EventBus
# StateStore.publish(PageState) -> None  (async)
# StateStore.snapshot() -> StateSnapshot | None  (sync)
# StateStore.wait_for_update(after_version: int) -> StateSnapshot | None  (async)
# StateStore.version / closed  (sync properties)
# EventBus.emit(Event) -> None  (async)
# EventBus.subscribe(*, max_queue_size: int = 64)
```

既有插件 `Plugin.observe() -> PageState` 为异步方法；Runtime 负责调用后统一 `publish()` **恰好一次**。`PluginContext`、模型与 Sink 公开签名保持不变。

## 2. 确定的设计选择

- 默认观察周期 **100 ms** (`interval=0.1` 秒)，可配置；使用单调时钟的**固定周期、跳过过期 tick**策略。
- 同一观察通道最多 **1 个在途观察**。不维护无限观察请求队列。
- **立即观察请求合并**：观察中到来的若干请求只保留一个待执行请求；无观察运行时尽快触发。
- **暂停采用自然完成**：已开始的观察完成本轮后才确认暂停；暂停期间不开始下一轮；恢复时尽快进行一次新观察，并重设周期基准。
- 使用 **独立的内部新鲜度策略接口**，02.2 先提供可测试通用接口及模拟实现；Browser 实际身份、文档、几何策略在 02.3/02.4 集成。
- Runtime 只管理自身任务；外部组合入口持有 Browser Session、Provider、Plugin 的生命周期。

## 3. 推荐模块与公开入口

建议新增：

```text
src/bca/core/runtime/
  scheduler.py
  observation.py
  diagnostics.py
  __init__.py                  # 仅增量导出，不改变 02.1 API

tests/core/runtime/
  test_scheduler.py
  test_observation.py
  test_scheduler_integration.py

examples/
  runtime_observation.py
```

推荐将 Scheduler 与 ObservationPipeline 分离：Scheduler 只负责何时运行一个无参的异步观察调用；Pipeline 负责调用 `observe()`、执行新鲜度检查、提交状态及尝试发送通知。具体文件拆分可依实际代码调整，公开方法与语义应写进 `docs/RUNTIME.md`。

### 3.1 Scheduler 建议接口

以下为接口设计目标，允许为类型检查选择 `Callable[[], Awaitable[None]]` 或符合 Protocol 的 callback：

```python
class Scheduler:
    def __init__(
        self, operation: Callable[[], Awaitable[None]], *, interval: float = 0.1
    ) -> None: ...
    async def start(self) -> None: ...
    def request_immediate(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def stop(self) -> None: ...
    def snapshot(self) -> SchedulerStats: ...
    @property
    def state(self) -> SchedulerState: ...
```

`SchedulerState` 可用 `StrEnum`（`CREATED`, `RUNNING`, `PAUSED`, `STOPPING`, `STOPPED`）；`SchedulerStats` 应为冻结的只读快照。`interval` 要求正有限数，排除 bool/0/NaN/inf。接口名称可微调，但应提供对应操作且文档说明准确。

生命周期语义：

- `CREATED`：已构造未启动；`start()` 启动循环并尽快执行首轮。处于 RUNNING 重复 `start` 幂等。
- `pause()`：暂停新观察；如已有操作在途，等待其完成（包括成功提交或单次失败处理）再返回；方法返回时保证不再有在途观察。期间的立即请求合并保留，供恢复后执行。多次暂停幂等。
- `resume()`：从 PAUSED 进入 RUNNING，**立即执行一轮**，并以恢复时间作为新的固定周期锚点；PAUSED 期间请求合并，不额外叠加多轮。RUNNING 状态重复 resume 无副作用。
- `stop()`：进入不可逆的终止状态，阻止新请求，取消且 `await` 当前操作与调度任务；多调用者等待同一终止过程且幂等。关闭后不重新 start；外部仍负责插件、Store、Bus 等资源的最终关闭。
- 若 `stop()` 与 `pause()` 竞争，stop 优先，pause 等待安全退出后返回；取消某一个 `pause()` 等待者不得使 Scheduler 意外恢复。调度循环内部异常不得留下悬挂任务。
- 明确 `request_immediate()` 在 CREATED、PAUSED、RUNNING、STOPPED 时的语义及入参/生命周期校验；建议 CREATED 合并成首次观察，PAUSED 保留 1 位 pending，RUNNING 请求唤醒，STOPPING/STOPPED 拒绝或无效操作且须一致可测试。

**固定周期定义**：每个运行 epoch 设单调锚点 `t0`，计划点 `t0, t0 + interval, t0 + 2*interval ...`。某轮完成时若存在未过期的下个计划点，则等到该时刻；已经错过的点仅统计 skipped，下一轮按严格晚于完成时刻的计划点运行（若恰好到点可立即运行，测试需明确边界）。不得为了补偿漏掉周期而连续补跑积压 tick。使用 `loop.time()`/`time.monotonic()`，不使用 UTC 计算延迟。

**立即请求与周期同时到达**：同一次执行机会只开启一轮观察、消耗 pending；在观察中收到立即请求则在结束后安排一轮额外立即观察，多个合并为一轮；当周期也到点，不另加一轮重复观察。停止/暂停的状态门控高于立即请求。避免无 await 的忙循环；立即触发的观察完成后按照相同 epoch 计算下一次定时点。

### 3.2 Observation Pipeline 建议接口

给出对浏览器无依赖的接口，推荐：

```python
class FreshnessPolicy(Protocol):
    async def begin(self) -> object: ...  # 获取观察前令牌/上下文
    async def validate(self, token: object, state: PageState) -> bool: ...


class ObservationPipeline:
    def __init__(
        self,
        observe: Callable[[], Awaitable[PageState]],
        states: StateStore,
        events: EventSink | None = None,
        *,
        freshness: FreshnessPolicy | None = None,
        observation_timeout: float = 10.0,
        event_timeout: float = 0.05,
    ) -> None: ...

    async def run_once(self) -> None: ...
    def snapshot(self) -> ObservationStats: ...
```

也可用泛型 token、内部 `ObservationContext` 类型提升静态检查，但不能要求业务插件返回新的公共模型。可以提供默认 no-op FreshnessPolicy；`None` 表示无额外策略校验，文档必须标记其保护范围，**不能宣传为已解决 Browser 导航与几何失效**。`PageState` 的业务内容仍由 Plugin 负责。

`run_once()` 成功路径（单观察通道串行调用）：

1. 记录单调时钟开始时间及 attempt 计数。
2. `freshness.begin()` 生成令牌，随后 `await observe()`。
3. 验证返回对象确为 `PageState`；运行 `freshness.validate(token, state)`，失败标记 stale，并舍弃本次结果。
4. 新鲜度有效时 `await states.publish(state)` **一次**。`UNKNOWN` / `PARTIAL` 仍是可提交的状态，不以识别不确定为异常。
5. 在成功 publish 后，马上读取 `states.snapshot()` 并在**单发布者/同一协调区域**中确认版本与状态，形成 `runtime.observation_completed` 事件内容（如 `version`, `plugin_id`, `source_frame_id`、耗时）。不得从其他并发发布造成变化的全局 `version` 推断本次提交版本。
6. 以单独的 `asyncio.timeout(event_timeout)` 尝试 `events.emit(...)`；EventBus 等待背压时最多阻塞该预算。通知失败记入诊断，不回滚 Store 已提交状态；通知成功只表示 Bus 接收，不代表 CLI 已消费。

`run_once()` 可建立异步运行锁，保证即使被外部同时调用也不会并发调用同一插件 `observe()`；Scheduler 本身也维持单任务。Store 目前仅有 `publish()->None`，推荐在 Pipeline 的单写入者范围内通过 `snapshot()` 关联版本；在文档中写明本通道由 Pipeline 独占发布责任，插件不能在 `observe()` 内再发布相同状态。禁止改写 02.1 的 `publish` 返回值。

**超时、失败、取消边界**：

- `observation_timeout` 只覆盖 `freshness.begin → observe → validate → states.publish`；事件通知使用独立时间预算。所有耗时使用单调时钟。
- 普通一次观察错误、超时或 stale 记录对应指标；Scheduler 下一计划周期仍可继续。stale 不应自动形成无限密集重试；下一定时 tick 或已明确合并的立即请求触发重观察。
- 对可预期失败可以发送 `runtime.observation_failed` / `runtime.observation_stale` 事件，但发送也受独立预算约束。失败消息只包含安全的分类与少量诊断字段。
- `asyncio.CancelledError` 原样传播；Scheduler `stop` 要取消并 await。不要吞取消并伪造成成功状态。通知层可记录发布失败，但不能阻塞关键停止路径。
- `StateStore` 已关闭、配置非法、不可恢复的生命周期错误应清楚归类，并使上层能够获知；避免无限循环地每 100 ms 重复刷同一结构性错误。可以约定 Scheduler 对明确的 fatal 异常进入 STOPPED 并保留 `last_error`，普通观察失败作为可恢复结果。必须在文档和测试中区别两类。
- 若 `publish` 已成功提交，随后事件通知失败或取消，状态仍然存在；不得重试发布相同 PageState 造成版本重复递增。
- 若插件 `observe()` 已经调用 Provider 并被取消，其清理仍遵从 Browser 已有规则；02.2 的模拟测试核对任务完成，不接管 Browser Provider 的生命周期。

### 3.3 诊断与观察行为

提供只读统计快照，建议字段包括：

- Scheduler：`started`, `completed`, `periodic_runs`, `immediate_runs`, `skipped_ticks`, `coalesced_requests`, `last_run_duration_ms`, `last_error`；
- Pipeline：`attempts`, `published`, `stale`, `failed`, `timed_out`, `cancelled`, `event_emit_failed`, `last_observe_duration_ms`, `last_publish_duration_ms`。

指标累计规则、开始/完成时刻、失败记数与 reset 规则在 `docs/RUNTIME.md` 说明。本阶段约定每次成功状态提交后至多发出一条 `runtime.observation_completed` 通知；失败或 stale 时至多发出一条对应诊断事件。所有通知均使用独立有界时间预算，通知超时只记录统计；避免每 100 ms 打印信息级日志。后续 CLI 可以选择不订阅高频完成事件，而直接从 Store 读取最新状态。

## 4. 关键竞态测试（必需）

1. 初次 start、默认 100ms、间隔非法参数、重复 start/stop、stop 后行为。
2. 固定周期在操作耗时低于间隔时的计划点；操作超过 1～3 个间隔时跳过过期 tick、单通道在途数上限为 1。
3. 立即请求：空闲立即执行；忙碌时 1/10/100 个请求合并；与周期同时到达不双重执行。
4. `pause()` 在操作进行时等待其结束；返回后没有在途任务；暂停期间不会启动新观察；恢复后立即一轮、重置周期锚点。
5. `pause`、`resume`、`request_immediate`、`stop` 交错；请求等待者自身取消不影响全局一致性；退出后无遗留任务。
6. 有效 `PageState` 仅提交一次；`UNKNOWN` / `PARTIAL` 作为有效状态；无效类型和插件错误有明确记录。
7. `FreshnessPolicy` 返回 stale 时不发布；begin/validate 异常、耗时、取消覆盖。
8. `observation_timeout` 取消在途观察并 await，下一 tick 不重入旧观察。
9. 02.1 严格 EventBus 背压：人为填满订阅队列，通知最多等待 `event_timeout`，Store 仍可更新，Scheduler 可继续；事件失败不回滚版本。
10. 提交后通知失败/取消不触发第二次发布；并发试图调用 `run_once` 不造成同插件重叠执行或错误版本配对。
11. `stop()` 期间观察被取消，等待所有本阶段拥有的任务退出；现有 StateStore/EventBus/Provider 不被意外关闭。
12. 重复运行的确定性测试优先使用受控 fake clock / asyncio.Event / barriers，避免脆弱的固定 sleep 对时序下注。

除了新专项测试，现有 02.1 30 项测试及整个仓库回归必须继续通过。

## 5. 示例与验收

新增 `examples/runtime_observation.py`：用**模拟插件/观察函数**演示周期观察、一次立即请求、暂停恢复、StateStore 最新版本读取、EventBus 订阅通知和安全停止。示例需要可在 Windows 直接运行，不依赖 Edge/CDP，也不操作真实网页。

运行质量检查（依实际 venv 路径）：

```powershell
.\.venv\Scripts\python.exe examples/runtime_observation.py
.\.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.2
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest-02.2
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

无 CDP endpoint 时，Opt-in 真实 Browser 测试可按既有约定跳过。记录实际测试数、skipped、环境与异常；保持项目工作区现有未提交文件与用户修改。不要自行创建 Git 提交。

## 6. 文档及交接

更新 `docs/RUNTIME.md`，必要时更新 `docs/INTERFACES.md` 中 Runtime 扩展入口、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_PLAN.md` 和 README 中的实际用法。文档必须覆盖：

- Scheduler 公开签名、固定周期与超时边界、立即请求合并、暂停/恢复、停机优先级；
- Pipeline 的状态提交、单写入者版本关联、新鲜度策略及其能力边界；
- Observer 错误/取消/通知失败与统计口径；
- 对 BCA-02.3 Action Pipeline/Controller 的接口交接与所有权要求。

完成后产出 `docs/BCA-02.2_HANDOFF.md`，记录真实文件列表、签名、关键竞态策略、质量命令与结果、示例输出、已测试/未测试范围、待架构主会话协调项。**停止在 02.2 交付审查，不自行进入 02.3。**
