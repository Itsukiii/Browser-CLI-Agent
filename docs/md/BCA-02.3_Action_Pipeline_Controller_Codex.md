# BCA-02.3 — Action Pipeline & Runtime Controller：Codex 开发任务

> 任务编号：BCA-02.3  
> 项目：Browser CLI Agent（BCA）  
> 工作目录：`D:\Project\BCA`（项目根目录 `bca/`）  
> 仓库：`https://github.com/Itsukiii/Browser-CLI-Agent`  
> 基线：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 阶段：**02.3 开发；完成后停在交付审查，不进入 02.4**  
> 文档日期：2026-11-17

## 1. 开始开发前的核对

请在**当前本地工作区**增量开发。BCA-02.1/02.2 已在本地实施并验收，但截至交接均未创建 Git 提交；`main` 的旧 HEAD `19df477547c26a4131d96191a8bb8bdb8362a4ea` 不是完整 Runtime 开发基线。先执行 `git status --short`，检查实际代码及任何用户未提交修改，维护原有内容和历史测试产物。

优先阅读以下文件，并以**本地源码的精确签名**作为实现依据：

1. `docs/md/BCA_PROJECT_CONTEXT.md` / 项目内对应共享总纲与 `BCA-02_Runtime.md`。
2. `docs/BCA-02.1_HANDOFF.md`、`docs/BCA-02.2_HANDOFF.md`、`docs/RUNTIME.md`。
3. `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/BROWSER.md`。
4. `src/bca/core/protocol/`、`src/bca/core/providers/`、`src/bca/core/plugins/`。
5. `src/bca/core/browser/{session,capture,input,geometry}.py`（`geometry.py` 为 Browser 内部实现，不视为稳定对外 API）。
6. `src/bca/core/runtime/{__init__,ports,state_store,event_bus,scheduler,observation,diagnostics}.py`、`tests/core/runtime/`。

如本任务所列“建议 API”与本地精确实现发生冲突，应在保持现有公共契约的前提下采用兼容方案，并在交接报告记载。涉及公共 Protocol、Provider、Plugin 接口的变更需先提交架构主会话确认，不在本阶段自行修改。当前不预设需要升级 Protocol 2。

## 2. 已确认的设计决定

- 动作请求按**批次**进入**有界 FIFO** 队列，默认最多 **32 个待执行批次**；满时 `await` 等待空位。等待可被取消，也可由上层设置总超时。
- 一条动作批次内依次执行 `InputProvider.execute(Action)`；**首个失败即停止后续动作**，保留所有已完成结果。批次成功表示输入指令已确认，不表示网页业务目标已达成。
- 执行前发现观察上下文过期：**拒绝当前批次，并请求 Scheduler 立即重新观察**。新观察完成也不会自动复用旧动作或旧坐标；用户/插件应基于新观察重新生成命令和动作。
- Browser 输入结果不确定时，停止后续动作通道并要求外部显式恢复；不能自动重放或以重建 Provider 对象冒充浏览器恢复。
- Runtime 管理自己的队列、工作任务、协调锁和诊断；外部组合入口拥有 BrowserSession、Capture/Input Provider、Plugin 实例和 Store/Bus 的最终关闭权。Runtime Controller 只关闭/停止**它明确拥有**的组件。
- 关键运行控制先改变内部控制状态、阻止新动作并清理在途任务，再进行有超时预算的事件通知。Event Bus 的慢订阅者不能成为停止或阻断动作的前置条件。
- 02.2 已定 Scheduler 默认 `interval=0.1`、立即请求合并、暂停等待当前观察自然完成。保持其既有行为。

## 3. 既有接口基线（不得用臆造接口代替）

