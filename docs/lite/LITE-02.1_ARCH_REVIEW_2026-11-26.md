# BCA-lite / LITE-02.1 架构主会话源码复核

**复核日期：** 2026-11-26  
**代码基线：** `lite@46dc5858c25ef80b077ef1bc8a9b99db5a65938e`  
**实现提交：** `3316abb`；**交接提交：** `46dc585`  
**结论：** **LITE-02.1 子阶段 Accepted；允许启动 LITE-02.2。** LITE-02 整体仍未 Accepted。此结论为 GitHub 源码、测试代码、提交证据的独立静态核对；未在用户 Windows/Edge 上自行执行测试。

## 1. 实际检查范围

- `src/bca/lite/{vision.py,_native_vision.py,vision_types.py,vision_resources.py,bridge.py}`
- `tests/lite/{test_vision_native.py,vision_fixture.py}`
- `docs/lite/LITE-02.1_HANDOFF.md`、`docs/lite/models/{README.md,ppocr-v3-en.json}`
- `docs/evidence/LITE-02/02.1/{README.md,lite-native-final.txt,offline-with-model.txt,legacy-recheck.txt,offline-diagnostic.txt,memory-after-diagnostic.json}`
- 原始示例：`final/ocr--305.json`、`final/ambiguous-missing.json`、`final/native-missing-model.json`、`final/source-expired.json`、`final/destroy-retry.json`、`final/TemplateProbe-negative.json`。

## 2. 已通过的代码/协议检查

1. **Native 所有权：** `MaaVisionFacade` 单 `ThreadPoolExecutor(max_workers=1)`；Controller、Resource、Tasker 的构造、`.wait()`、详情读取、私有 v5.16.1 Destroy 均在工作线程完成，CDP owner loop 不做同步 Native Job 等待。Bridge/Browser Provider 仍由上层 Application 管理。
2. **取消与排空：** `_submit` 对 Executor Future 采用 shield/等待，不把外层 asyncio Cancelled 当作 Native 已终止；`aclose()` 共享清理 Task。Destroy 注入异常后能返回 `released=false`、持有依赖与 worker，复用同线程重试；真实路径的资源释放次序正确。
3. **原生识别确实运行：** `JTemplateMatch`、`JOCR` 使用 Maa v5.16.1 dataclass 参数，`TaskDetail.nodes` 及各项识别详情在 Native 对象存活时归一化。模板、OCR 的直接识别和单节点 Pipeline 均有真实 DLL 证据。
4. **结果分类：** 无命中且详情完整的 `Job.succeeded` 才能归 `NOT_FOUND`；缺模型被显式前置校验阻断为 `ERROR`；候选多而 `unique=True` 归 `AMBIGUOUS`；完整失败/结果结构异常归 `ERROR`。不能用 `best_result` 冒充唯一目标。
5. **截图来源与坐标：** 每次 `recognize()` 只拍一张真实 Maa screenshot；各 RecognitionRequest 共享同一 `CaptureContext`/`ObservationRef`。ROI 框经测试为 Maa 返回图像全图像素，避免二次叠加 ROI 原点或 CSS/DPR 转换。超龄但未替换的结果可只读显示，Bridge 仍拒绝旧观察授权。
6. **资源控制：** Bundle 采用显式绝对路径，模板验证路径/文件和尺寸，OCR 模型 manifest 的大小及 SHA256 在加载前验证。模型来源、许可证与固定修订写入文档；没有自动下载或隐含 wheel 分发。
7. **分阶段边界：** 当前只建立识别/资源能力，不将测试用 Pipeline 结果虚构为应用可授权动作，不提前做业务插件/持续轮询/CLI。

## 3. 测试证据核验

- `lite-native-final.txt`：**82 passed / 5 skipped**，21.89s。5 个 skipped 为需要真实 Edge 端点的测试；包括报告所述 **58 个新增** native/图像测试。
- `offline-with-model.txt`：全仓库离线 **844 passed / 50 skipped**，77.79s。测试轮次与环境单独记录，不与 live 证据混淆。
- 固定图片真实 OCR：数字 `0..9`，负数 `-1/-20/-305`，多位数 `12/345/6789` 的 full/ROI；`ocr--305.json` 实际显示 MATCHED 且文本 `-305`。
- 模板正负样本、歧义候选、model missing、expired source、Destroy retry、正负 Pipeline 各有原始 JSON；`TemplateProbe-negative.json` 显示失败后多次截图而 `authorized_batch=false`，来源边界处理合理。
- mypy、Ruff、打包、wheel 异工作目录验证已在交接日志提供，不把使用原 `.venv` 依赖的异目录测试当成全新安装环境验证。

