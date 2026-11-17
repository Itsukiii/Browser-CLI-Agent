# BCA-02.1 State Store / Event Bus 交接

2026-11-17：02.1 开发和本轮测试完成，待阶段审查；没有进入 02.2。工作区实际分支 **main**，HEAD 为 **19df477547c26a4131d96191a8bb8bdb8362a4ea**，与任务参考基线一致。本轮未创建新 Git 提交。

开始时已有 docs/md/BCA_PROJECT_CONTEXT.md 用户修改，以及 browser-artifacts-manual、02.1 任务文件和 BCA-02_Runtime.md 未跟踪内容；保留这些内容。未操作手动浏览器或历史截图产物。仅按 Ruff 在 02.1 任务文档的 Python 示例中增加一个空行，不改变需求。

## 实现文件与公开 API

- `src/bca/core/runtime/state_store.py`：StateSnapshot、StateStore、StateStoreClosedError。
- `src/bca/core/runtime/event_bus.py`：EventSubscription、EventBus、EventBusClosedError。
- `runtime/__init__.py`：保留原 StateSink/EventSink，导出以上类型。具体类以结构化类型满足端口，不反向导入 runtime 包；PluginContext 和 Plugin 接口不变，无循环依赖。
- `tests/core/runtime/test_state_store.py`、`test_event_bus.py`：30 项测试。
- `examples/runtime_basics.py`：可独立运行的状态发布/等待及双订阅广播，mypy 同时检查 Sink 类型兼容。
- 文档：INTERFACES、RUNTIME、README、ARCHITECTURE、DEVELOPMENT_PLAN 及本报告。

| 公开类型 | 签名 |
| --- | --- |
| StateSnapshot | frozen、kw_only dataclass：version: int（正整数）、state: PageState |
| StateStore | publish(state: PageState) -> None、snapshot() -> StateSnapshot \| None、wait_for_update(after_version: int) -> StateSnapshot \| None、close() -> None；version/closed 只读 |
| EventBus | subscribe(*, max_queue_size: int = 64) -> EventSubscription、emit(event: Event) -> None、close() -> None；closed 只读 |
| EventSubscription | 由 subscribe 创建；get() -> Event \| None、close() -> None；pending 只读 |

除 snapshot/subscribe 和属性外，以上方法均 async。StateSnapshot 是 Runtime 本地封装，不扩展公共 Protocol 2 Model 或 codec。StateStoreClosedError / EventBusClosedError 继承已有 LifecycleError，code 分别为 runtime.state_store_closed / runtime.event_bus_closed。类型、游标、容量错误抛 ValidationError，优先参数校验再生命周期检查。游标允许非负 int（不接受 bool），容量必须正 int。

## 并发与关闭决定

StateStore 使用 Condition 协调提交与等待。初始 version=0，只有最新快照；每次成功提交加一，包括相同对象/内容。游标独立于 PageState.sequence/schema_version，不改动插件状态。未来游标等待版本严格超过它。关闭时先检查是否已有符合游标的新快照，有则返回，否则 None；发布关闭竞争按成功取得临界区的顺序确定。取消等待者不影响其他等待者。

EventBus 使用独立发布锁确定成功广播顺序，共享 Condition 协调容量/消费/退订/关闭。提交时重新检查仍活跃的全体订阅者容量，一次无 await 临界区追加同一 Event 对象；没有逐队列 await put，没有后台任务。等待期间新增订阅者参与当前事件，退订者排除，零订阅者成功但没有接收者。

外部 asyncio.timeout 包含等待发布锁与容量的时间。提交前取消/超时不产生部分投递；提交完成后不撤销。一个慢订阅者会阻塞全局后续发布。Subscription.close 丢弃其未读事件、解除背压并唤醒 get；Bus.close 拒绝新提交并唤醒待提交 emit 抛关闭异常，但允许已有队列排空后 get 返回 None。各 close 幂等，无 reopen；用户任务仍由调用方取消并 await。

所有组件限定单 asyncio 事件循环，不支持跨线程使用。PageState/Event 内部 dict/list 不深复制，发布后原发布方和读取方均按只读共享。对进程崩溃、内存耗尽或磁盘持久化不提供事务保证。

## 实际测试与质量结果

环境：Windows / Python 3.14.7 / pytest 9.2.0，仓库 .venv。命令及本轮结果：

| 检查 | 实际结果 |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.1` | 初轮 28 passed；补齐边界后同目录 `-q` 验证 **30 passed / 0.16s** |
| `.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest-02.1` | **311 passed / 4 skipped / 10.40s** |
| `.venv\Scripts\python.exe examples/runtime_basics.py` | version=1；两个订阅者接收同一 Event，正常退出 |
| `.venv\Scripts\python.exe -m mypy` | 39 source files，无错误 |
| Ruff check / format --check | 通过；含任务示例空行格式调整 |
| `.venv\Scripts\python.exe -m build` | wheel/sdist 成功；日志 .test-artifacts/build-02.1.log |

全量运行在命令进程中清除 BCA_CDP_ENDPOINT；4 个跳过均为 Browser 的 opt-in 真实入口。本阶段不依赖真实浏览器，不声称重新验证 01.4 实测。--basetemp 使用仓库临时目录，沿用此环境避免系统临时目录权限问题的做法。

最终 Ruff 格式检查为 102 files already formatted。完整 git diff --check 提示用户既有 docs/md/BCA_PROJECT_CONTEXT.md 第 6、7 行的 Markdown 行尾双空格；该文件未由本轮修改，保留原样。本轮变更排除该已有文件后的 diff 空白检查通过。

已验证：100 次状态提交和 sequence 重置、同内容加版本、慢等待者合并、多等待者及单个取消、注册/发布交错、未来游标、关闭有/无更新、发布/关闭顺序、错误类型；零/多订阅者与对象身份、100 并发发布的相同 FIFO、默认容量及背压、仅一队列满时无部分投递、容量等待取消/超时/关闭、发布锁等待取消、提交后取消不撤销、等待期间订阅/退订、慢订阅注销、读取取消、关闭唤醒及排空、重复关闭、无额外后台任务。另验证事件发布失败不会回滚 Store 状态，现有分层/循环依赖及插件测试随全量通过。

未验证：Python 3.12/3.13 实机矩阵、跨线程/进程、长时大规模负载及真实 Browser→观察管线集成。本阶段没有性能基准承诺，测试依赖可控协程调度，未使用固定时间睡眠作为并发正确性的依据。

## 02.2 接入提示

StateStore 是最新页面状态权威来源；EventBus 只负责通知，不是 Controller 状态权威来源。关键运行控制应先直接执行，再用可取消或有超时预算的 emit 通知；慢订阅者不得延迟浏览器断开后的停用动作。

Store/Bus 是两个独立提交，通知失败不回滚状态。单观察通道使用串行 observe→publish，每次观察只提交一次。若状态事件带 Runtime version，必须在同一串行协调内关联本次提交，不能在多发布者并发后把全局最新版本误作本次版本。保持 publish()->None；无需提前改动公共协议来返回游标。

目前没有待架构主会话协调的 Protocol、Provider 或 Plugin 变更。Scheduler、Observation Pipeline、Action Pipeline、Controller 均留待后续阶段。