- `bca.core.protocol`：冻结关键字 dataclass `Action`、`ActionResult`、`PageState`、`Event`；`ActionStatus.SUCCEEDED/FAILED/CANCELLED`、`ErrorDetail` 等。`Action` 需要 `page_id`；鼠标动作坐标是 CSS viewport 空间。
- `bca.core.providers.InputProvider.execute(action: Action) -> ActionResult` 为异步；预期执行失败返回 `FAILED`，部分边界失败可能抛异常；`asyncio.CancelledError` 原样传播。
- `bca.core.browser.BrowserSession`：`connection`、`page_id`、`session_id`、`generation`、`is_ready`、`bound_target`；`connect/list_targets/bind/refresh_target/unbind/send/close` 为 async；一个 Session 显式绑定一个页面。
- `BrowserInputProvider(session, *, timeout=10.0)`：`execute()`、`available`、`input_state_uncertain`、`last_error`、`close()`；Provider 内部串行但**不提供 Capture/Input 跨 Provider 全局锁**。失败后 best-effort 释放按键，释放不代表撤销。`input_state_uncertain` 为真时不能发更多动作。
- `Frame.pixel_to_css()` 是截图像素到 CSS viewport 输入坐标的唯一标准转换。Runtime 不重复转换 DPR 或叠加滚动偏移。
- `StateStore`：`snapshot()` 返回最新 `StateSnapshot(version, state)`，`publish()` 无返回值；每观察通道唯一写入者。`EventBus.emit()` 支持有界通知与等待背压。
- `Scheduler(operation, *, interval=0.1)`：`start/pause/resume/stop` async、`request_immediate()` 同步、`state/snapshot()`；`pause()` 的 await 返回是当前操作完成屏障，`stop()` 取消并 await Worker，终止不可重启。
- `ObservationPipeline(observe, states, events=None, *, freshness=None, observation_timeout=10.0, event_timeout=0.05)`：`run_once()`、`snapshot()`；`FreshnessPolicy.begin() -> object`、`validate(token, state) -> bool`。02.2 在观察期间检查新鲜度，尚无 Browser 实际策略；不修改 02.2 已验收统计/超时/单次提交语义。
- `Plugin.handle_command(command: Command) -> tuple[Action,...]`，插件持有网页语义；Runtime 不解析、重写或自动重试业务命令。

## 4. 组件范围与建议文件

新增 `src/bca/core/runtime/action_pipeline.py`、`controller.py`、`browser_freshness.py`（如最终命名不同，保持职责清晰），可适当扩展 `diagnostics.py`、`__init__.py` 和观测协作层。新增 `tests/core/runtime/test_action_pipeline.py`、`test_controller.py`、`test_browser_freshness.py` 及适当的模拟集成测试，更新 `docs/RUNTIME.md`、`docs/INTERFACES.md`、README/ARCHITECTURE/DEVELOPMENT_PLAN 的相关章节，新增 `examples/runtime_actions.py`。

全部新公开 Runtime 类型从 `bca.core.runtime` 明确导出，避免对内部 `__init__` 反向导入导致循环。建议使用标准库 `asyncio`、`dataclass`、`Protocol`、`StrEnum`，保留 Python 3.12+ 与既有严格 mypy/Ruff 配置。

## 5. Action Pipeline：公开类型与接口草案

以下是**设计契约草案**，精确签名可在满足行为的前提下合理完善，交接文档必须记载最终版本。

```python
@dataclass(frozen=True, kw_only=True)
class ActionBatch:
    actions: tuple[Action, ...]
    request_id: str | None = None
    observation: ActionObservationRef | None = None


@dataclass(frozen=True, kw_only=True)
class ActionObservationRef:
    # 引用 Runtime 已验证并提交的观察，而不是仅凭调用方自填的 frame_id
    version: int
    # 推荐内部封装不透明身份；实际字段见 §7
    token: object


class BatchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass(frozen=True, kw_only=True)
class BatchResult:
    status: BatchStatus
    results: tuple[ActionResult, ...]
    failed_index: int | None = None
    # 其他 batch_id/request_id、安全错误类别、时间戳字段按需要补充


class ActionPipeline:
    async def start(self) -> None: ...
    async def submit(self, batch: ActionBatch) -> BatchResult: ...
    async def stop(self) -> None: ...
    def snapshot(self) -> ActionStats: ...

    # 只读运行/阻断状态；必要时提供显式恢复入口
```

要求：

