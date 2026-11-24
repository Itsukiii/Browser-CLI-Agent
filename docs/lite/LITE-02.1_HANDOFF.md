# LITE-02.1 · Maa 原生视觉与资源适配交接

2026-11-24。**实现与原生验证已交付，提交架构审查；不是 LITE-02 正式 Accepted。** LITE-01 已由架构主会话正式 Accepted。02.2/02.3 未实现。

## Git 与范围

- 按用户指令 `git pull --ff-only origin lite`，从干净工作区快进至 **a8c67e0**。
- 已完整阅读 LITE-01_ACCEPTANCE、LITE-02_DESIGN、LITE-02_DESIGN_REVIEW、LITE-02_CODEX_DEVELOPMENT_HANDOFF、BCA_PROJECT_CONTEXT；以正式审查补充意见约束实现。
- 代码、模型清单、测试、原始证据提交 **3316abb**。本报告独立归档，文档提交见 `git log --oneline -- docs/lite/LITE-02.1_HANDOFF.md`。
- 全部工作在 lite；未修改 main、未推送远端、未改总纲/README 的阶段验收状态。
- 只新增单帧视觉适配、固定版本 native owner、资源校验和测试；没有持续观察、BusinessPlugin、CLI 或动作执行器。

## 源码与公开接口

| 文件 / 接口 | 行为与责任 |
| --- | --- |
| `src/bca/lite/vision.py` / MaaVisionFacade(bridge, resources, raw_size=True) | owner loop 构造，独占一个 ThreadPoolExecutor worker，借用已绑定并启动的 Bridge/Providers |
| `await start()` | 校验 Python/native v5.16.1；加载 Bundle/显式 OCR model；连接 Controller，绑定 Resource/Tasker；部分失败自动关闭 |
| `await recognize(tuple[RecognitionRequest,...])` | 一把实例锁覆盖单次 Maa 截图、读取精确 ref、全部直接识别和结果物化；每次调用实际新截图，不提供缓存替代 |
| `await aclose() -> CloseReport` | 拒绝新入口、排空 native、停止 Tasker、按 Tasker→Controller→Resource 销毁；最后 bridge.aclose / executor.shutdown；不关闭借用的 Browser providers |
| `vision_types.py` | 冻结 TemplateRequest/OCRRequest、Candidate、CaptureContext、RecognitionResult/Batch、RecognitionStatus、CloseReport；无 native 惰性对象流出 |
| `vision_resources.py` | ResourceSpec 指定绝对 Bundle；OCRModelSpec 指定模型目录/来源清单；逐文件大小与 SHA256 验证，禁止 Bundle 隐含 OCR 模型 |
| `_native_vision.py` | 真实 dataclass 参数转换、TaskJob/节点详情物化、候选解析；隔离 Maa untyped API 和固定版本私有 Destroy，检查 worker 线程 |
| `bridge.py` 增量 | 只读 `binding -> (page_id,session_id,generation)` 和 `max_frame_age` 属性；不改原单次授权/坐标/输入行为 |
| `tests/lite/vision_fixture.py` / `test_vision_native.py` | 合成已知像素经实际 Controller→Bridge→Frame 路径；58 个新测试；不作真实 Edge 证据 |

导入示例（宿主已独占并启动 Bridge）：

```python
from bca.lite.vision import MaaVisionFacade
from bca.lite.vision_resources import OCRModelSpec, ResourceSpec
from bca.lite.vision_types import OCRRequest, TemplateRequest

facade = MaaVisionFacade(bridge, ResourceSpec(bundle_absolute_path, model_spec))
try:
    await facade.start()
    batch = await facade.recognize((TemplateRequest("button", "button.png"), OCRRequest("number")))
finally:
    close_report = await facade.aclose()
```

调用者必须检查 close_report.released/errors；失败时保留 Facade 并在同一 worker 重试 aclose，不能销毁外部 providers 后丢弃存活 native 对象。Bridge 和 Providers 必须由该组合独占；本阶段没有向插件提供 Controller/Tasker 入口。测试使用私有 `_submit` 的 Pipeline 探针不是公开应用 API。

