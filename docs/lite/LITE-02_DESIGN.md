# LITE-02 接口设计提案

2026-11-23，基线 `lite@3e54a2d` + 本轮 LITE-01 定向补证。**供架构审查，尚未实现，未获设计通过前不启动 02.1～02.3。**

依据：LITE-02_CODEX_DEVELOPMENT_HANDOFF、LITE-01_ARCH_REVIEW、主交接书 §3/7/12/13、当前 bridge/controller/Browser 源码，以及安装的 maafw v5.16.1 Python binding。保留历史 Assets/Vision fixture 思路，不复用 RMSE 算法或旧 PluginManager。

## 1. 决策摘要

- 每个激活的插件拥有一个 MaaVisionFacade；Facade 独占 Resource、Tasker、MaaCDPController 和单 worker executor。Application 独占 BrowserSession/Capture/Input；Bridge 借用它们。插件不持有原生句柄或浏览器接口。
- Coordinator 在 asyncio owner loop 用一个串行门覆盖截图、识别、解析、必要的单步授权与输入；所有 native 调用/详情物化/销毁在同一专用 worker 上执行。不另造调度器、资源注册中心或通用 DSL。
- 常规识别采用 `post_recognition(type, dataclass, image)`：一个 Maa 返回图像、一个精确 ObservationRef、多次识别共用此图。Pipeline 仍在 02.1 作原生验证，但不作为默认观察链，避免隐藏截图替换引用。
- 观察内容签名负责去重；命令语义修订负责验证意图是否仍适用；ObservationRef 负责绑定/几何/时效。三者不能互相替代。
- 写操作一律 `require_authorization=True`。只允许从本次唯一视觉候选解析出的业务目标，单次点击后强制新观察；未知输入永久退役当前运行组合，不自动重发。

## 2. 资源拥有权与释放

建议新增 `vision.py`（含内部固定版本 native owner）、`plugin.py`（不可变 DTO 与 Protocol）、`observation.py`（Coordinator）。不增加独立通用资源管理系统。

| 对象 | owner / 所在线程 | 清理 |
| --- | --- | --- |
| Session / Capture / Input | Application / asyncio loop | native/bridge 完全排空后 Input → Capture → 自有 Target → Session |
| CDPBridge | Application / asyncio loop | 跨线程 invalidate 仅撤销入口；await aclose 等实际 coroutine finally |
| Controller、Resource、Tasker | Facade / 单 worker | 停止后 TaskerDestroy → Controller.close → ResourceDestroy |
| Callback holders、绑定强引用、临时 Job | Facade worker | 至少保持到最后一个相关 job 结束及 Destroy 返回 |
| 插件实例 | Coordinator / owner loop | 纯业务解析；close 只清理插件自己的业务状态，不释放外部 Maa/CDP |
| 图像、normalized results | 单次 CaptureContext / 观察调用 | 转换为独立只读数据；发布后的结果不再调用 native |

启动：在 loop 上显式 connect/bind/start providers → 构造授权模式 bridge → worker 建 Controller/Resource/Tasker → connection job → post_bundle(可信绝对路径) → bind(resource,controller) / inited → 插件准备就绪 → 接受观察。每步失败按已创建资源逆依赖清理，不留部分激活对象。

固定版本释放层只调用安装绑定已注册的 `MaaTaskerDestroy`、`MaaResourceDestroy` 和现有 Controller.close；清空 `_handle` 后避免 __del__ 二次销毁。运行前同时核对 Python distribution/native version 是 5.16.1；只对受审计对象使用私有字段。不得把这些调用宣传为长期稳定的上游 Python 公共 API。

关闭：禁止新入口/停止周期任务 → 如有取消先 bridge.invalidate → 当前 worker job 到终态 → worker 调用 tasker.post_stop().wait → 销毁 Tasker（此时保持 Resource/Controller 强引用）→ Controller → Resource → 等待 executor shutdown → bridge.aclose → 外部 providers/session。所有 native 等待都不在 CDP loop。关闭流程用一个持有强引用的共享清理 Task，重复 close/取消只等待，不重复 Destroy；清理异常记录到 CloseReport，不能以 CLOSED 冒充释放成功。

**取消限制：** 上游 Job.wait 没有超时参数，也没有通用 Job.cancel。不能把 asyncio 等待超时解释为 native 已停。Facade 自有 worker Future 必须 shield 后排空；取消 bridge 会使后续 CDP callbacks 失败，但不保证中止正在执行的 OCR。单 worker 当前正在 wait 时，不把 post_stop 排到后面又声称它能立即中断前面的 job。若 native 永久卡死，线程无法强杀，标记关闭未完成并保留资源；02 不引入进程隔离。应用层 deadline 只控制入口与业务有效期，不能伪造 native 强制终止保证。

