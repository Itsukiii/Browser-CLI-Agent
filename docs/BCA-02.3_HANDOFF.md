# BCA-02.3 交付审查

日期：2026-11-17。当前仅完成 02.3，未进入 02.4。包版本 `0.2.0`、Protocol 2、Provider/Plugin 公共契约保持不变；未创建 Git commit 或 push。

## 基线与本次范围

HEAD 仍为 `19df477547c26a4131d96191a8bb8bdb8362a4ea`。02.1/02.2 的本地未提交实现为实际基线，全部保留；没有将旧成果重新计作本次新增。原有 `docs/md/BCA_PROJECT_CONTEXT.md` 用户修改、任务文档、`browser-artifacts-manual/` 和历史测试产物均保留。本轮仅对 02.3 原始任务 Markdown 的 Python 代码块添加 Ruff 要求的空行，未改任务内容。

主要新增文件：

- `src/bca/core/runtime/action_models.py`：冻结批次、引用、结果、统计与策略接口。
- `action_pipeline.py`：32 个等待名额的 FIFO、单执行任务、首错停止、取消清理屏障、阻断与恢复。
- `browser_freshness.py`：公开 CDP 指纹测量、实际帧记录、提交引用、新目标恢复来源证明。
- `controller.py`：自有 Scheduler/ObservationPipeline/ActionPipeline 与统一协调门。
- `examples/runtime_actions.py`、`examples/runtime_browser.py`：模拟示例和隔离目标的真实接入示例。
- `tests/core/runtime/action_fakes.py`、`test_action_pipeline.py`、`test_controller.py`、`test_browser_freshness.py`、`test_real_runtime.py`；原 observation 测试新增提交钩子校验。

修改 ObservationPipeline 仅为兼容增加同步提交钩子及参数检查；原单次提交、超时、取消、通知语义保留。新增类型通过 runtime/__init__.py 导出，更新 README、ARCHITECTURE、DEVELOPMENT_PLAN、INTERFACES、RUNTIME。

## 最终公开接口

```text
ActionBatch(*, actions: tuple[Action, ...], observation: ActionObservationRef | None = None,
            request_id: str | None = None, batch_id: str = <automatic UUID>)
ActionObservationRef(*, version: int, token: object)
ActionPipeline(provider, context, events=None, *, capacity=32, gate=None,
               request_refresh=None, event_timeout=0.05)
BrowserFreshness(session, states)
RuntimeController(observe, provider, states, context, events=None, *, interval=0.1,
                  capacity=32, observation_timeout=10.0, event_timeout=0.05)
```

以上构造说明中的 automatic UUID 为说明占位，不是可执行 Python。精确类型定义以源码为准。

ActionPipeline：async start/submit/stop/recover，sync inhibit/snapshot，readonly state。recover 接受 replacement InputProvider 与 ActionObservationRef；inhibit 为 Controller 使用的同步停止接纳点。

RuntimeController：async start/pause/resume/submit/stop/recover，sync reference/snapshot，readonly state。state 复用 SchedulerState，动作通道健康独立为 ActionChannelState。RuntimeSnapshot 包含 state/action_state/scheduler/observation/actions，均为不可变枚举或冻结统计。

ActionContextPolicy：async check(reference, action)→bool、allow_recovery(previous, replacement, reference, blocked_reference)→bool。RuntimeContext 另外实现 FreshnessPolicy.begin/validate、同步 commit(token, snapshot)、reference()。自定义策略是可信组合代码，不能将模拟 Context 当作真实 Browser 新鲜度验证。

BrowserFreshness：上述 RuntimeContext 接口，加 async capture(CaptureProvider)→Frame、create_recovery_target()→str，以及同步 create_input_provider(timeout=10.0)→BrowserInputProvider。资源创建是显式操作，返回的 Provider/目标由调用方拥有。

ObservationPipeline 增加仅关键字 `on_commit: Callable[[object, StateSnapshot], None] | None = None`，其余签名及 run_once→None 不变。

BatchResult 字段为 batch_id、request_id、status、results、queued_at、started_at、finished_at、failed_index=None、error_type=None；只保留实际 Provider 返回的 ActionResult，不生成虚假成功。完整统计口径与可运行恢复步骤见 [RUNTIME.md](RUNTIME.md)。

## 并发和安全边界

成功 append 为接纳点，popleft 为开始点，inhibit 为停止接纳点，均在单事件循环无 await 段内线性化。容量指排队 32，不含执行 1；容量等待不创建后台批次任务。取消入队等待不留位置，取消排队请求移除并释放容量，取消执行请求只发一次取消并等待 Provider 清理完成。重复取消或 stop 不再次打断清理。Controller 先阻止新工作，再并行停止 Scheduler/ActionPipeline，不持协调门等待停机。

观察 begin→observe→validate→publish→commit 与整批动作共享协调门。publish 后核对 Store 实际快照，再同步关联令牌，中间不 await。动作在门内、每条输入之前检查引用对象、Store 快照、页面身份及几何。未记录的帧、伪造/复制引用、未提交令牌不能授权。UNKNOWN/PARTIAL/ERROR 识别状态仍按原协议保留，Runtime 不猜测业务可执行性。