1. 上述 Runtime 本地模型与统计为冻结 dataclass/明确枚举，不扩展 Protocol 2 的 codec；验证输入类型、空批次、重复 ID、混合 page_id、无效上下文等参数。推荐空批次为合法空操作、结果 SUCCEEDED，且不发浏览器输入；如按既有接口约定选择不同方式，必须写测试说明。
2. 同一个 Action Pipeline 只有一个执行中的批次；FIFO 按**成功进入队列的先后顺序**，而非协程创建时间或墙上时钟。批次内部严格依次 `await`。提交成功后返回最终 `BatchResult`；队列满时等待不等于成功接纳。
3. 容量 32 指**排队等待的批次**，不包含正在执行的 1 个批次；如采取另一一致口径，必须明确并测试；默认用此口径。排队中的提交者不无限建后台任务/队列元素。
4. 入队及获取队列位置须在取消安全的同步提交点确定；队列未接受前取消/超时不占位。排队后调用方取消时，若仍在队列中，应移除批次并释放空位；若已经开始执行，则取消它对应的执行流程并 **await 执行取消后的 Browser 内部释放/清理**，保留副作用不确定性。不能出现 caller 已返回取消、内部动作却在后台继续发往页面的情况。
5. `stop()` 先禁止新提交，唤醒等待队列容量的提交者，终结尚未执行的请求，并取消并 await 当前批次；重复 stop 幂等，多调用者取消不能中断共享终止任务。所有等待 submit 的 Future 必须最终完成或抛明确异常，不能悬挂。
6. 不同批次**不可交错执行**；一个失败批次停止自己的后续动作。后续已排队请求是否可继续依安全性决策：已确认、无不确定输入、绑定有效的普通 `FAILED` 可按配置/明确规则继续；状态未知/目标丢失则阻断通道并以清晰结果结束或拒绝待处理批次。严禁不确定时默默继续。
7. `ActionResult.action_id` 应与对应 Action 精确匹配；返回的 `SUCCEEDED` 仅表示输入命令确认；Unexpected error 按异常分类传播或归档，不能伪造 SUCCEEDED。对 `CancelledError` 保留取消语义，同时由 Controller 保留诊断/阻断状态。
8. 支持通知 `runtime.action_completed`、`runtime.action_failed`、`runtime.action_stale` 等事件，附 batch/request/action ID 与安全错误类别、耗时；通知有独立小预算（建议默认 50ms），不得携带 `Action.text`、按键序列、页面图片或异常详情；慢 Event Bus 不延迟输入通道停止/安全状态切换。
9. Action Pipeline 不直接关闭输入 Provider、Browser Session、State Store/Event Bus，也不拥有插件对象。

## 6. 背压、取消和停止的精确竞争语义

- 入队确认点、出队/开始执行点、停止接收点均由同一事件循环协调锁或等价同步结构保障。
- **取消前尚未入队**：无 Browser 副作用、无队列残留。
- **已入队但未开始**：移除批次、唤醒等待空位者，完成为取消/拒绝；不执行动作。
- **已经开始执行**：向当前执行任务请求取消，等待其完成取消和 Browser best-effort 释放；若 CDP 已发消息，效果可能发生。确保结果不会冒充完整成功。
- **stop 与入队竞争**：以明确的同步线性化顺序判定，stop 后没有新批次执行。取消 stop 等待者不能撤销已生效的停止决定。
- **队列满等待超时**：由调用者 `asyncio.timeout()` 包含入队等待与结果等待的总预算；不能误把超时理解为“从未执行”，必须根据是否已经入队/开始执行分别处理，必要时保留不确定状态。
- 明确记录批次的 `queued_at`、`started_at`、`finished_at` 或相应单调计时，诊断可以分辨等待容量、队列等待及执行耗时。时间字段遵循现有 UTC 与单调时钟分工。
- 在内部锁下不做长期 I/O；不要通过持锁 await EventBus.emit 导致死锁或全局停机被订阅者拖住。

## 7. Observation Context 与 Browser 新鲜度

这是本阶段**关键接口衔接问题**：`PageState` 只有可选 `source_frame_id`，`Frame` 没有 generation；02.2 的 `FreshnessPolicy.begin()/validate()` 只在观察内使用，并不会自动产出可供动作复查的令牌。需要增加 Runtime **内部**上下文关联机制，并与实际 `ObservationPipeline` 配合；不得把 token 在无校验的情况下当成可信凭据。

### 7.1 建议设计

