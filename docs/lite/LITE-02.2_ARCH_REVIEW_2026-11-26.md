# BCA-lite · LITE-02.2 架构与代码复核

- 复核日期：2026-11-26
- 仓库：`Itsukiii/Browser-CLI-Agent`
- 目标分支：`lite`，复核时 HEAD `e38e916ffacfaf856119bea1c2d3f28aa2aaa1a5`
- 范围：实现提交 `0dcaf74`、归档提交 `e38e916`；`src/bca/lite/{plugin.py,observation.py,vision.py,_native_vision.py,bridge.py}`，`tests/lite/{test_observation.py,test_coordinator_lifecycle.py}`，交接报告、`PLUGIN_CONTRACT.md`、原始日志和 JSON。
- 审查方式：GitHub 远端源码及原始证据静态复核；架构主会话未在用户的 Windows/Edge 机器自行执行测试。

## 一、决定

**实现主体预验收通过，发现一项须补证的命令结果可靠性缺陷；LITE-02.2 暂不标最终 Accepted。** 允许准备 LITE-02.3 测试设计、隔离 Edge fixture 和稳定性脚本，但请先提交此处的定向修正及回归证据，再宣布 02.2 Accepted 与正式进入 02.3 功能开发。

此决定不否定现有设计。`BusinessPlugin` 纯业务、`MaaVisionFacade` 独占 native 对象、`ObservationCoordinator` 单门协作、观察来源/内容签名/回合标志分离均符合已批准的 LITE-02 方案。

## 二、已核对的能力

1. `BusinessPlugin` 只有 `plan / observe / format_state / parse_command / resolve / close`；状态 DTO 冻结，payload/signature 对递归 tuple、标量和有限浮点进行检验，VisualTarget 只指向识别候选，不接收任意像素坐标。
2. `ObservationCoordinator` 串行覆盖 `refresh`、新的业务观察、单步命令授权、native click 及后置观察；同内容多帧只生成一次状态变化通知，有界队列记录丢弃，读取 `?` 重新采集。
3. 写入须在新观察下校验 `interaction_revision`、deadline、业务 MATCHED、唯一真实视觉候选和原始 `ObservationRef`。调用方无法通过复制 `RecognitionBatch` 重新获准点击；候选点由 Maa 图像坐标映射，不做 CSS/DPR 二次转换。
4. Native stop 失败、异常或仍 running 时不 Destroy，保留依赖与 worker；成功后在同一 worker 依 Tasker→Controller→Resource 销毁。Destroy 抛异常的结果不确定时隔离句柄并拒绝重试，不把清空 `_handle` 等同释放成功。`CloseReport.released=false` 不可向应用报告已关闭全部底层资源。
5. 原始证据：lite `105 passed / 5 skipped / 22.97s`，全量离线 `867 passed / 50 skipped / 59.56s`；mypy、Ruff、格式和构建报告均存在。原生受控图像持续观察达到约 `1.950586 Hz`（短时，0.5s 调度间隔），不等价于真实 Edge 或长期稳定性。
6. `docs/lite/LITE-02.3_STABILITY_PLAN.md` 已保留历史 OpenCV 4096×4096 decode access violation 的进程级复测策略；未对未知原因作推断。

## 三、P1 阻断：native 点击 Job 的失败状态未纳入 CommandResult

**定位：** `src/bca/lite/vision.py` 的 `MaaVisionFacade.click()`。

当前代码调用：

```python
await self._submit(lambda: controller.post_click(*point).wait().succeeded)
return self._bridge.input_outcome
```

`post_click(...).wait().succeeded` 的布尔结果被丢弃。与此同时，`src/bca/lite/bridge.py` 在 `_click_frame` 开始时把 `_outcome` 设为 `rejected`，随后实际提交输入设为 `unknown` / 成功设为 `confirmed`；**但 `_capture_frame` 重新截图不重置上次的 input outcome**。

因此存在可复现序列：

