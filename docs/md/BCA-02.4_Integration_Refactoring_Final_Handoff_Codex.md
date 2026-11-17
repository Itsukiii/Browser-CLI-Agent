# BCA-02.4 — Runtime 最终集成、性能基线、代码审计与正式交接

> **执行对象：** Codex  
> **项目：** Browser CLI Agent（BCA）  
> **仓库：** https://github.com/Itsukiii/Browser-CLI-Agent  
> **本地根目录：** `D:\Project\BCA`（统一 `bca/` 仓库）  
> **当前阶段：** BCA-02.4；前置 BCA-02.1、02.2、02.3 已验收  
> **协议：** `PROTOCOL_VERSION=2`；当前包版本 `0.2.0`  
> **执行原则：** 先采集原始基线，后审计重构，再执行同条件回归及交接；事实以本地源码、运行记录为准。

## 1. 上下文与必须核对的实际基线

本任务以 **本地工作区中已经实现、但尚未 Git 提交的 BCA-02.1～02.3 代码** 为起点。历史 Git HEAD `19df477547c26a4131d96191a8bb8bdb8362a4ea` 只是 Browser 阶段的参考提交，**不包含本地全部 Runtime 成果**。开始先执行 `git status --short` 并清点已跟踪/未跟踪文件，保留用户修改和已有产物。不要使用会覆盖工作区的 reset/clean/checkout 操作，不自行 commit/push。

按次序阅读：

1. `docs/md/BCA_PROJECT_CONTEXT.md`（若实际目录不同，按仓库查找）和 `BCA-02_Runtime.md`。
2. `docs/BCA-02.1_HANDOFF.md`、`docs/BCA-02.2_HANDOFF.md`、`docs/BCA-02.3_HANDOFF.md`。
3. `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/BROWSER.md`、`docs/RUNTIME.md`。
4. `src/bca/core/protocol/`、`providers/`、`plugins/`、`browser/`、`runtime/` 的公开接口与具体实现。
5. `examples/runtime_basics.py`、`runtime_observation.py`、`runtime_actions.py`、`runtime_browser.py`，及 `tests/core/runtime/`、`tests/core/browser/`。

本阶段前置报告的 BCA-02.3 结果：Runtime **150 passed**；全量 **435 passed、0 skipped**（在独立 Edge CDP 测试环境中）；mypy strict、Ruff、wheel/sdist 通过。用户独立验证 `runtime_actions.py` 输出 `first=succeeded, old_reference=stale, state_version=2, accepted=2`，并在没有 CDP 环境时取得 **149 passed、1 skipped**。这些是历史基线，不能作为 02.4 的新测试结果。

### 既有边界与稳定入口

- Protocol 2 `Frame`、`PageState`、`Action`、`ActionResult`、`Event`、`StateSink.publish()`、`EventSink.emit()` 保持兼容。
- BrowserSession 拥有 CDP 连接，Capture/Input Provider 借用；ProviderRegistry 只查询，不负责关闭资源。
- Runtime 已有 StateStore、EventBus、Scheduler、ObservationPipeline、ActionPipeline、BrowserFreshness、RuntimeController。保留其已经公开并经测试的主要行为。
- Scheduler 默认 100 ms 固定周期、跳过过期 tick、合并立即请求、暂停允许当前观察自然完成。
- StateStore 只保留最新状态；EventBus 是有界 FIFO，满时等待，广播提交原子化；通知不是运行控制的权威来源。
- ActionPipeline 默认排队容量 32（不含执行中的一个批次）、FIFO、首错停止；旧观察引用触发拒绝和刷新，输入结果不确定时阻断并显式恢复。
- ObservationPipeline 负责单次有效状态提交与版本关联；BrowserFreshness 使用真实绑定/文档/视口上下文；Runtime Controller 协调任务，外部组合入口拥有插件、Provider、BrowserSession、Store/Bus 的资源释放权。
- 有效输入坐标使用 `Frame.pixel_to_css()` 的 CSS viewport 坐标；不得二次叠加 DPR 或 scroll。

## 2. 阶段目标与交付顺序

BCA-02.4 的整体目标是：**真实完整链路验证、可量化性能与资源基线、基于证据的代码整理、同条件回归、最终跨会话交接。**

必须按以下顺序推进：

