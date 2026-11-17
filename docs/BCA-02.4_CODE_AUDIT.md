# BCA-02.4 代码审计

2026-11-17。此报告初版在修改 Runtime 核心前生成。原样源码 ZIP、SHA256/行数、测试、原始性能 JSON 位于 `.test-artifacts/02.4-before/`。全量原样回归 435 passed / 17.17s；额外审计回归 4 failed / 2 passed，失败用于复现下述问题，不计作原有回归失败。

## 审计清单（先证据，后修改）

| 编号、位置 | 分类与现有行为 | 风险与处理决定 | 原样证据 | 实施结果 |
| --- | --- | --- | --- | --- |
| R1 browser_freshness._Observation.frames / capture / validate / commit | 确实冗余：dict 值持有完整 Frame，所有后续使用仅为 frame_id membership | 改成 ID set；capture 时仍检查实际返回 Frame 的绑定，不削弱来源验证 | rg 仅有赋值及 membership；弱引用回归在提交后仍看到 Frame | 已改 set[str]；第一组专项 17 passed |
| R2 browser_freshness._providers / create_input_provider / allow_recovery | 确实冗余所有权：dict 永久强引用工厂创建的 Provider | 改为 WeakKeyDictionary；输入通道与外部 owner 仍强持有当前 Provider，恢复期间旧/新参数也保持存活；来源值及资格判断不变 | close + del + gc 后 Provider 仍存活的回归失败 | 已改弱键映射；第一组专项及真实恢复 smoke 通过 |
| R3 controller.submit / recover / pause / resume / stop | 锁与任务：stop 有自回调保护，submit/recover 无同类检查，observe 持门再等待自己动作造成自锁 | 统一私有外部调用检查，进入 lifecycle 锁之前拒绝自调用；沿用 LifecycleError，不改签名/所有权/正常调用顺序 | 新增 submit/recover 回归均超时，pause/resume 已由下层拒绝 | 已统一 _external；观察及输入回调回归通过 |
| R4 action_pipeline._Entry.started / _run | 确实冗余状态：可选单调时间写入 Entry，只有 worker 当前栈读取；UTC started_at 另有结果责任 | 单调开始时刻改 worker 局部变量，保留 UTC 字段、取消标志、Future、在途状态 | 仅 _run 内三处访问，无跨任务读取 | 已改局部 started；第二组专项 45 passed |
| K1 BrowserFreshness begin/validate 与 Capture 前后几何测量 | 功能相似但保护不同阶段：观察前后包含插件识别时间；Capture 包含截图原子边界和 PNG/裁剪验证 | 保留；跨组件合并需改变稳定 Browser 契约，当前没有证明同生命周期等价 | 每次观察 9 个 page CDP 请求：Runtime 4 + Capture 5 | 保留 |
| K2 action freshness 与 BrowserInput 几何/generation guard | 必要且独立：引用/版本归 Runtime，实际输入时绑定及坐标归 Browser | 保留最终检查，不能凭旧观察检查跳过真实输入验证 | 每次 click 6 请求：Runtime 2 + Input 几何 2 + press/release 2 | 保留 |
| K3 Controller gate、Observation lock、Provider lock | 不同入口的防线：跨观察/输入协调，独立 Pipeline 防重入，独立 Provider 串行 | 保留，单独使用组件仍需防线，不因 Controller 当前持门而删除 | 原有直接调用/竞争测试及新真实链路 | 保留 |
| K4 _Entry.cancel_requested、inflight、共享 stop task、shield | 必要独立状态：一次取消、防止释放被二次取消、未知副作用识别、多个 stop 等待者 | 保留，不以任务数减少为由移除清理屏障 | 原 02.3 执行取消、重复取消/stop、队列结果竞争测试 | 保留 |
| K5 StateStore 输入检查与 StateSnapshot 检查 | 同形但不同公开构造入口 | 保留，不把直接构造 Snapshot 的校验责任推给 Store | 原状态测试 | 保留 |
| K6 新目标恢复证明、同目标拒绝 | 必要独立防线 | 保留全部条件；不添加清空 uncertain 标志的快捷恢复 | 真实 recovery smoke、同目标重建拒绝测试 | 保留 |
| D1 文档/例子与测试组织 | 历史阶段记录仍有“后续集成”表述；缺少正式 Runtime 闭环测量入口 | 增加独立示例与正式交接，历史报告保留时点，不删除不同竞争语义的测试 | 02.3 真实示例为 mouse move，02.4 新示例从 PNG 识别并点击、再次识别颜色 | 已交付 runtime_integration.py、MAIN_SYNC、HANDOFF 与机器可读性能报告 |

