# BCA-02 / Runtime — 运行时调度、事件与状态管理

> **任务编号：** BCA-02  
> **子会话名称：** BCA-02 / Runtime  
> **版本：** v0.1 · 2026-11-16  
> **状态：** 任务规划完成，待子会话方案讨论与 Codex 开发  
> **项目根目录：** `bca/`（单仓库）  
> **项目基线：** `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> **前置阶段：** BCA-00 Protocol 阶段验收；BCA-01 Browser 正式验收归档

## 1. 阅读顺序与接口来源

1. `BCA_PROJECT_CONTEXT.md`：项目背景、分层、模块关系、开发进度和协作规范。
2. `BCA-00_MAIN_SYNC.md`：Protocol 2 基线与公共类型、异步契约。
3. `BCA-01_MAIN_SYNC.md`：Browser 会话、Provider、资源所有权、观察新鲜度和输入恢复约定。
4. `BCA-01_FINAL_REVIEW.md`：Browser 交付验收和实际测试覆盖。
5. 仓库 `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/BROWSER.md`，以及 `src/bca/core/protocol/`、`providers/`、`browser/` 的**实际源码**：精确 API 的权威依据。

仓库：https://github.com/Itsukiii/Browser-CLI-Agent 。BCA-01 归档时审查的参考提交为 `19df477547c26a4131d96191a8bb8bdb8362a4ea`；开始开发时先确认实际工作区分支和版本。

本文件定义设计目标、责任边界与验收条件。未确定的实现细节在 BCA-02 子会话中讨论，并在生成 Codex 提示词前形成明确决策。

## 2. 阶段目标

在 BCA-00 的公共协议和 BCA-01 的浏览器能力之上，构建可供后续插件管理、CLI 与页面适配使用的通用 Runtime。

Runtime 负责两条执行链路的协调：

```text
观察链：调度触发 → 页面观察（经 Provider / 插件观察接口）
      → PageState → State Store → 事件 / 订阅者

操作链：上层提交规范化动作请求 → 新鲜度与绑定检查
      → 顺序执行 InputProvider.execute(Action)
      → ActionResult / 错误事件 → 触发下一轮观察