1. 内部 `BrowserObservationToken` 记录：Browser Session / Connection 对象身份、`page_id`、`session_id`、`generation`、文档身份（如 URL + `performance.timeOrigin`）、视口尺寸、滚动和 DPR；可附记录时刻和来源 `source_frame_id`。一次 token 对应具体观察尝试。
2. Browser 适配器实现已存在的 `FreshnessPolicy`：`begin()` 截取观察前身份及页面/几何指纹；`validate(token, state)` 重读指纹，只有仍匹配并且观察来源符合已校验的页面时才接受。浏览器层经 `session.send()` 的**公开**CDP 请求测量，不直接把 Browser 的内部 `geometry.py` 当成稳定依赖；应以 01.4 真实观察示例中的测量模式为参考，避免重复实现不一致的坐标转换。
3. 验证通过且 `StateStore.publish` 成功之后，由 Pipeline/Controller 在**同一串行观察提交路径**建立 `StateSnapshot.version` ↔ 该 token 的关联。仅有 `validate()` 成功而没有发布成功的 token，不得授权动作。处理 02.2 `run_once()->None` 的事实：可用内部兼容的提交钩子/装饰器、组合层记录器或适当扩展非 Protocol 公共 API，确保更新与 store 快照精确配对。修改时应保留 02.2 的单次提交、超时/取消和通知规则及全部旧测试。
4. 若 Runtime 不能可靠获得浏览器观察期间实际使用的图像帧身份、插件可能独立重新截图或 DOM，则 **不能声称 token 和识别内容来自同一帧**。对于坐标动作，至少要求插件/命令返回的观察引用与已验证 Store 快照/来源帧相符；对无法提供来源关联的动作，采用明确的拒绝或显式非坐标策略，而不是暗中假定画面新鲜。
5. ActionBatch 入队时绑定已确认的观察版本/引用；**真正执行之前**在全局观察/动作协调边界内再次验证：当前版本还是引用版本，Session connection/page/sessionId/generation 相同，文档、视口、滚动、缩放指纹未变化，并且所有 Action.page_id 匹配当前目标。每个输入动作之前再次做必要检查，防止多步批次跨页面变化继续执行。
6. 若验证失败，返回 `STALE`，不执行过期动作，要求 Scheduler `request_immediate()`；多个刷新请求由已验收 Scheduler 合并。必须对 STOPPING/STOPPED 时 request_immediate 的 LifecycleError 做安全处理，避免覆盖原始失效原因。
7. `Frame.pixel_to_css()` 由负责识别的插件使用。Runtime 只能验证坐标已属于协议 CSS viewport，不修改 DPR/scroll；文档/布局随输入发生变化时执行下一步前应重新判定上下文，宁可提前停止，不沿用旧坐标。
8. Browser 校验读取不能保证 DOM 在“检查完毕”和“点击送达”之间原子不变。实现与文档应明确这是**可检测变化的防护**，而非网页事务保证。

### 7.2 观察与动作跨 Provider 的同步

Browser Capture 与 Input 各自串行，**彼此没有全局锁**。Controller 为相同目标建立一个统一的观察/动作协调门（建议 `asyncio.Lock` 或等价控制），确保：

- 有效观察的 `begin → observe → validate → publish → token关联` 不与动作批次的实际输入交错；可以将轻量通知与重计算部分安排在合适范围，但 token 发布时序与动作检查必须严谨。
- 动作入执行门后再次核对版本与 Browser 指纹，再执行该批次；动作过程中如果输入导致导航/几何变化，下一个动作检查应拒绝旧上下文。
- 调度器暂停/恢复与动作执行协调而不造成自锁；不要在 Scheduler 自己的 operation 回调里 await Scheduler.pause/stop。动作完成或被拒绝后只调用同步 `request_immediate()`，由 Scheduler 的正常任务发起观察。
- 停机时先阻断新动作/观察、取消并 await 在途任务，再结束外部 Browser 资源；所有门锁、队列等待者最终得到明确完成语义。

可以通过薄的 operation wrapper 将既有 `ObservationPipeline.run_once` 与统一协调门组合；也可采取同等安全的结构。选定方案必须说明“观察结果与 token 的发布线性化点”以及“动作真正开始的校验点”，并用受控 interleaving 测试验证。

## 8. 错误分类与恢复入口

请依据实际仓库 `bca.core.errors`、BrowserError、ActionResult/ActionStatus 填充结果，不新增与既有公共协议冲突的错误枚举。

| 情况 | 行为 |
| --- | --- |
| Action 校验失败（参数/键名/坐标） | 标记当前批次失败或传播明确 ValidationError；未发送的动作不执行；诊断包含失败索引 |
| InputProvider 返回 FAILED | 记录真实 ActionResult；停止本批次剩余动作；根据 `input_state_uncertain` 和目标有效性决定是否阻断后续批次 |
| Browser `TargetLostError` / 断连 | 阻断新输入，取消/结束已排队动作并保留诊断；后续必须重新绑定、观察并显式确认恢复 |
| 超时或响应缺失 | 按 Browser 返回的结果及 `input_state_uncertain` 保守处理；不得重发未知动作 |
| 执行任务取消 | 保留 CancelledError 语义，等待原 Provider 清理、标注可能已发生副作用；不能把取消等同于撤销 |
| 观察版本/文档/几何变化 | STALE，拒绝当前批次，发起立即观察；原批次不自动重放 |
| Plugin 新返回的状态 `UNKNOWN/PARTIAL/ERROR` | 原样保留 02.2 状态语义；是否允许某类业务动作由上层/插件约束，不在 Runtime 猜测网页语义 |