现有 run_native 适合一次性 smoke，其 to_thread 默认池不提供固定线程，也规定 callable 自行销毁资源。长期 Facade 不逐次套用该一次性 helper，改为私有 `_submit` 对单 worker executor 做同等 shield/drain；构造/作业/详情读取/销毁均由此入口串行。其关闭和重复取消需要独立回归。

## 3. Maa API 与结果归一化

安装源码核对：`.venv/Lib/site-packages/maa/{resource,tasker,pipeline,define,job,controller}.py`；可对照 [v5.16.1 binding](https://github.com/MaaXYZ/MaaFramework/tree/v5.16.1/source/binding/Python/maa)。下述为真实签名/字段，语义组合仍须 02.1 实测。

```python
resource.post_bundle(bundle_path).wait()
tasker.bind(resource, controller)
image = controller.post_screencap().wait().get()  # BGR uint8
job = tasker.post_recognition(
    "TemplateMatch",
    JTemplateMatch(template=["button.png"], roi=(x, y, w, h), threshold=[threshold]),
    image,
).wait()
ocr_job = tasker.post_recognition(
    "OCR",
    JOCR(expected=[], roi=(x, y, w, h), threshold=ocr_threshold),
    image,
).wait()
```

JTemplateMatch.threshold 是 list[float]、method 默认5；JOCR.threshold 为 float，expected 为 list[str]（允许正则的具体行为需正负例核验），only_rec/model/replace/order_by/index 均为实际字段。不沿用旧0.96；模板算法分数和OCR置信度分开校准。缺图/缺模型在加载预检和 native 失败处提供明确诊断，不靠低阈值“通过”。

`job.get()` 返回 TaskDetail 或 None；`TaskDetail.nodes` 是**惰性加载**，可能继续调用 Tasker，必须在 worker 且 Tasker 存活时完全物化。遍历 NodeDetail.recognition，读取 RecognitionDetail 的 reco_id/name/algorithm/hit/box/all_results/filtered_results/best_result/raw_detail；不能假定 nodes[0] 永远是目标节点。显式校验对应请求/预期算法，节点缺失或解析异常归 ERROR。

TemplateMatchResult 实际为 BoxAndScoreResult(box,score)，没有自动提供应用 asset_id。请求携带自有 request_key/asset_id，用请求归属标记候选；需要区分多个模板身份时分别请求或独立命名节点，不从合并列表猜索引对应模板。OCRResult 包含 box/text/score，按实际类型读取；Rect 归一为不可变 (x,y,w,h)，检查有限值、非负位置、正尺寸及图像边界。

保留所有 filtered candidates 供插件解释；best_result 仅诊断，不能直接当唯一授权目标。Facade 不把多个有效独立目标自动判为歧义：只有请求/插件要求唯一目标却有竞争者、或 OCR 结果互相矛盾时，业务结果为 AMBIGUOUS。不得重新实现模板匹配/NMS/OCR。

| 归一状态 | 判定 |
| --- | --- |
| MATCHED | native结果完整、hit且满足业务所需字段/唯一性策略 |
| NOT_FOUND | 有效识别详情明确无命中；不凭 Job.failed 猜测 |
| AMBIGUOUS | 有多个无法消歧的业务候选/文字冲突；不生成可写目标 |
| ERROR | 资源/模型/截图/任务执行/结果结构错误；native failure 无足够无命中证据也归 ERROR |

Job.succeeded 与 hit 分开保存；Job.failed 仍尝试取详情，但不得把框架错误归成“没有目标”。02.1 必须用实际负例记录两条 API 的 status/hit/nodes/raw_detail，若上游行为不同则更新适配规则及设计。

Pipeline 验证：`resource.post_bundle` 加载仅 recognition + DoNothing 的命名节点，再 `post_task(entry, pipeline_override)`；设置有界 timeout，避免无匹配任务长时等待。记录内部实际截图次数、每个节点对应来源。普通 Pipeline 可多次截图和重试，**不能**将最新 bridge.observation 随意套给整个 TaskDetail 的全部节点。02.1 采用单节点/单次受控场景并追踪截图计数；无法建立精确关联时只作为 API 证据，不向业务暴露可授权 observation。两条路径都要真实执行 TemplateMatch 和 OCR，不能只验证 DirectHit。

## 4. 图像与 ObservationRef 关联

建议内部冻结模型：

```text
CaptureContext:
  source_ref: ObservationRef       # 保留同一对象，绝不重建/序列化再授权
  binding: (target_id, session_id, generation)  # Application 已知并核验
  frame_id: str
  captured_at_utc, observed_at_monotonic, completed_at_monotonic
  maa_width, maa_height, raw_width, raw_height
  coordinate_space = "maa_image_pixels"
  image: read-only BGR uint8 ndarray

RecognitionBatch:
  capture: CaptureContext
  results: tuple[RecognitionResult, ...]  # 自有不可变候选/状态/追踪ID
```

捕获流程：Coordinator 持有门 → worker 只发一次 post_screencap 并 wait/get、复制数据 → 回到 loop 立即读取 bridge.observation → 检查非None、binding、Frame identity/尺寸、原任务成功 → 固定 CaptureContext → 同一门内 worker 对同一 image 完成全部识别并物化详情 → 插件解析 → 发布。两次 worker 提交之间门仍不释放，其他观察或点击没有入口。识别执行中导航/失联可使已得图像成为历史记录；发布前复核 binding/live ref，失效时发布 ERROR，绝不授权。

默认 raw_size=True；non-raw 是可测试配置，任务启动后不允许改变 resize 参数。坐标全用 Maa 返回图像像素；图像 ROI 为识别参数（不是截取后丢失原点的独立数组）。对算法返回 ROI 框究竟是全图还是 ROI-local，02.1 用已知位置实测，统一为 maa_image_pixels；只在有证据时加 ROI 原点，不能默认重复加。

点击由 Coordinator 在返回图像空间选整数中心，调用 controller.post_click；Maa 将其按 raw/returned 比例 round，bridge 再 Frame.pixel_to_css。**不提前转 CSS 再交给 post_click。** 如使用区域 CaptureProvider，Frame 自带 capture_x/y，仍只由 Frame 转换一次。scaled near-edge rounding 后可能越界：先验证映射 raw point 落在 Frame 内，否则拒绝而非 clamp 猜测。

VisualObservation 不长期持有完整 ndarray：包含自有序号、source_ref/元数据、业务payload、status、diagnostic、signature与targets。ref 的 Frame 自带PNG，最新状态持有一份；订阅者只收到轻量通知，不无限积累PNG。取消/错误输出 source=None 或带明确失效标记，不复用旧成功 source。payload 用冻结dataclass/tuple/不可变标量，拒绝共享可变dict“冻结外壳”；数组若暴露需独立不可写后端，setflags不可绕过，沿用旧资产的不可变bytes思路即可。

## 5. 最小业务插件 Protocol（建议，不是现有代码）

插件只获已经归一的识别结果，无 Controller/Tasker/Session。宿主加载一个可信 Python 实例，不扫描插件目录，不引入旧 Manifest/PluginManager。

```python
class BusinessPlugin(Protocol):
    plugin_id: str
    resources: ResourceSpec

    def plan(self, image_size: tuple[int, int]) -> tuple[RecognitionRequest, ...]: ...
    def observe(self, results: RecognitionBatch) -> BusinessState: ...
    def format_state(self, state: BusinessState) -> str: ...
    def parse_command(self, text: str) -> Intent: ...
    def resolve(self, intent: Intent, current: BusinessState) -> TargetKey: ...
    def close(self) -> None: ...
```

- ResourceSpec：Bundle位置、可选OCR模型清单、能力声明。Facade负责装载与释放；插件不重复 load native Resource。失败视为插件激活失败，有原因可查。
- RecognitionRequest：仅两种薄类型 TemplateRequest/OCRRequest，含稳定request_key及对应的配置；转换成上游dataclass，不设计新的流水线语言。plan只根据图像尺寸/静态配置设置ROI，不能用DOM。
- BusinessState：payload、status、semantic_signature、可选interaction_revision、targets: tuple[VisualTarget,...]。observe为同步纯解析；显式source由宿主包到VisualObservation，插件不能伪造替换引用。
- VisualTarget：target_key、对应request/candidate key、maa坐标box、可操作性；宿主核验坐标确实来自本batch已验证候选。业务按钮不能随意填写固定坐标冒充视觉定位。
- Intent 为有限联合 `ReadIntent(query_key)` / `ActionIntent(verb, target_key, expected_revision, deadline)`；parse失败抛明确命令错误。只读请求总是 Coordinator.refresh，得到**新** observation，再调用format；不返回缓存冒充即时数据。
- close为同步幂等轻量业务清理；当前插件不允许自建后台任务/native资源，因而无需async initialize/start/stop全套生命周期。如果今后确需外部I/O，另提接口变更。

签名：plugin.observe根据业务相关payload生成不可变签名，排除frame_id/时间/native job ID。状态改变比较 `(status, semantic_signature, diagnostic_category)`，新帧相同内容不重复通知；错误恢复必须通知。interaction_revision只在视觉证据能辨认场景/回合时有效。相同文字不证明同一回合：若 intent 需要回合一致性但没有可视revision，拒绝该类跨观察写操作，或在后续 fixture 中增加可视回合标志，不用DOM偷补。

## 6. Coordinator 与命令边界

建议公开 async start/stop/close/refresh/execute_intent，sync latest/stats。一个 asyncio.Lock 是本目标所有 native work 的入口门。周期任务最多一个在途操作，无补跑积压。refresh无条件等待门后拍新帧，不复用正好正在进行或旧缓存的帧。

- start：资源已就绪后开始观察；RUNNING下重复start幂等。
- stop：禁止周期新入口并等待当前周期完成，不关闭Facade；再次start可用。业务执行另受同一入口状态约束，stop需等待当前命令有界业务步骤结束或显式撤销并退役。
- close：停止所有入口、排空并释放全部自有资源，终态不可重启。
- 识别NOT_FOUND/AMBIGUOUS/模型级ERROR可在后续新观察恢复；bridge超时/失联/unknown是运行组合终止条件，不在后台偷偷重连。恢复由Application显式创建新实例及新目标/已知输入状态；旧意图废弃。
- 每周期统计 capture/native-recognition/parse/total、开始/完成时间、成功数/失败数/丢弃tick；以完成且有效的视觉结果计算1Hz，不把失败循环计成功频率。间隔以单调时钟，不积压补偿。
- 仅保留latest快照；变化通知为有界轻量记录，序号可检测遗漏；诊断另写结构化日志。通知消费者慢时不持有业务门等待UI，记录丢弃数，不引入事件总线。

单步execute_intent：取得门 → 新截图/识别 → 匹配原intent的revision/deadline及唯一目标 → 来源和box边界复核 → authorize(该精确ref) → worker native post_click → 消费ref → 新观察验证后置状态。返回 InputOutcome 与新观察分别表示输入和业务结果，不把success混为一谈。门从开始直到后置观察完成保持，背景循环不能替换ref。02.3仅验证一个受控视觉点击；完整多步Quiz/命令队列交互由04/03实现，不提前造批次Runtime。

## 7. 素材/模型与分发

Fixture图片/标签/最小pipeline放在包内 `bca/lite/resources/fixture/`，用 importlib.resources/as_file 管理路径生命周期至 Resource 关闭，支持非仓库cwd和wheel；独立插件ResourceSpec也可指向明确可信绝对Bundle。OCR模型单独显式配置，缺失报错，不在import/start/test时静默联网下载。

02.1选择并记录具体MaaCommonAssets发行物/commit、det.onnx/rec.onnx/keys.txt尺寸、SHA256和各自许可证；未取到并审查前不声称任何模型可再分发。当前设计阶段未下载/选定模型，OCR质量未测。模型体积不默认进Git/wheel；附可复现获取与校验说明，可在离线测试机预配置。模板/字体使用有可分发许可的受控fixture，列来源和标签；不提交私人网页截图。

## 8. 分阶段实施与审查门

| 子阶段 | 实施顺序 | 必需证据 |
| --- | --- | --- |
| 02.1 | 固定版本native owner → Bundle/模型 → 直接识别/单节点Pipeline → 归一化 | 两路真实DLL Template/OCR；模板≥10正/10负；数字0..9、负号≥3类、多位数≥3类；缺模型/歧义；详情/source/ROI实测；反复启动关闭和部分失败 |
| 02.2 | 冻结DTO、最小Plugin → Coordinator → 去重/refresh/门闩 | 同内容不刷、变化/丢失/错误恢复；refresh必有新帧；同loop心跳；并发观察与授权无覆盖；取消/重复stop/显式重建 |
| 02.3 | Edge fixture → Maa视觉点击 → 连续运行 → 分发回归 | DPR/ROI/raw/字体字号/失效矩阵；不少于3分钟且≥120有效完成周期；CPU/RSS趋势、median/p95；准确DOM oracle；所有句柄/Target/pending清理；wheel异cwd资源/缺模型测试 |

所有测试分开报告 fake / native固定图 / native+Edge。02.1若发现 API 输出语义、资源模型可用性或坐标语义与设计不同，先更新设计差异；不删除负例或降低验收门槛后直接声称通过。

## 9. 请求架构主会话审核的具体决策

1. 单native worker + Facade唯一拥有者、取消排空及固定版本私有Destroy；不承诺线程强杀。
2. 直接识别作为默认观察路径；Pipeline只在来源可追踪条件下提供观察，无法配对则只做API验证。
3. 插件纯业务Protocol（plan/observe/format/parse/resolve/close）及宿主统一资源装载，无通用插件生命周期框架。
4. CaptureContext精确ref绑定、不可变结果、去重signature与interaction_revision区分、缺回合证据拒绝跨观察写操作。
5. 单门覆盖新观察至单步动作及后置观察，停止/错误重建语义与有界通知。

审查通过后才按02.1→02.2→02.3落地。本文没有修改产品源码，也不把资源/OCR/观察循环写为已实现。
