# BCA-lite · LITE-02.2 P1 定向复核及正式子阶段验收

- 复核日期：2026-11-26
- 仓库：`Itsukiii/Browser-CLI-Agent`，分支 `lite`
- 远端 HEAD（复核时）：`0dcb6debda2a15c69fb6ec8d1d75d7198bead61c`
- 修复提交：`b7118e3dc2fc94cadbe914b2787962534524ba9e`
- 实际远端归档提交：`0dcb6de`。交接消息所称 `9059b34` 未在当前远端查到，按当前 Git 提交图为准。

## 决议

**LITE-02.2 子阶段 Accepted；允许启动 LITE-02.3。** 此决定基于审阅远端源码、测试实现、原始 JSON 和运行记录；架构会话并未在用户的 Windows / Edge 机器独立重跑测试。**整个 LITE-02 尚未 Accepted**，需待 02.3 全部验收。

## P1 缺陷复核

先前 `MaaVisionFacade.click()` 忽略 `post_click().wait().succeeded`，而 CDP Bridge 历史 `input_outcome` 可能仍是 `confirmed`，导致不同次动作结果串用。

现行实现：

1. `CDPBridge.authorize(ref)` 必须经过身份、来源、时效和绑定检查，成功后设置 `input_outcome = "not_attempted"`，形成新的动作边界；截屏本身不会伪造一次新动作的确认。
2. Facade 消耗一次 `RecognitionBatch`，等待本次 Maa native click Job；调用 `finish_native_click(bool(succeeded))` 将 Job 结果与本次 CDP 确认合并。若 Job 抛异常（包括等待阶段）则保守归并 `False`，取消会先等待原生清理后失效。
3. **只有 native Job succeeded、本次 CDP `confirmed`、Bridge `connected` 三条件同时成立，才返回 `confirmed`。** 其余情况一律 `unknown`，清除授权及最后帧并阻断继续输入；不会重试不确定动作。
4. `Coordinator` 将 `unknown` 传播到结果并退役组合；后续命令无法重新用旧授权发送输入。

## 核查的回归与证据

- `tests/lite/test_click_outcome.py`：7 个注入场景（pre_failed、pre_exception、false_success、callback_false、ack_lost、post_failed、post_exception）+ Coordinator 传播 + 两次合法新动作/单次授权 = **9 passed**。
- `final-targeted/click-pre_failed.json`：先前动作成功后，第二次失败返回 unknown，日志累计 callbacks=1 / inputs=1（两者仅属于第一次）。
- `final-targeted/coordinator-native-pre-failure.json`：第二次 callback=0、输入累计=1，返回 unknown，后续命令被阻断。
- `final-targeted/click-false_success.json`：native 声称成功但无回调也拒绝确认。
- `final-targeted/confirmed-new-actions.json`：两次不同截图、两次 native/CDP 一致确认，实际输入恰好两次；已消费批次/旧授权不能重复输入。
- `docs/evidence/LITE-02/02.2-click-fix/targeted.txt`：**9 passed / 0.98s**。
- `lite.txt`：**114 passed / 5 skipped / 23.70s，exit_code=0**。
- `offline.txt`：**876 passed / 50 skipped / 61.41s，exit_code=0**。
- `mypy.txt`：99 个源码文件通过；`ruff.txt`、format、build 日志通过。

上述注入使用真实 Maa native/受控 Provider 配合测试替身；**不是**本次真实 Edge 传输故障再验收。LITE-01 的真实 Edge 传输证据仍有效。

## 02.3 接续约束

1. 实际 Edge：CDP 截图 → Maa Template/OCR → BusinessPlugin/Coordinator → 视觉唯一候选 → 单次授权点击 → DOM oracle 复核；测 DPR、原生缩放、raw/nonraw、ROI、字体变化、歧义、旧回合/失效。
2. 真实环境 >=3 分钟且 >=120 个有效观察周期；报告完成时刻、有效 Hz、median/p95、CPU/RSS/PrivateBytes/系统剩余内存、关闭前后资源状态，不用受控图像 1.95Hz 作为 Edge 结论。
3. 依 `docs/lite/LITE-02.3_STABILITY_PLAN.md` 独立复跑历史 OpenCV decode、Maa 单独和同进程混合顺序，保留 Windows access violation 的失败现场；不把此前独立 92 项重跑通过等同于已归因。
4. 清洁安装/wheel 异 cwd、资源来源/模型哈希、销毁异常/stop-failure/取消与 unknown 行为继续作为发布前门槛。
5. 02.3 实现和证据按单阶段交付。Codex 负责实现/测试/提交；主架构会话负责最终复核。当前 `README.md` 与 `BCA_PROJECT_CONTEXT.md` 的 LITE-02 整体状态暂不更新，待 02.3 完成后同步。

## 结论

**LITE-02.2 Accepted，LITE-02.3 可开工；LITE-02 整体仍在推进中。**