```

采用异步协调、最新有效观察优先、明确的失败语义和可预测的关闭顺序。运行时对页面状态内容保持通用处理，插件负责具体页面观察与动作映射。

## 3. 责任范围与建议落位

主要实现目录：`src/bca/core/runtime/`；配套测试：`tests/core/runtime/`。按实际仓库结构补充模块，并更新相关 `docs/` 文档与集成示例。

| 组件 | 主要职责 |
| --- | --- |
| Scheduler | 周期任务调度、启停、暂停/恢复、限流、过载周期跳过、取消 |
| Observation Pipeline | 调用观察能力，跟踪观察上下文，组织结果并发布一次状态 |
| State Store | 最新 PageState、单调递增版本、订阅读取、等待更新 |
| Event Bus | 事件发布/订阅、顺序、队列背压、订阅者生命周期 |
| Action Pipeline | 动作排队/串行、上下文检查、执行结果与失败处理 |
| Runtime Controller | 运行状态、任务所有权、协调启动及有序收尾 |
| Diagnostics | 观察周期、延迟、动作排队与执行时间、异常和跳帧统计 |

Core 已在 `bca.core.runtime` 定义 `StateSink.publish(PageState)`、`EventSink.emit(Event)` 协议。实现应直接与既有接口适配，并在开发前核对真实签名。

## 4. 关键契约与设计要求

### 4.1 观察调度

- 提供可配置的观察周期和触发式立即观察入口。
- 同一观察通道默认仅允许一个在途观察；处理时间超过计划周期时跳过过期 tick，避免积压旧帧。
- 每次成功的观察通过现有插件观察协议产生 `PageState`，Runtime 统一负责提交一次 `StateSink.publish()`。
- 观察过程中维护来源、开始/结束时间、页面绑定身份和必要的几何/文档上下文；上下文检查与截图采集的实际集成点由子会话核对 Browser 接口后确定。
- 失败、超时、取消、暂停和恢复需要可区分的状态与诊断信息。

### 4.2 State Store

- 保存最新有效的 `PageState`，维护 Runtime 自身的单调版本或游标；明确与 `PageState` 原有字段的关系。
- 向订阅者提供当前快照、后续更新等待与安全退出语义。
- 明确订阅者速度落后时采用何种状态递送策略（推荐最新状态合并，对事件流单独定义可靠性要求）。
- 只存储与传递结构化页面数据，保持既有公共模型的不可变与序列化约定。

### 4.3 Event Bus

- 以 Protocol 2 的 `Event` 模型发布运行状态、观察完成/失败、动作完成/失败和连接生命周期变化等事件。
- 明确订阅注册、取消订阅、每个订阅者的事件顺序、缓存容量和背压策略。
- 确定关键生命周期事件的错误传播与关闭时排空行为；对慢订阅者设置可观测指标。
- `EventSink.emit(Event)` 使用已有 async 契约，尽量做到跨模块调用语义一致。

### 4.4 Action Pipeline

- 接受规范化 `Action` 或按序动作序列，并调用现有 `InputProvider.execute(action) -> ActionResult`。
- 对同一目标绑定提供明确的 FIFO 顺序及首错停止策略；动作执行需等待明确的完成/失败结果。
- 在动作前核对与观察时相关的 connection、page_id、session_id、generation 及必要的 viewport / 文档上下文。`Frame` 本身不包含 generation，不能仅依据帧时间戳判断有效性。
- `ActionResult.SUCCEEDED` 表示输入指令完成，不代替后续页面观察结果。
- 对浏览器返回的失败、目标丢失、超时、取消和 `input_state_uncertain` 提供明确结果及恢复入口；是否继续执行由可验证的状态决定。
- 处理动作后可触发立即观察，以加速上层获取页面最新状态。

### 4.5 生命周期与资源所有权

- 上层拥有 `BrowserSession`，Session 拥有 CDPConnection，Capture/Input Provider 借用 Session，Registry 只负责注册/查询。
- Runtime Controller 管理自身任务，制定组件启停、运行/暂停、关闭过程和幂等性约定。
- 关闭时先停止接收新工作、停止调度、取消并 `await` 在途任务；在拥有资源管理责任的组合入口中按 `Input.close → Capture.close → Session.unbind/close` 收尾。
- 避免不同组件重复释放同一 Browser 资源；明确 Runtime 对外部传入组件的所有权策略。
- 输入结果不确定时保留明确状态供调用方选择恢复方式，并遵循 Browser 的保守输入恢复约定。

### 4.6 监测与性能

- 使用单调时钟统计：实际观察间隔、采集/观察耗时、跳过周期数、状态发布耗时、动作排队等待与执行耗时。
- 支持低成本获取关键统计快照；日志与事件避免产生高频重复输出。
- 性能验收使用固定模拟延迟、可重复的浏览器集成样本分别评估，记录测量边界。

## 5. 与已交付 Browser 的接口约束

- `BrowserSession` 的连接/绑定 API 为 async：`connect/list_targets/bind/refresh_target/unbind/send/close`，并暴露 `session_id`、`generation`、`page_id` 等上下文。
- `BrowserCaptureProvider.capture(page_id)` 返回 PNG 编码的不可变 `Frame`；区域能力 `capture_region()` 是 Browser 专属扩展，不属于公共 CaptureProvider ABC。
- `BrowserInputProvider.execute(Action)` 返回 `ActionResult`，七类动作执行由 Browser 维护内部状态。两个 Provider 各自串行，跨 Provider 顺序由 Runtime 决定。
- 截图定位坐标通过 `Frame.pixel_to_css()` 转成 CSS viewport 坐标。Runtime 使用既有坐标规则与 Action 字段语义。
- 输入失败后的释放是 best-effort；不确定执行结果需要显式处理。取消的任务必须被等待完成后才能收尾。

## 6. 分阶段开发规划

### BCA-02.1 — 基础状态与事件设施

完成 State Store、Event Bus、背压/订阅策略及基础单元测试；确认协议既有 `StateSink`、`EventSink` 的实际约束，提供可独立使用的 API 和示例。

### BCA-02.2 — Scheduler 与观察链

完成周期/立即观察、跳过过期 tick、最新观察结果提交、失败与暂停恢复管理；使用可控的观察替身测试延迟、过载和取消行为。

### BCA-02.3 — Action Pipeline 与 Runtime Controller

完成动作顺序、新鲜度检查、取消/失败传播、结果记录、运行期资源所有权和有序关闭；接入已实现的 Browser Session/Providers。

### BCA-02.4 — 集成、测量与交接

在受控浏览器测试页验证 Capture → Observe → State → Action → 再观察的闭环，覆盖导航/换绑/几何变化、超时、断连、取消、慢订阅者与资源清理；记录指标和验收证据，形成 `BCA-02_MAIN_SYNC.md`。

## 7. 测试与验收标准

1. State Store 和 Event Bus 支持多个订阅者，更新顺序、背压和关闭行为有可重复的测试。
2. 周期观察在任务超时时不会无限积压，能够通过模拟延迟验证单通道在途上限与过载处理。
3. 有效观察的 `PageState` 按统一契约发布一次；错误与取消有明确事件或结果。
4. Action 序列按顺序执行，失败时停止同批次剩余动作；取消/不确定输入得到可靠反馈。
5. 观察上下文失效时能识别并阻止基于过期上下文的点击，同时保留后续重新观察与恢复路径。
6. 启停、暂停/恢复、重复停止以及在途任务取消可以安全收尾；无遗留运行任务及被误关闭的外部所有资源。
7. 与 BCA-00 Protocol 2、BCA-01 Browser 公共接口兼容；pytest、mypy strict、Ruff、打包测试记录清楚。
8. 实际浏览器受控闭环测试与纯模拟测试分别提供覆盖说明；观察和动作指标具有清楚的统计范围。

## 8. 子会话协作与交付格式

- 本会话先核对共享上下文、仓库当前协议及 Browser 已交付接口，再逐项讨论 Scheduler、订阅背压、动作执行等设计决策。
- 确认设计后输出交给 Codex 的开发提示词；实际实现与测试统一在 `bca/` 仓库中进行。
- 如涉及公共 Protocol、Provider、Plugin 接口的变化，先向架构主会话提交变更建议。
- 每个子阶段完成时记录交付内容、修改文件、接口、测试和遗留事项。
- 整体阶段完成时生成 `BCA-02_MAIN_SYNC.md`，内容至少包括：各模块实现与公开入口、调用/所有权/并发约定、观察/动作的新鲜度和异常语义、实际测试结果、运行指标、BCA-03/05/06 的接入说明和待协调问题。

## 9. 启动状态

BCA-00 与 BCA-01 已完成当前可依赖的交付基线。BCA-02 已形成独立任务范围，可启动子会话做设计与接口核对。实际 Codex 开发以子会话检查到的仓库代码和共同确认的阶段方案为准。