1. **02.4-A：基线复核、完整集成、性能测量。** 冻结整理前的测试与性能证据。
2. **02.4-B：代码审计与定向精简。** 先生成审计报告，按证据逐项修改；每组修改及时回归。
3. **02.4-C：最终集成回归、性能对比、交付。** 用相同或注明差异的条件验证重构后的行为并输出 `BCA-02_MAIN_SYNC.md`。

若关键变更会修改公共 Protocol/Provider/Plugin/Browser 已验收契约、跨模块资源所有权或已定行为，应**先形成待架构主会话协调的变更提案**；不要在本轮默默改变这些接口。允许在 Runtime 私有实现中整理结构和抽象，只要公开行为与测试兼容。

## 3. 02.4-A：集成场景与性能基线

### 3.1 实现/完善真实闭环

在隔离的本机 Edge/Chromium CDP 实例、**自建受控测试 Target** 中，验证实际路径：

```text
BrowserSession 绑定受控页
  → CaptureProvider 截图（Frame）
  → 插件或受控观察替身识别（PageState，关联实际来源帧）
  → ObservationPipeline → StateStore（版本更新）→ EventBus 通知
  → RuntimeController.reference() / ActionBatch
  → ActionPipeline → InputProvider.execute(Action)
  → 页面 DOM/Canvas 受控可观测效果
  → 立即重新观察 → 新 PageState、State Store 版本更新
  → 资源清理及残留检查
```

既有示例可复用、扩展，但正式闭环必须核实 **确实使用真实截图和输入 Provider**，而非在观察或输入关键环节用脚本伪造成功。DOM 可以用于受控测试断言，不替代真实点击。检查结果关联 `frame_id`、观察版本、动作/批次 ID 及当前绑定，避免仅因某条打印日志就宣称整链路正确。

测试页面应可控、可重复，覆盖正常点击、滚动引起旧引用失效、重新观察后成功、导航/重绑/resize/viewport 变化及关闭。针对不同 DPR（建议 1、1.5、2）与全图/区域采集核对实际像素到 CSS 的坐标闭环；区域采集如使用 Browser 扩展 API，应明确其具体类型约束。Browser 不支持的缩放模式保持原错误边界，不以“扩大覆盖”为由修改协议。

### 3.2 失败与资源测试

真实 CDP 能力可以验证的场景包括：受控目标关闭、连接断开、重绑、在途 capture/action 取消、重复 stop、独立标签被正确保留；确保任务被取消后 **await** 完成并核对资源状态。

对于 **响应丢失导致的输入结果不确定**、释放过程中失败等情形，优先使用可控 CDP 传输故障注入或有明确作用点的模拟替身；将每项证据注明为 `real-browser`、`fault-injection` 或 `simulated`。不要用“主动 retire Provider 的真实浏览器测试”冒充真正的 CDP 响应丢失验证。可控复现不了的实际故障应明确列入剩余风险，不伪造已覆盖。

记录：`pending_count`、`reader_running`、`connected`、自建目标残留数量、原有 Target 是否保留、Runtime 自有未完成任务数、关闭异常以及 input_state_uncertain 的最终情况。使用隔离 profile 和自选新调试端口，不碰用户日常浏览器会话，不操作真实雀魂账户/对局。只关闭本测试实际创建和拥有的 Target/实例。

### 3.3 延迟、吞吐及资源测量

先对**原样代码**采集基线，再进行精简重构。使用单调时钟，给出测量点和样本量；至少记录：

- Capture 耗时（CDP 获取、图片校验及解码/裁剪，按可测边界区分）。
- `observe()` 总耗时、状态 publish 耗时、事件 emit 耗时及事件超时计数。
- Scheduler 实际观察间隔、过期 tick 跳过量、立即请求合并量、在途观察峰值。
- 动作队列等待、上下文新鲜度验证、Input Provider 执行、从提交动作到新观察状态可用的端到端耗时。
- 各阶段 CDP 请求次数及其分类（特别是重复几何/文档测量）。
- 短时基准与持续运行样本中的队列长度、在途任务、连接 pending、内存用量；如需高于基础依赖的进程内存指标，明确采样方法和可选依赖。

