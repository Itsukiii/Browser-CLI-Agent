# LITE-02 设计架构评审 · 2026-11-24

**决定：设计 Approved，可依次启动 LITE-02.1 → 02.2 → 02.3。** 本批准仅针对 `docs/lite/LITE-02_DESIGN.md` 的设计方向，非功能实现验收。

## 已确认的五项核心决策

1. **单插件、单 native worker、一个 Facade 持有 Maa 对象。** Application 保有 Browser Session/Provider/Bridge；Facade 管理 Controller/Resource/Tasker、Job 和确定性清理。worker 不执行 CDP owner-loop 阻塞等待。
2. **显式单帧来源的直接识别优先。** 一次 `post_screencap()` 形成唯一 `ObservationRef`；相同 BGR 图像用于多个 `Tasker.post_recognition(JTemplateMatch/JOCR)`。单节点 Pipeline 两种视觉算法须真实测试，但其内部多截图行为不能悄悄关联到同一观察令牌。
3. **轻量业务插件 Protocol。** `plan/observe/format_state/parse_command/resolve/close` 只处理业务语义；宿主独占 Maa 和 CDP，避免新的通用插件框架。
4. **三个相互独立的有效性维度。** `ObservationRef` 是图片/Target/几何/时间来源；`semantic_signature` 是内容去重；`interaction_revision` 是可视觉核验的动作回合。缺回合证据时不进行跨观察写操作。
5. **一把 asyncio 门协调生命周期。** 观察→识别→决策→精确授权→单步操作→后置观察不允许其他命令替换引用；失败/取消/unknown 保守停止；通知仅有界轻量增量，不重建 EventBus/Runtime。

## 02.1 实现前必须落地的接口验证

- **实际识别详情验证：** 以安装的 `maafw==5.16.1` 代码/真实 DLL 测量 `Tasker.post_recognition(type, dataclass, image)` 的 `TaskJob.get()`、懒加载 `TaskDetail.nodes`、`RecognitionDetail`、`hit`、negative Job.failed/status 语义、ROI 坐标是否全图绝对坐标。
- **正确的结果分类：** 有效无命中才是 NOT_FOUND；native/模型/详情错误归 ERROR；多候选只有在业务要求唯一且无法区分时才是 AMBIGUOUS；决不能用 `best_result` 在歧义场景自动点击。
- **资源与许可证：** OCR det/rec/keys 必须显式指定可信来源、版本、校验哈希及分发许可证。按安装后真实资源布局验证 model path；不能下载未知模型后直接随 wheel 发布。
- **归一结果的来源保护：** Maa 结果须关联发起识别的 CaptureContext，完毕后读取并验证当前 Bridge Ref；只复制可解析、不可变的候选和坐标，不能在 Tasker Destroy 后读惰性结果。插件不能自行构造授权对象。
- **多种时间边界：** 一次截图完成后 OCR 可能耗时超过 `max_frame_age`，识别结果可以只读展示历史观察，但不授权写动作；执行前必须刷新观察。禁止将 `Job.wait()` 视为可强制取消。

## 02.2 / 02.3 工程约束

- `Coordinator.refresh` 每次实际拍摄新帧；后台 1Hz 以完成的有效识别计数，任务繁忙不堆积 tick；输入不饥饿，订阅者慢不能持有观察门。
- 所有写入目标必须来自当前 batch 实际唯一视觉候选且在 Maa 图像坐标空间内，不能由插件猜测 CSS/DOM；bridge 严格一观察一步点击。
- `ReadIntent` 不缓存冒充即时查询；同一回合多步骤由 LITE-04 业务协调实现，LITE-02 只验证单步闭环。
- 保留真实负例、模糊/歧义样本、字体/缩放/ROI、缺模型、关闭竞争、wheel 异 cwd 等证据；完整 02.3 至少 3 分钟与 ≥120 有效观察，记录 RSS、CPU、median/p95。

## 子阶段验收门

| 阶段 | 最少可验证结果 |
| --- | --- |
| 02.1 | Maa native TemplateMatch 和 OCR 两条 API 在真实图像上完成；模板 ≥10 正/≥10 负、0～9、负号及多位数样本；模型校验与生命周期证据 |
| 02.2 | 薄插件 DTO/Protocol、状态去重、真实 refresh、串行操作来源、错误恢复、取消和重启边界 |
| 02.3 | 真实 Edge 截图 → Maa 视觉 → 唯一目标位置 → CDP 授权点击 → DOM oracle；ROI/raw/缩放/字体/失效与 3 分钟长期观察；wheel 资源加载 |

## 开发纪律

Codex 在 `lite` 分支实施并形成 `LITE-02_HANDOFF.md` 和原始证据；接口发生实测偏差要先更新设计差异，再改实现或验收条件。LITE-02 通过全部子阶段并由主会话审核后，才进行正式 Accepted 和下次 README/PROJECT_CONTEXT 更新。`main` 保持历史基线。
