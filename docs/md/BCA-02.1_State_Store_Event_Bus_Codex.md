# BCA-02.1 — State Store & Event Bus 开发任务

> **项目：** Browser CLI Agent（BCA）  
> **子系统：** BCA-02 / Runtime  
> **阶段：** BCA-02.1 — 基础状态与事件设施  
> **仓库：** https://github.com/Itsukiii/Browser-CLI-Agent  
> **项目根目录：** `bca/`  
> **协议基线：** `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> **前置依赖：** BCA-00 Protocol、BCA-01 Browser（已验收）  
> **任务状态：** 方案已确认，供 Codex 执行

## 1. 开发背景与准备

BCA 是面向指定浏览器页面的感知与输入控制框架。Runtime 负责协调观察、状态提交、事件通知、动作执行和运行生命周期。本阶段首先实现可独立使用的 State Store 和 Event Bus，为后续 Scheduler、Observation Pipeline、Action Pipeline、Plugin Manager 与 CLI 提供稳定基础。

开始实施前，请在统一的 `bca/` 工作目录核对当前 Git 分支、提交与已有代码，并阅读：

1. `BCA_PROJECT_CONTEXT.md` 与 `BCA-02_Runtime.md`（如工作区已同步）；
2. `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/BROWSER.md`；
3. `src/bca/core/runtime/__init__.py`；
4. `src/bca/core/protocol/`、`src/bca/core/providers/`、`src/bca/core/plugins/`；
5. 相关已有单元测试及 `pyproject.toml`。

BCA-01 归档时的参考提交为 `19df477547c26a4131d96191a8bb8bdb8362a4ea`。仓库实际代码与文档是精确接口的依据。若发现公共 Protocol、Provider 或 Plugin 接口必须变更，请先记录提案，交由架构主会话协调。

## 2. 本阶段交付目标

实现两个可以分别构造、运行和测试的 Runtime 组件：

- **`StateStore`：** 保存最新有效的 `PageState`，维护独立于插件 `PageState.sequence` 的单调版本游标，提供快照读取、异步等待更新和安全关闭。
- **`EventBus`：** 向多个订阅者广播 Protocol 2 `Event`，每个订阅者拥有有界 FIFO 队列；满时等待，保证并发发布顺序与单次广播的全体接纳语义。

组件应直接满足现有协议：

```python
class StateSink(Protocol):
    async def publish(self, state: PageState) -> None: ...


class EventSink(Protocol):
    async def emit(self, event: Event) -> None: ...
```

`publish()` 与 `emit()` 的返回仍为 `None`；`await` 正常返回代表组件成功接受提交，不代表持久化、事件已被消费者处理或业务操作成功。

## 3. State Store 接口与语义

建议公开入口位于 `bca.core.runtime`，实现文件为 `src/bca/core/runtime/state_store.py`。

```python
@dataclass(frozen=True, kw_only=True)
class StateSnapshot:
    version: int
    state: PageState


class StateStore(StateSink):
    async def publish(self, state: PageState) -> None: ...
    def snapshot(self) -> StateSnapshot | None: ...
    async def wait_for_update(self, after_version: int) -> StateSnapshot | None: ...
    async def close(self) -> None: ...

    @property
    def version(self) -> int: ...

    @property
    def closed(self) -> bool: ...
```

### 3.1 更新与版本

1. 初始 `version == 0`，`snapshot() is None`。
2. 每次成功接纳 `PageState`，运行时版本严格递增 1。即使业务数据与上一状态相同，也属于一次成功的状态提交。
3. Store 仅持有最新状态；`snapshot()` 返回不可变的 `StateSnapshot` 封装。
4. Runtime 游标与 `PageState.sequence`、`schema_version` 相互独立，不覆盖或修改插件提供的字段。单个 Store 对应单条观察通道；插件实例重建导致的 sequence 重置不影响 Store 游标的单调性。
5. `publish()` 保持 StateSink 契约，状态版本可通过 `snapshot()`、`version` 和等待接口读取。并发发布的先后顺序以 Store 成功提交的串行顺序为准。
6. 保持 Protocol 2 的数据所有权约定：提交成功后发布方不再修改 `PageState.data` 等内部可变容器；读取方将其视为只读。明确在文档中记录此限制。

### 3.2 等待与关闭

1. `wait_for_update(after_version)`：如果当前版本严格大于游标，立即返回最新快照；否则等待下一次有效更新。
2. 多个等待者相互独立；新版本成功提交时唤醒符合条件的所有等待者。慢等待者可直接读取最新版本，不追溯中间版本。
3. 关闭后拒绝后续 `publish()`，使用明确的 Runtime 生命周期异常；所有等待者都应被唤醒。
4. 若关闭时已存在 `version > after_version` 的状态，等待者仍可拿到该最新快照；否则返回 `None` 表示后续不会有更新。
5. `close()` 幂等；等待协程取消时只取消当前等待，不破坏 Store 或其他等待者。
6. 对 `after_version` 进行有效性校验，接受非负整数；拒绝布尔值、负数及错误类型。游标大于当前版本时等待未来超过该游标的版本，或明确采用并记录另一种一致的校验策略；请优先采用前者。

实现上优先使用 `asyncio.Condition` 或等价轻量同步机制，确保版本检查与等待注册之间不存在丢失唤醒的竞态。

## 4. Event Bus 接口与语义

建议实现文件为 `src/bca/core/runtime/event_bus.py`，并从 `bca.core.runtime` 导出公开类型。

```python
class EventSubscription:
    async def get(self) -> Event | None: ...
    async def close(self) -> None: ...

    @property
    def pending(self) -> int: ...


