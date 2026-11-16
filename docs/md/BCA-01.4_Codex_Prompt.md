# BCA-01.4 / Browser Integration & Acceptance — Codex 开发任务

> 项目：Browser CLI Agent（BCA）  
> 阶段：BCA-01.4 / Browser 子系统集成、最终验收与跨模块交接  
> 工作目录：BCA 仓库根目录（用户环境：`D:\Project\BCA`）  
> 既定基线：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 日期：2026-11-16  
> 前置成果：BCA-01.1、BCA-01.2、BCA-01.3 已通过阶段验收；01.3 报告称全量 `265 passed / 0 skipped`，含真实 Edge 集成测试。该数字仅作为历史基线，本阶段须重新执行并记录自己的结果。

## 1. 工作方式及权威资料

开始前读取并核对**当前本地工作区**的源码与文档，尤其是：

1. 项目共享资料：`BCA_PROJECT_CONTEXT.md`、`BCA-01_Browser.md`、`BCA-00_MAIN_SYNC.md`（若不在工作区可通过项目资料获取）。
2. `docs/INTERFACES.md`、`docs/BROWSER.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_PLAN.md`。
3. `docs/BCA-01.1_METADATA_FIX_HANDOFF.md`、`docs/BCA-01.2_DELIVERY.md`、`docs/BCA-01.3_HANDOFF.md`。
4. `src/bca/core/browser/` 的 connection、targets、session、capture、geometry、input、keys、errors、models 及导出文件；`src/bca/core/protocol/`、`src/bca/core/providers/`。
5. 三阶段既有模拟/真实浏览器测试和 `examples/` 中的示例。

以**本地最新实现和已验收行为**为权威。GitHub 远端可能与本地工作区进度不同，不要用旧版本覆盖已交付修复。先梳理实际调用与契约；发现集成缺口时作局部、可验证的修正，不以接口重设计替代集成验收。公共 Protocol 2 或 Provider ABC 的变更先提出协调建议。

## 2. 阶段目标及交付原则

把 BCA-01.1～01.3 的现有实现作为一个可独立调用的 **Browser 子系统**完成集成验证、使用文档、最终交接，供 BCA-02 Runtime 和其他消费者稳定接入。

阶段完成时应能通过一个清晰、可运行的端到端实例证明：

**连接既有 CDP 浏览器 → 发现并显式绑定 Target → 启动并注册 Capture/Input Provider → 截图获得 `Frame` → 将目标截图像素转换为 CSS 坐标 → 执行 `Action` → 读取真实 DOM 结果验证 → 依序关闭 Provider/Session 并清理。**

本阶段优先提供**薄集成入口、真实集成测试与操作手册**。是否新增简洁的 Browser 组合辅助函数或上下文管理器，由现有代码重复程度决定；如无需新公开 API，保持现有三个对象和 ProviderRegistry 即可，不为形式上的“集成层”增加状态机或抽象。

## 3. 必须保持的公共契约

- `BrowserSession`：连接、目标枚举、显式 `bind()`、`refresh_target()`、`unbind()`、`send()`、`close()`、`page_id`、`session_id`、`generation`、`bound_target` 等以当前实际签名为准。普通导航保留已绑定身份；目标销毁、解绑、断线和换绑会使旧身份失效。
- `BrowserCaptureProvider(session, *, timeout=...)`：`available` / `start()` / `capture(page_id)` / `capture_region(page_id, *, x,y,width,height)` / `close()`；返回 Protocol 2 `Frame`。PNG 编码、截图像素为实际尺寸、viewport 代表可见内容 CSS 坐标、`pixel_to_css()` 负责截图到输入映射。
- `BrowserInputProvider(session, *, timeout=...)`：`available` / `start()` / `execute(action)` / `close()`；支持 Protocol 2 已定义的七类输入，输入状态、不确定执行结果和 best-effort 释放延续 01.3 语义。
- `ProviderRegistry`：注册和类型化查询 Capture/Input Provider；注册本身不启动 Provider。
- `Action`、`ActionResult`、`Frame`、`Viewport`、`ErrorDetail` 等为 Protocol 2 冻结关键字 dataclass；结果和异常按 `docs/INTERFACES.md` 区分；时间戳 UTC-aware，时延使用单调时钟。
- Session 拥有 CDP 连接，Provider 借用 Session。退出顺序：先结束输入动作并 `Input.close()`，再 `Capture.close()`，最后解绑或关闭 Session；清理对异常与取消也要可靠。