## Native 生命周期和取消

- Controller/Resource/Tasker 创建、作业等待、读取结果、销毁都在一个专用 worker。Maa 内部 callback 线程仍通过 Bridge 回到 CDP loop；不声称 callback 也运行在该专用线程。
- 原生 `.wait()` 不在 loop；取消只撤销 Bridge、持有并 shield 等待实际工作结束，然后传播 CancelledError，不强杀线程。重复取消/close 共享清理任务。
- 正常 close 在排空后调用 post_stop；取消已使 Controller 不可用时，Tasker.inited 可变 false。确认其 idle 后不再投递无效 stop，CloseReport.stop_status 为 `not_needed_idle_disconnected`，再执行 Destroy。
- 正常释放次序为 Tasker→Controller→Resource，清空各 `_handle` 防析构双释放；绑定引用与回调持有者一直保留到 Destroy 返回。
- 注入 TaskerDestroy 异常后返回 released=false，保留 Controller/Resource 与原 worker；恢复后 aclose 在同线程重试成功。没有“失败也报 CLOSED”的假清理。
- 若 native 永久卡死，线程不可强杀；保留任务/资源等待是当前边界。不是进程隔离或长期 RSS 证明。

## 实测 API / 结果语义

1. `post_recognition("TemplateMatch", JTemplateMatch(...), image)` 与 OCR/JOCR 实际运行；dict 不作为参数。图像为 Controller 返回的 BGR uint8。
2. `TaskJob.get()` 的 TaskDetail.nodes 惰性加载在 worker 内完成；读取并复制 all/filtered/best、hit、reco_id、job 状态、raw JSON。候选 box 是 list，顶层 recognition.box 是 Rect；公开候选转换为不可变 tuple，不在 Destroy 后回读 Tasker。
3. **直接识别正负例均 Job.succeeded**。正常无命中有完整详情、hit=false、空 filtered/best，归 NOT_FOUND。TaskJob 缺详情、结构异常或执行未成功归 ERROR。
4. **缺 OCR 模型也可能 succeeded/hit=false/空详情**，无法单凭此结果区分合法无文字。Facade 在识别前强制显式模型校验/装载；无模型直接 ERROR。模板缺失、损坏、越界路径或大于 ROI 同样先拒绝，不能当 NOT_FOUND。
5. 两种算法 ROI 返回框均为 Maa 全图绝对像素；不再加 ROI 原点。所有候选检查有限分数、整数框、图像边界；不进行 CSS/DPR 二次换算。
6. unique=True 且有多个 filtered 候选时 AMBIGUOUS；unique=False 保留多候选 MATCHED。best 仅诊断，不自动选择目标。模板和 OCR 双候选均有实测。
7. Pipeline 正例 Template/OCR 均实际 post_task、截图一次。负例 timeout=100ms 后失败，可截图重试，返回节点 recognition=None。本阶段 Pipeline **不生成可授权 Batch**；不能将最后一个 ref 套给整条任务。

这三处实测差异已写入设计实施补充与失败日志；没有降低原有验收要求。

## 来源与时效

CaptureContext 持有原始 ObservationRef 对象、固定 binding、Maa 图像尺寸及不可变 BGR bytes；image 属性返回 bytes-backed ndarray，不能 setflags(write=True)。同一次截图的所有请求使用该图，不重新截图。

识别完成后再次核对 Bridge.observation 对象身份；换绑、外部替换或关闭使全部结果标 ERROR / source_current=false。仅超龄但来源未变时保留 MATCHED 等历史只读结果、expired=true；真实 Bridge.authorize 仍拒绝过期引用。两个标志只描述完成时状态，不是对未来点击的授权。02.2 将继续在业务门内刷新和协调；这里没有语义回合、去重或写动作接口。

## 模型、素材与阈值