## 原样测量和限制

Edge 157.0.4341.60，Python 3.14.7，专用回环端口 9341；DPR 1/1.5/2、640×480 CSS、全图和区域各 5 次点击，另有 10 秒持续观察。所有时间由示例 perf_counter 采集，启用 tracemalloc。Capture 非 CDP 剩余时间包含 PNG 校验/解码/裁剪/重编码、Python 与测量开销，不能当作纯解码时间。tracemalloc 仅是 Python 分配，不是 Edge/Pillow native RSS。原始 JSON 保存所有样本，后续同一入口同参数比较。

原样 capture_full median/p95 68.06/114.00ms，capture_region 55.84/81.27ms，observe 79.94/154.96ms，freshness_action 1.42/2.60ms，Input 3.06/13.20ms，提交至新状态 66.78/109.22ms。持续观察间隔 median/p95 194.95/208.29ms，111 次观察峰值 1，跳过 tick 45，合并立即请求 57。100ms 默认调度不保证在当前机器、DPR、截图与测量负载下达到 10Hz；不能通过删安全校验宣称解决截图延迟。

全程队列峰值 0（此真实基准为串行点击，不代表容量压力），采样 pending 峰值、Python 内存变化见最终对比；容量压力单独由模拟测试证明。无证据支持合并 K1/K2 的跨层请求，本轮不改变这些路径。

## 最终实施与对照

核心只修改三个 Runtime 私有实现文件：action_pipeline 351→350 行、browser_freshness 227→228 行、controller 162→169 行，合计净 +7 行。去除了一个 Entry 状态字段、完整 Frame 的冗余持有和 Provider 的额外强所有权，增加统一自锁防护；不以净行数下降作为成功标准。其余 Runtime 源码与冻结 ZIP 一致，Browser/Protocol/Provider/Plugin 源码未修改。

最终 Runtime 165 passed，全量 450 passed（含 12 项 opt-in），静态类型/风格/构建通过。实际故障中继覆盖真实 Edge 已执行响应丢失，而非替代输入逻辑。对照：每轮观察仍为 9 个 page 请求，每次点击仍为 6 个，截图及最终输入防线不变。

完整性能表和采样边界见 [HANDOFF](BCA-02.4_HANDOFF.md) 与 [JSON](BCA-02.4_PERFORMANCE.json)。提交至新状态 median/p95 66.78/109.22→62.01/90.36ms，但观察 p95 154.96→191.20ms、持续观察间隔 p95 208.29→305.25ms 变差。两个短样本有主机负载、GC、渲染波动与持续观察样本量差异，**没有证据宣称总体性能提升**。本轮可确定收益为移除无用途对象持有与修复自回调死锁。

真实基准前后均 pending≤1、队列采样峰值 0、任务数 7～8、观察峰值 1；结束后 pending=0、reader=false、connected=false、自有目标残留=0、新增未完成任务=0。弱引用回归明确证明释放对象不再由策略保留；10 秒持续样本不能证明无限时长无泄漏。

没有需要改变公共契约才能完成本轮的阻塞项。跨模块合并几何测量、同目标恢复证明与 DOM 来源授权列为后续架构讨论范围，本轮均未实施。