## 4. 集成开发要求

### 4.1 标准使用链路

编写一个最小、清楚、可运行的集成示例，放在 `examples/`（例如 `browser_end_to_end.py`），并在 `docs/BROWSER.md` 中给出运行方法：

1. 连接命令行传入的 CDP endpoint，列出可用页面；显式指定 Target ID，或由示例创建并记录**自身的测试 Target** 后显式绑定。
2. 启动 Capture/Input Provider，注册到 `ProviderRegistry`，展示通过协议类型获取能力的方法。
3. 捕获完整 `Frame`；如有指定区域，捕获 Region；将图中可识别的标记或受控按钮中心从截图像素转换为 CSS 坐标，建立 Protocol 2 `Action` 并执行。
4. 用网页实际 DOM 事件或状态变化核验动作生效，展示 `ActionResult` 及必要的 Frame 元数据、采集/输入时延。
5. 在 `try/finally` / 等效异步清理路径中正确释放所有资源；只关闭自己创建的页面。

如示例需要稳定测试数据，使用本地静态 HTML 或 HTTP 测试服务与独立测试 Target。图像识别可用测试标记的确定性色彩/像素中心；要确保**决策点确实取自截图字节**，不能通过直接读取 DOM 位置代替截图闭环。DOM 可在输入后作为独立的验收观测来源。

### 4.2 Session / Provider 联动与并发

确认多个 Provider 借用同一个已绑定 Session 时的行为一致，至少验证：

- 初始化、幂等 start/close 和 ProviderRegistry 查询；Provider 关闭后 Session 是否仍可独立使用。
- 重复截图与动作顺序执行；并行发起的 capture、input 与 session 生命周期竞争时，各操作保持自身契约，不跨目标提交过期 Frame 或发送旧目标输入。
- `Target` 导航、解绑、重新绑定（含同一 targetId 的新 generation）、关闭、WebSocket 断线：旧请求和等待者被正确拒绝，资源不会泄漏。
- 超时和协程取消：按既有 Capture/Input 错误边界、输入不确定状态与有界释放规则处理。记录已经发送动作可能产生副作用的事实，避免把协议确认等同于业务结果可回滚。
- 在 Frame 产生后发生页面变化、resize 或换绑时，说明上层如何判定截图新鲜度。对于集成示例，可在操作前按需检查 session 身份和当前几何；如果使用截图后再输入的组合辅助，必须明确其局限，避免用 `Frame.page_id` 单独代表代际匹配。

避免通过随意新增全局锁改变 Capture/Input 的现有独立串行契约。若实际测试揭示竞态缺陷，针对确定的缺口修复，并增加回归测试。

### 4.3 坐标与内容一致性

通过真实 Edge 验证截图 → 输入的端到端坐标关系：

- 完整截图、区域裁剪，以及有滚动条、非零滚动位置的测试页面。
- DPR 1 / 1.5 / 2（可用独立测试实例或 CDP 设备模拟）；图像真实宽高和映射比例分别校验。
- 使用 `Frame.pixel_to_css()`，输入端直接发送 CSS viewport 坐标。用 DOM 接收事件的坐标、目标元素命中结果确认，不额外乘 DPR 或加 scroll。
- 必须保留浮点精度、像素边界量化及 DOM 事件坐标取整的区别；可借鉴 01.3 最终报告中最大 0.75 CSS px 的实测记录，但不得将历史数据当成本轮结果。
- 测试页面状态、目标与截图时刻信息要能追踪关联；截图/输入正常完成后不等于业务页面状态永久稳定。

### 4.4 故障路径与资源所有权验收

以尽量少而覆盖关键边界的集成用例检查：

- endpoint 无法连接、目标失效或选择错误、Provider 未就绪；
- 图像采集失败/失真、坐标越界、输入被 CDP 拒绝；
- 点击由多个 CDP 消息组成时中间失败、取消及 best-effort 状态释放；
- 关闭顺序、重复 close、失败启动的部分资源清理；
- 最终 CDP `pending_count=0`、reader 已停止、连接已关闭，且没有关闭测试以外的浏览器页面。