## 4. 须带入 LITE-02.2 / 02.3 的风险与行动

### P1-A：Tasker 停止失败的 Destroy 安全门槛

`src/bca/lite/_native_vision.py::NativeVision.close()` 在 `post_stop().wait()` 返回 `stop_status="failed"` 后仍继续执行 `MaaTaskerDestroy`。当前单 worker 串行且通常所有公开作业已 wait，因此这不是已观察到的崩溃；但失败状态是否保证内部作业已静止尚无证据。

**要求：** 在 LITE-02.2 集成时做 fail-closed 处理或给出 v5.16.1 真实 API 证据证明失败可安全销毁；增加 stop-failure 注入测试，不能只注入 Destroy-before-release。若 native Destroy 结果不确定，不能盲目重复调用相同指针以制造二次释放风险。检查 `CloseReport` 的 `released`、`stop_status` 与 native handle 状态一致。

### P1-B：历史 OpenCV access violation（尚未归因）

归档 `offline-diagnostic.txt` 显示旧 `bca/plugin_sdk/vision/decode.py` 的 4096×4096 边界用例在诊断复跑发生 Windows access violation。`legacy-recheck.txt` 的 **92 passed** 只说明独立复跑正常；内存快照显示运行后可用物理内存较少，但**不能据此认定内存不足是原因**。

**要求：** 02.2 可继续开发；02.3 整合测试加入混合 Native/OpenCV 进程的内存 RSS/commit/系统内存记录、独立进程隔离复跑以及可重现日志。不要隐藏异常，不用降低测试门槛代替定位。若当前 BCA-lite 不使用 legacy Vision 解码，需清楚区分“旧测试进程稳定性”与“新 Maa 视觉链路稳定性”，但发布前仍应评估其影响。

### P2：边界与后续验证

- `MaaVisionFacade.aclose()` 既释放其自有 Native 资源又关闭其借用的 Bridge：需要明确这是**上层对 Facade 的独占授权/委托关闭**。关闭失败时不可继续关闭 Browser Providers。Coordinator 必须保持此拥有权及关闭次序。
- 取消 `recognize()` 会退役 Facade/Bridge，但调用方仍必须在 `finally` 中执行并核对 `aclose()`；02.2 的 Coordinator 不能把取消视为自动释放完成。
- `source_current` 和 `expired` 均仅描述识别完成当时状态，不等于最终动作许可证。02.2 的点击必须重新通过 `bridge.authorize(ref)`，并验证视觉唯一目标与业务语义。
- 本阶段模型与阈值来自受控 fixture，不证明真实浏览器字体；02.3 实测 Edge、DPR、raw/ROI、频率、资源与 RSS。真实 wheel 全依赖干净安装待 02.3。

## 5. 给 Codex 的下一步

**允许开始 LITE-02.2。** 按已批准 `docs/lite/LITE-02_DESIGN.md` 和 `docs/lite/LITE-02_CODEX_DEVELOPMENT_HANDOFF.md` 开发纯业务 `BusinessPlugin`/不可变 DTO、应用级 `Coordinator`、变化签名去重、`refresh` 必重新截屏、稳定 1Hz 有效观察与单步视觉目标授权。

务必增加覆盖：
- 同内容不同截图不刷屏，NOT_FOUND/AMBIGUOUS/ERROR 与恢复状态通知，动态数据的业务签名和 interaction_revision 不混同；
- 同一目标观察/点击操作的唯一入口锁，取消/停止/重复 close、输入不确定结果阻断；
- 只读命令强制新截图，写命令拿当前同批次唯一识别目标、当前 ref、有效业务 revision；
- 上述 P1-A 的 Tasker stop failure 路径，以及 OpenCV 异常的后续可复现调查安排。

完成后提交 `LITE-02.2_HANDOFF.md` 和原始证据，先申请子阶段审查，再进入 02.3；**本次并未对 GitHub 进行任何源码或文档修改**。