建议使用独立的 `ActionChannelState`（例如 READY / BLOCKED / STOPPING / STOPPED）表示输入通道健康，与 `Controller` 的生命周期 CREATED/RUNNING/PAUSED/STOPPING/STOPPED **分离**：输入阻断不强制停止观察。`BLOCKED` 恢复必须为显式 API，验证外部已经将 Browser 输入恢复到**可验证的已知状态**、完成必要的重连/重绑定/新观察，并更换失效 Provider；仅提供 `reset_uncertain()` 清零标志不构成恢复。为后续 CLI 提供安全错误类别和恢复说明，避免泄露输入文本。

## 9. Runtime Controller：生命周期与所有权

建议 Controller 为**单观察通道 / 单绑定页面**的组合器。公开草案：

```python
class RuntimeController:
    async def start(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...
    async def submit(self, batch: ActionBatch) -> BatchResult: ...
    async def stop(self) -> None: ...
    def snapshot(self) -> RuntimeSnapshot: ...
```

具体构造函数应接受已组装的 `Scheduler`、`ObservationPipeline`、`ActionPipeline` 和必要的外部协调引用；避免隐式连接端点或隐式创建/拥有 Browser Session。若 Controller 需要创建 Scheduler，明确其所有权并提供从 Plugin.observe/Provider 装配的可运行入口。

生命周期与协调：

1. `start` 启动已准备好的 Runtime 自有组件；检查必要的外部 Provider 已就绪。组件部分启动失败要清理已创建的 Runtime 任务，不关闭外部 Browser 或 Plugin。
2. `pause/resume` 复用已验收 Scheduler 语义；暂停观察与动作提交的关系需写成明确规则，建议：`pause` 暂停周期观察，动作通道仍需经过正常新鲜度校验才能执行（也可统一拒绝暂停期间提交，但必须明确并覆盖测试）。
3. `stop` 首先同步或在无长期 await 的临界区内禁止接受新操作，然后停止 Scheduler 与 Action Pipeline、取消并 await 其在途任务；确保 stop 期间任何新的 submit/request 都不能重新执行。最终状态 STOPPED，不允许 restart 同一已终止实例，重复 stop 幂等。
4. Controller 的 `stop` 不默认关闭外部 BrowserSession、Provider、Plugin、StateStore、EventBus。**拥有这些资源的上层组合入口**执行：先 Runtime 停调度与任务收尾 → Plugin stop/close → Input.close → Capture.close → Session.unbind/close → Store/Bus 清理，按当前真实所有权与依赖调整；Registry 不释放资源。
5. 关键错误/连接不可用时，先设置 ActionChannel BLOCKED、拒绝新的输入，再尝试有界事件通知；动作通道可阻断而观察仍继续，以便上层诊断与恢复。
6. `RuntimeSnapshot` 汇总 Scheduler/Observation/Action 状态和计数，读取无需 I/O，不能返回可修改内部状态的引用或包含敏感 Action 文本。
7. stop/pause/resume 与 submit 的竞争需要确定优先级和可测试的线性化点；不要在持有全局协调锁时等待自己要取消的观察任务。

## 10. 诊断与指标

优先沿用 `SchedulerStats`、`ObservationStats` 的统计口径，新增冻结的 `ActionStats` 和 Controller 快照。至少包括：已接受/已执行/已完成/已失败/过期/取消/阻断批次数、当前队列长度、队列满等待次数、首错停止次数、输入不确定次数、等待容量/排队等待/执行耗时、最后异常类别。所有耗时使用 `loop.time()` 或 `perf_counter()`，时间戳用 UTC aware datetime。计数在取消、部分执行、超时竞争下避免重复累计；指标定义写入 `docs/RUNTIME.md`。

Event Bus 事件建议 `runtime.action_completed`、`runtime.action_failed`、`runtime.action_stale`、`runtime.action_blocked`、`runtime.stopping` 等。事件消息保持精简，不包含网页内容、图片、原始文本、键盘序列、CDP params/result 或未脱敏异常消息；单条通知有独立有界预算，不影响控制状态权威来源。