确认的普通失败仅终止当前批次；不确定输入、目标丢失、不可用 Provider、意外异常和 ID 错配保守阻断后续批次。STALE 触发立即观察但从不重放；输入成功也请求新观察。事件是独立 50ms 预算的附属步骤，其失败甚至取消不能遗留提交 Future。实际结果诊断与调用方取消可能竞争，取消不代表撤销。

Browser 恢复仅支持外部 owner 关闭旧输入、新建受控目标、绑定、新 Provider、新观察、显式 recover。工厂记录 Provider 绑定身份，新目标来源被记录且凭据一次消费；仅重建同目标 Provider、清除标志或旧引用不通过。旧初始 Provider 若未由工厂创建，可正常使用，但无法通过此策略恢复，需要重新组装通道。新目标恢复不能撤销旧页面业务副作用。

Controller 不关闭 Plugin、Provider、Session、Store/Bus。上层顺序：Runtime.stop → Plugin stop/close → Input.close → Capture.close → 关闭自有目标并 Session.unbind/close → Store/Bus.close。插件/Provider 必须配合取消；不支持强杀永不结束的第三方清理。不要在组件回调中等待自身通道；停止自调用有明确 LifecycleError 防护。

指纹不是 DOM 版本或网页事务：相同指纹下局部 DOM 更新，以及检查到实际输入之间的变化仍可能发生。只允许同一组合器在协调门内访问该目标；外部并发输入/导航不能被 Runtime 锁阻止。识别仍使用 Frame.pixel_to_css，不另乘 DPR 或加 scroll。

## 实际验收结果

环境：Windows，Python 3.14.7，pytest 9.2.0，Edge `157.0.4341.60`。

| 命令/项目 | 实际结果 |
| --- | --- |
| pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.3 | **150 passed，1.39s** |
| pytest -W error -q --basetemp=.test-artifacts/pytest-02.3 | **435 passed，22.44s，无 skipped** |
| mypy | **50 source files，无问题** |
| ruff check . | **All checks passed** |
| ruff format --check . | 通过；交接文件新增后再次检查 |
| python -m build | 成功生成 0.2.0 sdist 和 wheel |
| examples/runtime_actions.py | first=succeeded，old_reference=stale，state_version=2，accepted=2 |
| examples/runtime_browser.py | initial=succeeded，after_scroll=stale，after_observe=succeeded，after_recovery=succeeded，state_version=3 |

02.3 新增 **58 项 Runtime 测试**，其中 57 项模拟、1 项真实 Browser；原 92 项 Runtime 全部保留。最终全量显式设置 `BCA_CDP_ENDPOINT=http://127.0.0.1:9340`，既有 4 项 Browser opt-in 加新增 1 项均实际运行。未配置端点时这 5 项按既有 opt-in 规则跳过；新增跳过仅为真实 Runtime 测试。

模拟覆盖容量 0/1/32/33、FIFO 不交错、容量/排队/校验/输入/结果交付取消、总超时、重复取消与 stop 清理竞争、共享 stop 等待者取消、首错与阻断分流、TargetLost/timeout/意外错误、错误 ID、慢/取消通知、恢复与 stop 竞争、观察门控、部分启动失败、自调用停止拒绝、各类 Browser 指纹变化与来源提交配对。

真实测试使用独立 Edge PID 20476、端口 9340、专用 profile `.test-artifacts/edge-runtime-actions`，DPI 参数 1.5；为沿用本机可用测试配置，使用 no-sandbox/disable-gpu/in-process-gpu，仅用于隔离验收实例。未连接 9222。示例创建并关闭原测试目标及恢复目标；全量测试结束仅剩启动时的 about:blank，随后通过 Browser.close 关闭该专用实例。保留忽略目录内 profile 和日志，不新增仓库根层临时文件夹。

日志：`.test-artifacts/pytest-02.3-runtime.log`、`pytest-02.3-full.log`、`build-02.3.log`。所有结果来自本轮实际执行，不将模拟结论当作真实浏览器证据。

## Git 与后续接入

git status 中 tracked 修改为 README、ARCHITECTURE、DEVELOPMENT_PLAN、INTERFACES、用户 PROJECT_CONTEXT、runtime/__init__；Runtime 源码/测试、阶段交接/任务文档与示例仍为未跟踪文件，符合 02.1/02.2 本地未提交基线。git diff --stat 不包括 untracked 文件，不能用其统计代表本次新增规模。`git diff --check -- . ':!docs/md/BCA_PROJECT_CONTEXT.md'` 通过；用户 PROJECT_CONTEXT 原有两处 Markdown 尾空格不修改。

02.4 尚需正式完整 Capture→Observe→State→Action→再观察业务链、多 DPI/缩放、压力、真实连接中断/响应缺失与各种输入释放路径。02.3 真实恢复使用外部退役 Provider 触发阻断，未将模拟的 CDP 不确定故障覆盖冒充真实故障注入验收。03 插件应经受控 capture 返回来源帧；05 CLI 保持引用对象、使用总超时、读取安全错误类别并显式恢复，不持久化或重放过期动作引用。本轮不进入这些后续阶段。