class EventBus(EventSink):
    def subscribe(self, *, max_queue_size: int = 64) -> EventSubscription: ...
    async def emit(self, event: Event) -> None: ...
    async def close(self) -> None: ...

    @property
    def closed(self) -> bool: ...
```

### 4.1 订阅及广播

1. 每次 `subscribe()` 生成独立订阅句柄和有界 FIFO 队列，默认容量 64；容量必须为正整数。
2. 订阅只接收订阅建立后成功提交的事件；不回放历史事件。
3. 所有仍活跃的订阅者收到相同的 `Event` 对象，且对每个订阅者保持同一成功发布顺序。
4. 即使没有订阅者，`emit()` 也可正常完成；表示事件已被 Bus 接受，但没有接收者。
5. `pending` 为当前订阅句柄中尚未读取的已提交事件数量。

### 4.2 等待型背压与原子扇出

本项目已确认 **有界 FIFO + 满时等待**。

1. `emit(event)` 接受提交时获取当前活跃订阅者集合；若存在订阅队列已满，则异步等待容量释放。
2. 当所有目标队列均可接纳事件时，在一个不会异步让出的提交临界区完成广播，将事件加入各队列，再使 `emit()` 成功返回。
3. 单次提交要么被目标订阅集合全部接纳，要么在取消、等待超时或关闭时保持未提交；不能出现部分订阅者收到、部分订阅者没收到的情况。
4. 多个发布者并发时需要确定全局提交顺序；所有订阅者对成功提交的事件观察到相同的顺序。建议以发布串行化协调配合队列容量通知实现，不依赖跨队列逐一 `await queue.put()`。
5. 等待容量时不持有会阻止 `get()`、退订或 `close()` 进展的锁，避免死锁。
6. 订阅者 `get()` 消费事件、订阅者 `close()` 注销以及 Bus 关闭都应唤醒相关等待者。
7. 外部可以通过 `asyncio.timeout()` 对 `emit()` 施加等待预算；取消或超时发生在提交之前时，该事件不会出现在任一订阅队列。已经完成提交后，不把取消或超时解释为消息撤销。
8. 明确并测试在发布等待过程中发生订阅/退订的成员资格语义。推荐将“提交时仍活跃的订阅者”作为一致性目标，并在实现文档中解释这一策略。并发订阅变更必须与原子提交协调，不可产生不确定的半发布状态。

### 4.3 读取、退订及关闭

1. `EventSubscription.get()` 读取本订阅中最早的未读事件；队列为空时异步等待。
2. `EventSubscription.close()` 幂等，注销该订阅并丢弃该订阅未读事件；解除它对发布者产生的背压，并唤醒其等待中的 `get()`。
3. `EventBus.close()` 幂等；阻止新订阅及新发布，唤醒正在等待容量的发布者并使其得到明确的关闭异常。
4. Bus 关闭后，各订阅者仍可按 FIFO 顺序排空**已经成功提交**的事件；队列排空后 `get()` 返回 `None`。
5. 未读取到事件、也不再可能接收事件的等待者须被唤醒返回 `None`；清理过程中不遗留后台任务。
6. 发布时检查 `Event` 类型。已发布的 Event 及其数据载荷按照 Protocol 2 的只读/所有权约定处理。
7. 使用统一的 Runtime 生命周期异常类型（例如 `EventBusClosedError` / `StateStoreClosedError`），尽可能与仓库 `LifecycleError` 体系相容；具体名称与继承关系在实现时明确并记录。

### 4.4 Event Bus 与 Runtime 控制逻辑的关系

已确认采用 **关键运行控制直接执行，Event Bus 负责通知** 的设计。

例如浏览器断开后，后续 Runtime Controller 应先标记不可用、停止接受动作及处理在途工作，再尝试通知 Event Bus。事件背压不能成为关键控制状态转移的前置条件。

本阶段落实以下基础设施原则：

- Event Bus 提供可取消、可由调用方设置超时的 `emit()`。
- 保证关闭、注销订阅和等待任务取消都能有界、可预测地收尾。
- 文档中明确：Event Bus 是通知设施，不是 Runtime 状态的权威来源，也不承担浏览器控制动作本身。
- 后续 Observation/Action/Controller 需要自行采用可靠的调用方式处理 `emit()` 超时或失败，而不把事件通知成功当成关键控制成功的条件。

## 5. State Store 与 Event Bus 的协作边界

1. `StateStore` 是最新页面状态的权威来源，`EventBus` 用于状态变化通知和运行诊断。
2. 两者是独立组件，不构成跨组件事务。State Store 已成功发布的状态不会因为随后 Event Bus 发布失败而回滚。
3. 后续 Observation Pipeline 将统一执行 `observe() -> publish()`，每次成功观察只提交一次 `PageState`，并按需要发布状态更新事件。
4. 后续状态更新事件若包含 Runtime 版本号，必须对应**本次成功提交**的游标，避免多个并发发布后错误读取全局最新版本。BCA-02.1 可在文档中说明后续需由观察串行协调或内部提交机制关联版本；保持现有 `StateSink.publish() -> None` 签名。
5. Runtime 游标、插件 `PageState.sequence`、`schema_version` 分别有不同语义；Event Bus 的成功发布顺序也独立于 `Event.timestamp`。

## 6. 文件与导出建议

```text
src/bca/core/runtime/
├── __init__.py            # 保留既有 StateSink、EventSink，并导出新公开入口
├── state_store.py          # StateSnapshot、StateStore
└── event_bus.py           # EventSubscription、EventBus 与相关异常

