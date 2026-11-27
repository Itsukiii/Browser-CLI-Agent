# LITE-04.2 · 性能偏差第二次架构裁决（2026-11-27）

> 审查基线：`lite@97f6532425c378eb20c908133d0d7b47dffe8111`
> **决定：04.2a/b 视觉准确性实证认可；LITE-04.2 尚未 Accepted；04.3 继续冻结。**
> 本轮只批准受控性能诊断及安全等价优化实验；原设计 ≥1Hz、来源时效、模型校验、DOM 不参与业务判断、native+CDP 双确认及一次授权均不放宽。

## 1. 证据核对

- `docs/lite/LITE-04.2_VALIDATION_HANDOFF.md`、`LITE-04_DESIGN_DEVIATION.md`、`quiz.py`、`quiz_edge_validation.py`、`test_quiz_vision.py`、`_native_vision.py`、仓库内 summary/性能 JSON、日志。架构会话未在本机 Edge 重跑。
- `b-blind-01/summary.json`：DPR 1/1.5/2 × raw/nonraw × seeds 9173/60127/88219 × 10 数字 = **180/180 正确 MATCHED，0 错误 MATCHED，180 来源有效**；包括 normal/bold 两套自制字形。`b-zoom` 真实桌面缩放 **30/30**，六项人工图像破坏均拒绝写入。此结论限定受控页面/资产与测试矩阵。
- `quiz.py` 使用一张 Maa 截图 67 个请求（题号/倒计时/分数 3 OCR，题目/选项 5 only_rec + 5×10 数字模板、9 选中态/确认模板），数字 OCR 与模板不一致、模板首二 margin <0.15 均拒绝，不从 DOM/历史值填充。
- `c-comparison.json` 的四组 ≥60s：原窗口 raw 59 有效 /60.7775s = **0.9708Hz**，native median/p95 **0.6715/1.2320s**；960×640 raw 0/61.546s（24帧因2s时效全部过期，native median 2.25895s）；原窗口 nonraw 0/61.518s（时效过期且确认模板漏匹配，native median 2.2170s）；两核亲和性 0/60.589s（native median 2.0274s）。四组无错误 MATCHED，released=true、pending=0/reader=false。
- CPU 工作 PID 平均 4.784、4.171、4.065、1.791 个逻辑核（含生命周期采样，采样配置不同不可直接比较）；性能跨进程波动尚不能归因于图片大小、CPU亲和性或单一原生模块。`offline.txt` 933 passed /74 deselected；页/fixture CLI 10 passed /1 skipped；干净 wheel、模型哈希、资源释放与静态检查通过。

### 1.1 测量器对有效频率的扰动（新增重要发现）

`tests/lite/quiz_edge_validation.py:observe()` 的 `total=end-start` **只覆盖一次 `facade.recognize` 与 `plugin.observe`**；而每次调用在它之后仍执行 `oracle()` 的第二次 CDP 查询、保存原始 PNG、将 Maa BGR 转换成另一张 PNG、序列化 67 项完整 recognition/requests 并追加 `rows.jsonl`。这部分在真实60s循环 `elapsed` 内，**但不计入 `total`/capture/native/parse**。因此首组0.9708Hz不能独立归因到产品管线；同时后三组 native median 已超过2s，测量器扰动不足以解释其全部故障。

## 2. 裁决：先排除测量扰动，再做请求合并实验

### P0 · 同条件双轨性能基线（优先执行）

1. 保留原始“全证据”用例原封不动；另加 **lean/production-like** 计时模式，在热循环里不逐帧写PNG/完整JSONL、不逐帧调用DOM oracle、不打印日志。只保留原始frame_id、monotonic起止、Maa `RecognitionStatus`、signature/revision、source_current、expired、请求总时长和bounded统计。有限采样图像/完整 native JSON 在**独立诊断轮次**存档，不得后台积压无界写盘。
2. 计时覆盖**真正从一次观察入口到下一次观察入口**的整段时钟，包括如有的Coordinator/CLI开销；`valid_hz` 使用有效且未过期的完整业务观察数/连续时长，不用配置频率或 Job.succeeded。准确性通过现有独立盲测证明，lean 模式至少保存有限帧和最后页端 oracle 核验，不得无依据计数假成功。
3. 同一隔离 Edge、同一实际窗口与ROI/模型、固定seed和真实10秒计时，串行执行**lean → 详细证据 → lean**，每次≥60s，记录温度/系统负载等已知干扰、窗口尺寸、DPR/raw、PID、CPU/RSS/PrivateBytes、每次recognize起止与总有效Hz；无其他 Maa/Edge压测并发。若 lean 已稳定≥1Hz，仍须确认不同支持配置、足够余量与重复性，不能只用一次靠边通过掩盖高p95。
4. 不调整原有 `max_frame_age=2`、模板阈值或 OCR 仲裁；`expired`、NOT_FOUND、AMBIGUOUS 必须从 valid 中剔除。测试诊断工具专用开关不进入正式插件路径。

### P1 · 67次 Native Job 成本剖析