1. 第一次真实 click 成功，Bridge 的 outcome 留在 `confirmed`。
2. 第二次重新截图并成功识别，获得新 Batch；此时 Bridge 的 outcome 仍是上一次 `confirmed`。
3. 第二次 Maa `post_click().wait()` 在进入 CDP Bridge 点击 callback **之前**失败，返回 `succeeded=False`。
4. Facade 忽略 False，读到旧的 `confirmed`；Coordinator 可能报告本次输入已确认，即使本次没有真正发出输入。

**要求：** 单次 native Job 结果必须与**本次** Bridge input outcome 对齐；前次状态不得决定本次命令。处理失败时保守且可诊断，不自动重放；如果输入是否触达无法判明，归 `unknown` 并退役运行组合。`confirmed` 只在当前点击确实得到对应 CDP 输入确认且当前 native action 的结果与之相容时返回。

建议最小修正路径（Codex 可选等价安全实现）：

- 在新动作开始前为本次输入建立清晰的状态边界（重置/代次标记；不要沿用历史 `confirmed`）。
- 保存并检查 `controller.post_click(*point).wait().succeeded` 的实际布尔值；出现不一致时拒绝以 `confirmed` 呈报。
- 覆盖 native click 前失败、callback 返回 False、callback 后异常、真实已确认、ACK 丢失，以及一次成功之后的第二次 native 提前失败。
- 保证每个失败路径都无自动重试、无第二次输入，且不破坏已验收的 `ObservationRef`、Bridge 时效与取消清理语义。

最重要的回归断言：**首次 confirmed → 新截图 → 第二次 native Job 失败且 Bridge.click 未调用时，第二次绝不可返回 confirmed，后续不得默认恢复/重放旧命令。**

## 四、其他跟踪项（不阻断本次小修）

- `ObservationCoordinator.execute_text()` 在入口先调用受信任插件同步 `parse_command()` 再进入命令门；按纯轻量插件契约可接受。之后需坚持插件不阻塞 owner loop。
- `execute_intent()` 对某些 native 异常目前直接抛出，不总是输出 `CommandResult`；LITE-03 CLI 应有统一异常呈现与终止状态，避免吞掉不确定输入。
- `1.950586Hz` 为有限受控图片测试。LITE-02.3 仍须真实 Edge、ROI/raw/DPR/字体、DOM oracle、至少 3 分钟与 120 次有效观察、CPU/RSS 和资源回收。
- `MaaFramework v5.16.1` 的私有 Destroy 仍受版本锁约束；异常隔离为 fail-closed 进程退役边界，不是资源自动恢复。

## 五、给 Codex 的下一轮开发指令

请先查看 `docs/lite/LITE-02.2_HANDOFF.md`、`docs/lite/PLUGIN_CONTRACT.md`、本审查文件及当前 `src/bca/lite/vision.py` 与 `bridge.py`。

**任务优先级 1：** 修复“前次 confirmed + 本次 native Job 失败 → 本次误报 confirmed”的输入状态归属问题。编写原生 Job 失败注入与 Bridge 回调次数证明，用单独提交保留全部原始测试证据；不要借此重构整个 Coordinator。

**任务优先级 2：** 定向复跑 `tests/lite` 和全仓库离线回归，检查 mypy/Ruff/build，记录异常及环境。更新 `LITE-02.2_HANDOFF.md` 增补修复节，提交至 `lite` 并交架构主会话快速复核。

**并行准备：** 按 `docs/lite/LITE-02.3_STABILITY_PLAN.md` 准备 LITE-02.3 自建 Edge 视觉测试页、OCR/模板图、不同缩放及独立进程内存指标方案。待上述小修完成确认后开始 LITE-02.3 集成实现。

README 和 `BCA_PROJECT_CONTEXT.md` 的 LITE-02 **整体**验收状态保持不变；不得直接把 02.2/02.3 冒充 LITE-02 整体 Accepted。`main` 保持不变。