PP-OCRv3 en_us，MaaCommonAssets commit `dabcd4681ac990dc4361de26416d986abd80e4aa`；det/rec/keys 的来源、许可文本、大小、SHA256 与显式下载命令见 [模型说明](models/README.md)。实际目录 `.maa-models/ppocr-v3-en` 被 Git 忽略；运行时绝不自动下载，模型不打入 wheel。

480×240 白底 fixture、seed=20261124 的 36×28 随机模板、Pillow 12.3.0 Aileron Regular 48px 数字，都是受控输入。字体官方发布许可和来源在模型说明。模板阈值0.9用于精确同尺度图（正例 score=1）；OCR阈值0.3，最终输出候选最低分约0.513717。此校准仅涵盖本 fixture，不沿用旧 RMSE 0.96，也不声称适用于真实网页字体/缩放。

## 测试结果

原始目录：`docs/evidence/LITE-02/02.1/`；复现命令与全部失败轮次见其 README。最终 `final/` 记录正负样本 PNG、结构化结果和生命周期诊断。

| 验证 | 结果 |
| --- | --- |
| 模板 | ≥10 正例不同位置、≥10 负例不同文字，每例 full/ROI，共40次直接识别；框与标签一致；额外双候选/损坏/缺图/小 ROI |
| OCR | 0～9、-1/-20/-305、12/345/6789，各 full/ROI 共32次，文字全部一致；额外空白、expected过滤、双候选、only_rec |
| API | Template/OCR 的直接识别和 Pipeline 正负例；缺模型 native 原始详情；全部真实 v5.16.1 DLL |
| 来源/生命周期 | 同图多请求、并发批次串行、绑定/引用替换、超龄授权拒绝、取消截图/识别/启动、重复取消关闭、部分加载失败、销毁异常重试、5轮正常启动关闭 |
| lite 集合 | **82 passed / 5 skipped，21.89s**；含58新增、24原有 native/桥接测试；Edge未启用 |
| 全仓库离线且显式模型 | **844 passed / 50 skipped，77.79s**；兼容性证据，不替代新增视觉验收 |
| 不指定 OCR 模型 | **36 passed / 22 skipped，2.35s**（仅新增测试文件）；显式 skip，不下载 |
| mypy / Ruff / build | strict 96源码文件通过，Ruff/check format通过，wheel/sdist成功 |
| wheel 异 cwd | 独立 target 安装后从异 cwd 导入、核对实际包路径并验证模型；复用 .venv 依赖，完整新环境/包内 fixture 验证留02.3 |

**异常轮次不隐去：** 另一次全量 -vv/faulthandler 诊断复跑在旧 OpenCV `decode_frame`（4096×4096边界用例）发生 access violation，之前若干旧 dataset 用例失败；该轮未完成。事后内存快照可用物理约449 MiB、可用虚拟约1982 MiB，但没有足够证据断定因果。相关旧 dataset/decode 独立复查 **92 passed / 6.82s / exit=0**。完整日志/快照均归档。先前844通过仍为独立成功轮次；不能据此声称混合 native/OpenCV 进程稳定性已穷尽验证。

## 遗留和下一步

- 请架构主会话复核本子阶段，尤其缺模型前置检查、只读超龄结果、native 销毁失败重试及 Pipeline 来源边界。
- 02.2：BusinessPlugin/业务 DTO、Coordinator、去重与强制新观察；02.3：真实 Edge、Maa识别框驱动点击、DPR/raw/字体、≥3分钟/≥120有效周期、CPU/RSS、完整分发验证。本轮均未实现，不提前并入大改。
- 正式资源加载不解析 native 文本日志；如果上游内部错误与空识别详情相同且前置校验无法发现，仍需上游提供更细诊断。本阶段覆盖明确缺模型/文件错误与作业/详情错误，不承诺所有底层推理故障可区分。
- 后续混合进程复测应记录进程 RSS/系统内存并核查上述异常；不要关闭用户程序或通过放宽阈值、删负例消除失败。多 Python/系统、实际游戏、长期泄漏均未测。