建议报告样本数、median/p95、最大值以及环境配置（Python/Edge/DPR/显示配置/窗口与页面状态），避免将模拟耗时与真实 CDP 耗时混合汇总。性能阈值以**实测结果及测试稳定性**为依据，不事先编造“必须达到”的毫秒数。若测量受机器负载影响，记录限制。用同一种测量定义比较重构前后；不能声称对照不存在的指标得到优化。

## 4. 02.4-B：全局代码审计与精简

### 4.1 先提交审计证据，再修改关键路径

先生成 `docs/BCA-02.4_CODE_AUDIT.md`（建议），列出可定位到文件、函数、调用路径的具体问题：

| 字段 | 要求 |
| --- | --- |
| 编号与位置 | 模块、函数、必要时行范围 |
| 分类 | 重复验证 / 冗余状态 / 历史逻辑 / 过度抽象 / 异常包装 / 锁与任务 / 不必要的 CDP 往返 / 重复测试 |
| 现有行为 | 当前事实、已存在下层保障、触发场景 |
| 风险 | 删除/合并是否影响目标身份、输入未知状态、取消清理和竞态 |
| 处理建议 | 删除、合并、保留、延后及原因 |
| 证据 | 对应测试、实际调用计数或性能样本 |
| 结果 | 最终变更位置与回归结果 |

请将审计分类为：**必要且独立的防线**、**功能重复但保护不同阶段的防线**、**确实冗余且可精简的逻辑**。不得只用“检查次数多”“代码行数多”判断冗余。

### 4.2 精简优先级

优先从低风险、收益明确的项目开始：

1. 删除已经不可达或未引用的旧路径、过时助手函数、重复适配层；确认相关测试/示例是否需要跟进。
2. 整理重复的数据模型转换与重复参数类型判断，将校验放在拥有相应事实与责任的边界；Runtime 负责观察引用与批次决策，Browser 负责实际输入时的安全与身份，Protocol 负责数据结构。
3. 统一同一组件中的冗余状态变量和派生属性，明确唯一真相来源，减少人工同步标志。
4. 简化异常链与诊断生成：错误分类清楚，保留原始 cause；将业务决定留在 Runtime 适当层，减少同层级的重复捕获、重复消息包装。
5. 审查 Scheduler/ObservationPipeline/ActionPipeline/Controller 的锁与 Future/Task 生命周期；避免不必要的锁嵌套、同一门控重复持有和不必要的后台任务。只调整能通过竞态回归证明安全的实现。
6. 对频繁发生的 Browser 指纹/几何测量做 CDP 请求路径分析；在存在相同生命周期保证的情况下合并冗余测量，保留 TOCTOU（检查后到执行前变化）风险所需的最终检查与 Browser 原有 generation guard。
7. 精简与现有实现不一致的文档、例子和测试组织；保留确实验证不同并发竞态的测试，不单纯按测试总数删除。

任何影响真实输入副作用、取消后按键释放、旧目标/旧观察安全隔离、未知结果的恢复资格、队列 FIFO 和首错停止的修改，都须有对应的新/旧测试支持，并在审计报告说明为何不会破坏防线。尤其对 `BrowserFreshness` 的同目标恢复拒绝与受控新目标来源证明，不应因复杂度较高就未经论证弱化。

### 4.3 重构控制与阶段门

- 每组变更尽量独立、可定位；每组运行相关专项测试，出错先定位本组变化。
- 需要改变公共签名、稳定异常类别、关键并发语义的优化，停止该项并在报告列出变更提案，等待主会话协调；其余部分可继续。
- 避免一次性跨所有模块重写。没有具体证据证明冗余的保护逻辑，保留并记录理由。
- 允许更新公开文档以精确反映当前实现，但不要把实际未完成的功能写成已完成。
- 保持项目 Python 3.12+ 类型与异步约定；mypy strict、Ruff 及构建必须通过。

## 5. 02.4-C：最终回归与交付

### 5.1 自动化测试

至少执行并报告准确命令、环境及结果：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.4-runtime
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest-02.4-full
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

真实浏览器测试单独使用受控 CDP 环境执行，并记录明确启用的环境变量、运行/跳过项目及数量。不应因缺少真实 CDP 而将 `skipped` 隐藏；也不要为了得到 0 skipped 而误连日常浏览器。运行核心示例与新增完整闭环示例，保存机器可读结果（推荐 JSON）与必要截图。运行 `git diff --check`，区分本轮变更和用户之前留下的 Markdown 空白问题。