## 11. 测试与验收（必须实际运行）

### 11.1 纯模拟单元/并发测试

1. 0/1/32/33 个批次：容量边界、满队列等待、解堵、FIFO、公平性及单通道不交错；并发 submit 顺序以入队确认为准。
2. 不同取消时刻：等待容量、已入队未执行、执行前校验、执行中 Browser 模拟释放、结果返回时取消；保证无悬挂 future / 残留任务，不把效果不确定伪装成安全重试。
3. 一个动作失败时保留已完成 ActionResult、失败索引，剩余动作不执行；普通失败与不确定状态对后续队列有不同处理。
4. `input_state_uncertain`、TargetLost/断连、Provider 不可用、timeout、异常和显式恢复验证；不自动重放旧动作。
5. 注入可控 Browser 身份与文档/几何变化：入队前后、排队中、观察中、每动作之间；失效时拒绝并且只触发合并的立即观察。
6. 观察与动作的全局门控：观察提交/token 绑定期间不交错输入，动作开始校验一定发生在执行门内，测试 navigator/scroll/resize/rebind 路径及可检测的 TOCTOU 边界。
7. Controller 多次 start/pause/resume/stop、在途任务结束/取消、stop 与 submit/恢复竞争、部分启动失败、外部资源未被 Controller.close；慢 Event Bus 不阻塞关键控制。
8. 保持 02.1 的 30 项和 02.2 的 92 项 Runtime 测试全部通过；Protocol 2、Browser、Plugin 测试回归通过。

测试优先使用 `asyncio.Event` 屏障、可控单调时钟及假 Provider，不靠大量 `sleep` 碰运气。记录哪些竞争情形由模拟验证，哪些由真实浏览器验证。

### 11.2 浏览器集成范围

02.3 至少提供受控页面的**最小真实 Browser 接入验证入口**（可选择显式配置本机回环 `BCA_CDP_ENDPOINT` 的 opt-in 测试/示例），验证新鲜度策略能够与已交付 Session/Provider 接口协作。使用独立的 CDP Edge 实例和程序自己创建的测试目标，保留原有用户标签页；明确测试的端口、页面创建与清理策略，不修改日常浏览器目标。全面的 Capture→Observe→State→Action→再观察、多 DPI/压力/断连实测仍由 02.4 做正式集成验收。

### 11.3 质量命令

在仓库根目录运行并记录完整结果（Windows）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.3
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest-02.3
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe examples/runtime_actions.py
```

初始全量回归基准来自用户实测的 **373 passed / 4 skipped**（4 项 Browser 真实集成测试需 opt-in）；新阶段总数应随新增测试增长。02.3 阶段的功能覆盖与测试计数不能把既有 02.1/02.2 成果重复记作新功能。任何新 skipped 必须说明原因。

## 12. 交付要求

开发完成后停留 **BCA-02.3 交付审查**。提交（或保留在现有工作区，按用户 Git 习惯）以下内容：

- `docs/BCA-02.3_HANDOFF.md`：主要文件、最终公开 API 与类型签名、队列和取消线性化语义、真实 Browser 新鲜度策略与观察引用关联、新鲜度失效/不确定结果恢复策略、Controller 所有权及关闭顺序。
- `docs/RUNTIME.md`：补充 02.3 使用方式、状态/统计含义、ActionBatch 提交及恢复调用示例。
- `examples/runtime_actions.py`：可运行的无浏览器模拟 Action → Result → request_immediate 演示；若提供 opt-in 真实 Browser 示例，须隔离目标并安全清理。
- 新增测试及实际 pytest、mypy、Ruff、build 输出结果；区分模拟测试与真实浏览器测试。
- `git status --short` 与主要 diff 摘要，说明原有未提交文件的保留情况；**不要擅自创建 Git 提交或 push**。
- 记录当前仍需 BCA-02.4 验证的场景，以及 BCA-03 Plugin System / BCA-05 CLI 后续接入规则；若遇必须变更 Protocol 2 / Provider / Plugin 公共接口的需求，先整理提案交架构主会话。

**验收重点：动作批次 FIFO + 32 容量等待、取消后可靠收尾、过期立即拒绝并请求新观察、Browser 输入不确定阻断与显式恢复、Controller 任务所有权及停止顺序、既有 02.1/02.2 行为全部保留。**