对已经由 01.1～01.3 单元测试充分覆盖的逻辑，可复用原测试并增加少量跨模块的真实集成断言；重点查证子系统边界，而非重复铺设庞大的同类单元测试。

## 5. 真实浏览器验收与用户环境

Codex 可在本机自行启动**隔离 Edge/CDP 实例**，使用独立端口、profile 和自己创建的页面完成真实集成测试；测试结束清理该实例及页面，保留可审阅的机器可读报告。尊重用户同时进行的手动体验：**不要操作用户现有的 9222 调试浏览器或其标签页**。如测试环境已有限制，准确说明实际运行范围。

建议新增：

- `tests/core/browser/test_end_to_end.py`：纯模拟/局部集成行为，按工程实际拆分；
- `tests/core/browser/test_real_end_to_end.py`：使用 `BCA_CDP_ENDPOINT` 的 opt-in 真实测试；
- `examples/browser_end_to_end.py`：可单独体验的完整链路；
- `browser-artifacts/` 或 `.test-artifacts/` 中的 `browser-integration-report.json` 和最少量 PNG 证据。

报告建议包含：Edge/CDP 版本；Target/session/generation；Frame 宽高/viewport/区域元数据；截图像素识别位置和 CSS 转换结果；实际 DOM 命中及输入结果；采集和输入耗时的样本、中位数、测量边界；失败/清理结果。对敏感页面数据和输入文本不写日志。

可以复用既有真实截图和输入测试以减少启动开销，但端到端验收须**在一次流程内**证明 Frame→Action→DOM 的闭环和生命周期清理，而不仅是声称各子测试分别通过。

## 6. 接口与文档整理

完成 BCA-01 的正式模块交接文档 `docs/BCA-01_MAIN_SYNC.md`，覆盖：

1. **实际公开入口**：`bca.core.browser` 的 Session、Capture、Input、Target、异常及其稳定使用路径；附最小可运行示例。
2. **运行所有权**：端点连接、目标绑定、Provider 初始化/注册、Input 先关闭、Session 最后关闭、重连/换绑策略。
3. **Protocol 2 适配**：Frame/Viewport 坐标语义、PNG bytes 生命周期、Action/ActionResult 及错误处理、Input 不确定状态。
4. **时序与新鲜度**：页面导航和 resize、旧帧风险、并发/取消处理，上层 Runtime 必须检查或决定的边界。
5. **验收证据**：模拟测试和真实 Edge 结果、性能样本、产物位置、验证环境以及清理状态。
6. **供 BCA-02、BCA-03、BCA-04、BCA-05、BCA-06 使用的契约**：哪些接口可直接依赖，调用方需要做哪些编排、错误恢复和坐标操作。
7. **已知限制与遗留建议**：依据本阶段实测精确记录；区分缺陷、能力边界及后续优化建议。

同步维护 `docs/BROWSER.md`、`docs/ARCHITECTURE.md`、README 和相关开发计划，修正过期示例与数字。公共接口在当前协议下保持兼容。文档应聚焦已实现能力、实际约束与使用方式。

## 7. 质量门槛与最终验收

执行（按工作区实际 Python 环境）以下命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -W error
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

配置隔离真实浏览器端点后，确认 BCA-01.1 / 01.2 / 01.3 / 01.4 的真实入口均实际执行；准确记录测试数、跳过数和运行环境。要求所有本阶段承诺的端到端用例通过，且旧测试保持通过；统计数据以本轮输出为准。

若运行失败，优先修复真实发现的集成问题，新增相应回归后重新运行完整质量检查。用例失败应保留足够的异常阶段、身份与资源信息，避免静默跳过。

## 8. 阶段交付物与暂停点

完成后提供：

- `docs/BCA-01.4_HANDOFF.md`：实现变更、集成实测、质量检查、异常与遗留问题；
- `docs/BCA-01_MAIN_SYNC.md`：供架构主会话和其他子会话复用的**正式 BCA-01 交接**；
- 稳定、可运行的集成示例与测试；
- 真实浏览器 `browser-integration-report.json`，以及用于验证坐标闭环的图像证据；
- 更新后的公开使用说明。

**任务完成后停在 BCA-01.4 的交付与审查。** 向用户提交结果和上述文件位置，由本子会话确认 BCA-01 最终验收，并将 `BCA-01_MAIN_SYNC.md` 交给架构主会话归档。后续 BCA-02 的工作由对应任务会话推进。