tests/core/runtime/
├── test_state_store.py
└── test_event_bus.py
```

按仓库实际组织保持导入方向清晰。注意：既有 `bca.core.plugins` 会从 `bca.core.runtime` 导入 `StateSink` / `EventSink`，不要引入循环依赖。运行时只依赖公共协议及已有 Core 错误类型。

## 7. 单元测试与验收要求

### State Store

- 初始快照与版本。
- 连续发布 100 次，仅保存最新快照且版本为 100。
- 发布内容相同也递增版本。
- 多等待者均可收到新版本；慢等待者获得最新状态。
- 等待注册与发布并发不会丢失唤醒。
- 取消一个等待者不影响其他等待者。
- 关闭时有更新/无更新两类等待结果。
- 发布与关闭并发、重复关闭、非法游标及错误类型。

### Event Bus

- 零订阅者、单订阅者、多订阅者广播。
- 每订阅者 FIFO 与并发发布全局顺序。
- 队列容量限制、满队列等待、消费者读取后继续发布。
- 多个订阅者中只有一个满队列时，事件在全部目标队列可接纳前不发生部分提交。
- 正在等待的 `emit()` 被取消/超时，无部分提交或遗留任务。
- 等待期间新增订阅者、订阅者退订的确定性结果。
- 慢订阅者退订解除背压；订阅者关闭后的等待读取退出。
- Bus 关闭后已提交事件可排空，未提交事件失败；重复关闭及并发关闭。
- 参数校验、异常类型、无后台任务泄漏。

### 工程检查

执行并记录仓库现有质量命令，至少包括：

```powershell
python -m pytest tests/core/runtime -v
python -m pytest
python -m mypy
python -m ruff check .
python -m ruff format --check .
python -m build
```

使用仓库当前虚拟环境和可用命令；如实际环境需要参数调整，记录最终执行命令和原因。测试以可重复的 asyncio 调度与模拟消费者为主，不依赖真实浏览器。性能指标可记录，但不得把未执行测试写成已通过。

## 8. 文档与阶段交付

完成代码后：

1. 更新 `docs/INTERFACES.md` 中 Runtime 已实现公开入口及其语义，保留公共协议原签名。
2. 在 Runtime 相关文档说明：状态游标、只读所有权、事件原子扇出、背压、取消、订阅注销、关闭和运行控制职责边界。
3. 提供最小示例或可执行测试，演示一个 `PageState` 发布/等待和两个订阅者接收 `Event`。
4. 生成 `docs/BCA-02.1_HANDOFF.md`，至少包含：
   - 实际新增/修改文件；
   - 稳定公开 API、方法签名及重要异常；
   - 设计选择与并发/关闭语义；
   - 实际执行的测试命令和结果；
   - 已验证与未验证项目；
   - 对 BCA-02.2 Scheduler/Observation 的接入提示；
   - 待架构主会话协调的公共接口问题（如有）。
5. 在报告中注明工作区实际 Git 分支、提交号以及是否产生新的提交。

## 9. 开发原则

- 维持 `PROTOCOL_VERSION=2` 和既有 `StateSink`、`EventSink`、`Plugin` 接口。
- 遵循 Python 3.12+、asyncio 单事件循环和仓库现有类型检查/格式化约定。
- 对并发竞态、取消、关闭及对象所有权提供明确、可重复的测试。
- 保持 Runtime 对页面业务语义透明。
- 优先采用简单、可审查的机制，确保模块能作为 BCA-02.2～02.4 的稳定基础。

**执行顺序：** 核对源码与基线 → 实现 State Store → 实现 Event Bus → 补充测试和文档 → 运行完整质量检查 → 输出 `BCA-02.1_HANDOFF.md`。