1. 在相同**单张Maa图像**重放 `NativeVision.recognize`，分别累计3次多数字段OCR、5次单字 only_rec、50次数字模板、9次选中态/确认模板的 wall-clock mean/p50/p95/占比；再在真实 Edge 用轻量计数复核。不把单张图的识别耗时称为带CDP的完整频率。
2. 将 native 任务提交/等待、模板读取与ROI面积、模型推理/序列化成本分开记录可以可靠取得的部分；拿不到的内部时段明确为未知。重点判断为何较小960×640与nonraw独立进程明显变慢，至少重复两次并控制环境变量和实测图像大小。
3. 性能优化假设必须用同图 A/B/C 方案对照，前后必须覆盖数字0..9、1↔7与6↔8、模板 margin/冲突/歧义/缺失、安全拒绝及按位置可定位的唯一可见目标。

### P2 · 批量模板候选的有界技术验证（批准实验，不预判速度）

- A：原方案5字段×10模板=50个JTemplateMatch，作为正确性/性能基准。
- B：**每个数字一次**，用覆盖5个单数字位置的单次ROI执行 JTemplateMatch（`unique=False`），最多10个Job；必须经真实 Maa v5.16.1 证实 `filtered_results/all_results` 提供足够**完整的所有命中坐标**，再按截图坐标严格归属到5个互不重叠的字段。每字段唯一匹配、其他数字排他、全部近似候选首二margin、OCR一致；任何字段有多个匹配或来源不确定立即拒绝。
- B 的ROI变宽且跨大量空白/文字，搜索面积增加，**不保证比50个窄ROI更快**；也不得以一个 best 匹配结果代表五个字段。优先做样本级计时和原生候选完整性验证，失败即撤销此方案，不进入生产逻辑。
- C：若 Maa binding 能在一个多模板Job的原生详情中明确区分**模板身份**，才允许对比每字段一次的多模板方案；原始接口尚无可依赖模板ID，不能猜测某个best属于哪个数字。不允许依据 DOM、缓存答案或重写图像匹配器跳过 Maa。
- 仅在实证收益成立、准确性和拒绝语义完全等价时，才可改动生产 `QuizPlugin.plan/observe` 与必要的内部 DTO；保持公用 Bridge/Facade/Coordinator 和单图精确ObservationRef不变。

### P3 · 另立窗口缩放/确认模板问题

原生窗口 nonraw 的确认模板首帧约0.893674，低于冻结的0.9，四个选项模板约0.999。需要单独研究二次重采样、模板尺度/渲染、几何ROI；可采用新资产/策略，但必须经校准与独立盲测。**不得为了本次回归直接降阈值**，也不得将该配置假称已支持。

## 3. 验收出口（不改既有门槛）

- 在本轮拟正式支持的 **raw/nonraw、DPR和真实缩放** 组合上，有真实Edge新帧、完整业务MATCHED、来源有效且未超龄的持续有效频率 **≥1Hz**（每次连续≥60s；建议对关键基线至少重复两轮，并留余量）；区分生产近似模式与详细证据模式的报告口径。
- 任何优化都需重新执行独立未调参的**≥180个数字样本**（覆盖两种受控字重，全部0..9、DPR/raw矩阵）、真实缩放、负例，满足**0错误MATCHED、≥95%完整可信识别**；同时原有完整业务识别、选择态/确认位置、分数负号/多位与可见轮次正确。
- 正常/失败时 native 完整 CloseReport、临时资源延续至Destroy、原Target保留与provider/CDP零pending；干净wheel、模型哈希、lint/mypy/build及全量离线/既有fixture回归继续通过。
- 原有60s全证据测试和新的lean性能测试必须并存，并在报告中明确测量模式、数据损失边界、原始证据路径与比较结论；不通过把未达标测试skip或改阈值来获得Accepted。
- 交付 `docs/lite/LITE-04.2_PERFORMANCE_HANDOFF.md`，证据存新目录 `docs/evidence/LITE-04/04.2-performance/`，包含基线配对、逐请求profile、替代策略候选完整性与耗时、优化后独立盲测/持续运行与每轮归因；保留本轮四组失败证据。

**04.3 解锁条件：** 上述真实安全性与有效频率通过、报告复核后，架构主会话正式标记 LITE-04.2 Accepted。任何未证实的批量模板方案不得直接连入真实自动点击。

## 4. 协作与子Agent

遵守根目录 `AGENTS.md` 及 `docs/md/BCA-LITE_MASTER_HANDOFF.md` §16 的软分流：Explorer可并行查 Maa 绑定及性能报告；Tester可独立设计复现和盲测；Native/Bridge的关键决定由高能力主Agent/Reviewer复查。**真实Edge/Maa的共享集成实验串行**，避免前一轮证据中出现的并发干扰。

当前本机观察到 `model`、`reasoning_effort` 覆盖（`fork_turns="none"`）、无 `agent_type`；Multi-Agent V1/V2尚未确认。**不得把软分流写成已成功创建子Agent。** 本轮继续允许不委派，不预设硬角色模型；记录实际使用情况。High推理强度可用于用户后续自愿A/B实验，但不当作本阶段必须前提。

**最终裁决：批准 P0/P1 诊断和 P2/P3 安全等价优化实验，不放宽有效1Hz验收。04.2尚未 Accepted，04.3仍待放行。**