### 5.2 集成与竞争测试矩阵

至少覆盖：

- 真实正常完整链路、动作后重新观察、版本与实际 DOM/测试目标效果一致；DPR 1/1.5/2 与全图/区域截图（记录实际覆盖）。
- 旧观察、滚动、resize、导航、重绑、目标销毁；拒绝过期 ActionBatch 且发起新观察，不重放旧动作。
- FIFO 队列容量边界、满队列等待、等待取消、执行中取消、两批次之间的隔离和首错停止。
- 持键/鼠标按下后异常、输入结果不确定状态、恢复凭据与新目标来源、失败清理；明确真实/注入/模拟证据。
- observe/capture/输入/状态发布/通知各阶段失败及取消；Controller 停止、重复 stop、取消等待关闭与部分启动失败。
- 慢事件订阅者、EventBus 超时与 StateStore 已提交结果、关闭先后和多订阅者顺序。
- 可重复的短时负载与持续运行：记录采样区间和内存/任务/队列/连接 pending 变化，合理选择时长以证据和环境可用性为准。

### 5.3 重构前后对比

输出相同测试条件的 before/after 表格（无法同条件比较须标注）：

- 核心模块及函数的代码规模、移除/合并的路径与净变化；**仅作为辅助信息**。
- 每轮观察/每批次动作的 CDP 请求数、测量路径数量及相关开销。
- 观察间隔、capture、freshness、动作延迟、端到端状态更新延迟的 median/p95。
- 失败/取消、资源释放、关键竞态回归及未改变的外部契约。
- 净性能可能上升/下降/无明显变化，基于证据如实说明，不强求“必须更快”。

## 6. 测试环境与资源保护

以 Windows / Python 3.14.7 / Edge 为主要验证环境，同时在可用时验证 Python 3.12/3.13；缺少环境则记录尚未验证。独立浏览器实例使用专用 profile、独立回环 CDP 端口和自建测试页面。严禁假定已有 9222 是测试实例。Browser 既有 loopback 安全边界不变。不要修改系统环境、使用用户生产网页或关闭非本测试创建的 Target。测试日志保存在 `.test-artifacts/` 等已忽略目录，必要的正式交付报告放 `docs/`。

## 7. 交付物与主会话同步

最终至少提供：

1. `docs/BCA-02.4_CODE_AUDIT.md`：清理清单、处理理由、变更定位、必要防线说明、重构前后对照。
2. `docs/BCA-02.4_HANDOFF.md`：本阶段开发范围、文件列表、执行的命令和真实测试结果、性能/资源统计、残余风险、工作区状态。
3. `docs/BCA-02_MAIN_SYNC.md`：供架构主会话使用的 **Runtime 正式跨模块交接**，整合 BCA-02.1～02.4 实际成果。应说明稳定公开入口、构造/调用签名、资源所有权、并发和锁、State/Event 的背压、调度/观察、动作批次/新鲜度/恢复、关闭顺序、事件与统计语义，及 BCA-03 Plugin System、BCA-05 CLI、BCA-06 Majsoul 的具体接入约定。
4. 更新 `docs/RUNTIME.md`、`docs/INTERFACES.md`（仅已确认的实际契约）、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_PLAN.md`、必要 README/示例与测试。
5. 一个可重复执行的全链路真实浏览器示例/测试和机器可读集成报告；若复用已有文件，说明入口、测试参数和结果位置。

交接报告清楚区分 **Codex 本地实际执行**、**仅检查源码的审查**、**模拟/故障注入**、**真正的 Edge 浏览器集成测试**。不得将此前阶段的数据当作本轮新实验。必要时附上审计报告的具体结论及尚待架构主会话协调的事项。

## 8. 完成标准与最终边界

BCA-02.4 完成的标准是：受控页面的完整观察→动作→再观察链路经过验证；并发和失败场景有明确证据；关键性能与资源指标有量化记录；冗余逻辑经审计后合理精简；重构前后保持 Protocol 2 和稳定模块接口行为；全量回归、静态检查和构建结果明确；正式交接文档与实际源码一致。

此任务交付后 **停留在 BCA-02.4 交付审查**，由本会话验收，并由架构主会话归档 `BCA-02_MAIN_SYNC.md`。不自行进入 BCA-03 或其他子系统开发，不自行创建提交或推送远端。
