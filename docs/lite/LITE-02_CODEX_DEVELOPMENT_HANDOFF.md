# BCA-lite · LITE-02 开发任务书 / Codex Handoff

**阶段名：** MaaFramework Vision & Lightweight Plugin Contract  
**规划版本：** v1.0，2026-11-23  
**开发目标分支：** `lite`（不合并 `main`）  
**编写方：** BCA-lite 架构主会话；实现方：用户本地 Codex  
**来源起点：** 远端 `lite@3e54a2dbb531bd2026e8ae6349dd1559f58cba40`。Codex 开始时应自行核对本地 HEAD、worktree、上游变化。  
**上游依赖：** `maafw==5.16.1`，Python Binding 与 native 相同版本；不随意升级。  
**验收状态：** LITE-01 已具备 native/Edge 桥接交付证据、尚未完成正式 Accepted 的两项定向补测；LITE-02 本文件是**开发设计和任务安排**，不是已交付功能证明。

---

## 0. 项目目标与边界

最终产品 **Browser CLI Agent Lite (BCA-lite)** 是一个主要面向 Chromium/Edge、以 MaaFramework 为底层视觉/任务引擎的**轻量化交互式浏览器助手**。用户可选择指定浏览器 Target、通过截图感知页面状态、从终端查看业务信息并输入命令，后续可以装载 Quiz Demo 和雀魂等业务插件。

本阶段只实现**真实 Maa 视觉识别 + 最小业务插件接口 + 持续视觉观察的 SDK 基础**。交互式终端属于 LITE-03；完整带分数结算的 Quiz 网页和答题插件属于 LITE-04；雀魂场景属于 LITE-05。不要为了扩展性重新发明通用 OCR、模板匹配算法、完整 PluginManager、任务 DSL、事件总线或第二套资源管理系统。

**最短成功场景：** 受控 Edge 目标页面 → 现有 CDPBridge + MaaCDPController 返回真实截图 → MaaResource/MaaTasker 模板匹配及 OCR → 业务插件构建有来源的结构化快照 → 相同内容不重复通知、变化后通知 → 安全停止并释放所有 native/CDP 资源。可增加一次受控视觉授权点击以检查框坐标，但不得跳过观察来源/安全授权。

## 1. 开发前必读文档与源码

### BCA 现有代码/文档（以仓库实际内容为准）

1. `docs/md/BCA-LITE_MASTER_HANDOFF.md`（总路线；尤其 §3、§7、§12、§13）。
2. `docs/lite/LITE-00_HANDOFF.md`、`docs/lite/LITE-01_HANDOFF.md`、`docs/BCA-LITE-01.md`；以及本次主会话补充的 LITE-01 审查记录。
3. `src/bca/lite/bridge.py`：`CDPBridge`、`ObservationRef`、`run_native`、`authorize`、`aclose`、`input_outcome`。
4. `src/bca/lite/maa_controller.py`：`MaaCDPController`、`raw_size`、`close`。
5. `src/bca/core/browser/{session,capture,input,geometry}.py` 和 `src/bca/core/protocol/models.py`：尤其 `Frame.pixel_to_css()` 和 Target 绑定。
6. `tests/lite/{test_cdp_bridge,test_maa_native,test_real_bridge}.py` 及 `docs/evidence/LITE-01/`。
7. 旧资源与视觉：`src/bca/plugin_sdk/{assets,vision}/`、`docs/{ASSETS,VISION}.md`，只借鉴 fixture、语义标识和测试思路，不把旧实现作为新视觉后端。
8. `pyproject.toml`、现有 `examples/plugins/vision_fixture/` 与 `plugins/example`，对照旧业务插件复杂度，精简新契约。

### MaaFramework **v5.16.1**（注意锁定 tag，不以未来 main 代替）

- [Python Controller / CustomController](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/source/binding/Python/maa/controller.py)
- [Python Tasker](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/source/binding/Python/maa/tasker.py)
- [Python Resource](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/source/binding/Python/maa/resource.py)
- [Python Pipeline dataclasses](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/source/binding/Python/maa/pipeline.py)
- [Python Recognition/Task result models](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/source/binding/Python/maa/define.py)
- [官方任务流水线协议](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/docs/zh_cn/3.1-%E4%BB%BB%E5%8A%A1%E6%B5%81%E6%B0%B4%E7%BA%BF%E5%8D%8F%E8%AE%AE.md)
- [官方快速开始](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/docs/zh_cn/1.1-%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md)

**已核实的重要 API 事实：**

- `Tasker.post_recognition(reco_type, reco_param, image)` 会对 `reco_param` 使用 `dataclasses.asdict()`；请使用实际 `JTemplateMatch`、`JOCR` 等类型，**不能直接传 dict**。
- `JTemplateMatch(template: list[str], roi=..., threshold=..., ...)`、`JOCR(expected=..., roi=..., threshold=..., ...)` 均存在于该 tag 的 `maa.pipeline`。
- `Resource.post_bundle(path)->Job` 加载 Bundle；`Tasker.bind(resource, controller)` 绑定；`job.wait()` **同步阻塞**；`Tasker` 可 `post_task` 或 `post_recognition`。解析详情以当前安装版的 `TaskDetail.nodes`、`NodeDetail.recognition`、`RecognitionDetail.{hit,box,all_results,filtered_results,best_result,raw_detail}` 为准；对“Job 成功但未识别”必须区分。
- Maa OCR 需要相应 `model/ocr` 模型资源（典型含 `det.onnx`、`rec.onnx`、`keys.txt`）；不能把已安装 `maafw` 当作模型必然存在的证据。
- Maa 控制器截图为 BGR `numpy.ndarray`；Maa Controller 可能缩放返回图像。所有识别框坐标必须注明相对于**哪一张 Maa 返回的图像**；不要擅自应用 DPR/scroll，也不要混用旧 Frame 原始像素空间。
- `Resource`/`Tasker` 的 Python 生命周期在 v5.16.1 没有统一公开的 `close`；原生销毁及 callback holder 的存活必须参照 LITE-01 的固定版本策略，以单 owner、安全顺序、独立 worker 管理。

## 2. 期望的小型架构

```text
BCA-lite application (未来 CLI)
         │
    ObservationCoordinator  ← 观察节奏、单线程业务门闩、状态变化通知
         │
    BusinessPlugin           ← ID、观察为业务快照、命令/只读查询接口
         │
    MaaVisionFacade          ← MaaResource / MaaTasker / RecognitionDetail
         │
    MaaCDPController         ← 已实现、已用原生测试验证
         │
    CDPBridge                ← ObservationRef、authorize、输入状态
         │
    BrowserSession / Capture / Input → 明确选中的 Edge Target
```

推荐目录（允许基于仓库情况微调，但报告必须解释）：

```text
src/bca/lite/
  vision.py                # 薄的 Resource/Tasker 绑定和结果归一化
  plugin.py                # 小型业务插件 Protocol / typed data
  observation.py           # 带来源的业务快照、diff/signature、观察循环
  ...                     # 原有 bridge.py/maa_controller.py 原则上复用
plugins/lite_fixture/      # 小型真实视觉插件（或 examples/plugins/lite_fixture/）
examples/lite_vision.py    # 脱离 CLI 可直接跑通的 native+Edge smoke
resources/lite_fixture/    # 随项目加载的图片/配置资源（具体位置可调整）
tests/lite/                # 单测、native 集成、opt-in Edge 测试
```

### 插件协议：保持“最小但完整”

不强行指定每个 Python 类的名字，但必须可以清晰回答以下问题，并用一个真实 fixture 插件证明：

| 责任 | 必须提供的契约 | 限制 |
|---|---|---|
| 插件身份 | 稳定的插件 ID、资源路径和观测能力说明 | 不依赖旧 `PluginManager` 全套 Manifest |
| 装载/关闭 | 装载 Resource/模型，生命周期错误可解释，关闭可幂等 | 同一原生句柄只有一个 owner |
| 观察 | 从**本次** Maa 截图及识别详情产生业务快照 | 插件不能自行新建不受控浏览器会话 |
| 快照 | 业务内容 + 观察来源引用 + 时间 + 识别状态 + 可用于点击的区域 | 区域坐标空间必须统一且显式 |
| 状态变化 | 业务字段相同保持稳定签名；变化才通知 | 新 Frame ID 本身不构成业务变化 |
| 命令解析 | 用户可读命令 → 受限意图/或明确拒绝 | 业务插件只描述“想做什么”而不绕过授权 |
| 只读查询 | 按需强制新观察，而非将缓存冒充实时数据 | 具体 `?` 在 LITE-03/04 完整交互 |
| 失败/歧义 | `MATCHED / NOT_FOUND / AMBIGUOUS / ERROR` 或同等清楚模型 | 识别不确定时禁止基于猜测点击 |

**不要把“插件可调用任意 Maa Controller”视作插件 API 的常规路径。** 插件应返回业务目标/Intent，Coordinator 检查来源、语义签名、期限后授权执行；这不是另造 Runtime，只是 BCA-lite 特有的安全门闩。

## 3. 建议拆成三个可独立检查的子阶段

### LITE-02.1 · Maa Vision 原生验证

**目标：** 真正跑通 Maa 的 TemplateMatch、OCR 及识别详情，不只重复 LITE-01 的 `DirectHit/DoNothing`。

**任务：**

1. 用固定图像/网页素材创建可复现的 Bundle。使用 `Resource.post_bundle` 加载 `pipeline/`、`image/`；按官方格式准备 OCR `model/ocr`，明确文件来源、版本、许可证、校验摘要与打包策略。视觉模型可从上游 MaaCommonAssets 的合适发行物获取，不要在测试时默认联网下载，也不要将私人截图作为 fixture。
2. 测试两种识别调用：`Tasker.post_recognition("TemplateMatch", JTemplateMatch(...), image)` 和 `Tasker.post_task("RecognitionEntry")` / Pipeline；同理对 OCR 验证，可选择一条作为业务常规路径，明确可替代性及差异。
3. 使用原生截图 `controller.post_screencap().wait().get()` 的 BGR ndarray；取回 task/node/reco detail，读取命中状态、区域坐标、文字内容、可用候选及算法分数；不把 `Job.succeeded` 当成命中。
4. 实现最薄 `MaaVisionFacade`，只封装当前实际使用的识别调用与结果。不要把 Maa 原有识别类型重新实现一遍，也不要重写 TemplateMatch、OCR。
5. 建立误识别判定：模板/文字的正例、负例、无结果、相近候选、歧义与缺模型失败；阈值基于 Maa 算法实际分数校准，不沿用旧 BCA RMSE 分数。

**验收证据：** 原生 DLL 真实执行 TemplateMatch 与 OCR 的日志和结构化 JSON，识别框与 fixture 标签对比；资源加载失败、OCR 模型缺失等有明确错误路径。优先完成离线图片与 native 测试，再加 Edge。

### LITE-02.2 · 最小 Plugin 与结构化观察

**目标：** 将 Maa 图像结果转为稳定的业务快照，支持持续观测和业务变化通知。

**任务：**

1. 固定插件 Protocol：资源绑定、`observe`、内容签名、格式化快照、命令→Intent/只读查询（先接口和示例，真正终端交互在 03）。
2. 定义 `VisualObservation`（或同等）：`source` 包含至少 Target/session/generation、Frame/ObservationRef、观察时间、Maa returned image 大小、识别结果坐标空间；`payload` 是业务内容；`status` 表示业务有效性/歧义/错误；`semantic_signature` 只从相关业务内容生成。数据不可被后续观测悄悄覆写。
3. 建立一个只负责“观察间隔、一次一帧原生识别、归一化发布、显式停止”的观察协调器。业务状态需要支持连续帧的稳定和变化；停止、重复停止、错误后重启在没有悬挂工作前提下可控。
4. 支持至少 **1Hz 的有效视觉观察**：计数以完成的“截图 + Maa 识别 + 插件解析”为准。合理节流避免忙等和积压。不能把 `sleep(1)` 或空 loop 统计成有效观察。
5. 实现读请求强制新观察的接口（供未来 `?` 使用）。如观察与命令可能同时触发 Maa work，应通过单 owner 的顺序控制避免同一个桥接截图被意外替换。
6. 初版要能辨别连续相同、场景变化、识别丢失、错误恢复；每次异常有可诊断事件，不要默默沿用旧成功态。

**验收证据：** 离线 + native + Edge 下的内容变化去重与周期统计。证明用户输入将来不会因 native `.wait()` 在 owner loop 阻塞（当前阶段可用一个并发 `asyncio.sleep` 心跳断言）。

### LITE-02.3 · 真实 Edge Fixture 与完整阶段验证

**目标：** 用受控页面验证 `CDP → Maa screenshot → Template/OCR → Plugin snapshot`，并为 CLI 与 Quiz 留下可复用 fixture。

**任务：**

1. 建立固定可测页面：可切换目标图案、数字、按钮位置和字体，给出确定性种子或测试控制机制；测试通过图像识别获取内容，DOM 只作为测试 oracle。
2. 测试正例、负例、双候选/歧义、DPR 1/1.5/2、raw/non-raw、全图/ROI、改变字号/字体或渲染风格，以及导航、页面消失、截图超时后的失败快照。若算法不支持某字体/尺度，应明确返回 NotFound/不确定，不能“猜中”。
3. 至少一次**由 Maa 模板识别结果提供点击位置**，在 `require_authorization=True`、当前观察 ref、业务签名确认的基础上触发一组单步视觉点击；用 DOM oracle 验证目标及坐标。不要直接复制 LITE-01 的红色标记固定坐标点击并当作视觉识别验收。
4. 验证数据来源和实时变化，输出 1Hz 的有效观察记录（帧/识别/业务快照/事件），以及至少一段连续运行测量；建议覆盖 3 分钟以上，并包含真实状态变化、丢失与恢复。记录 median/p95 和样本量；记录 CPU/RSS 趋势以便后续回归。
5. 关闭后要求 native jobs 已结束、所有 native 句柄安全释放、CDP pending=0、reader=false、Target 只关闭自建页，用户已有 Edge Target 保留。
6. 执行仓库回归、静态检查与独立 wheel 安装，交付资源/模型是否可以从构建结果实际定位，而不是依赖开发者工作目录。

**验收证据：** 原始识别输入与输出（可以是 fixture PNG、标签 JSON、状态时间序列、识别结果与 CDP DOM oracle），明确运行命令、每个条件样本数量、正负样本统计及错误案例。

## 4. 安全与接口不变量（LITE-02 必须检查）

- **Target 来源：** 页面必须由用户显式选定或测试创建；任何失效后不自动改绑其他 Target。不同 Target/Session/generation 的观察不能混用。
- **数据与视觉：** 业务插件只看截图和 Maa 识别结果。业务逻辑不得调用 DOM/JS 偷读题目、按钮值或分数；DOM/JS 可用于**测试 oracle** 和可控 fixture 状态注入。
- **Frame 对齐：** 识别输出中的所有方框显式标记“原始 frame”或“Maa resized image”空间，并通过可测试变换转换。Image Buffer 与 Result 必须对应同一有效 frame；不得取前后两次图的框拼接。
- **状态签名：** `semantic_signature` 是业务内容变化检测，不是防止竞态的锁，也不是取代 `ObservationRef` 的授权。后续 Quiz 一道题可能十秒刷新后**内容恰好相同**，必须额外考虑回合 ID 或可视状态区分；不能把“相同文字”当作“同一回合”的证明。
- **观察与输入：** 如采用 `CDPBridge` 目前的一次观察授权，后台观察不得在授权至点击之间偷偷覆盖 `bridge.observation`。需要显式停观察、独占门闩、重新截图等一致的协议。
- **未知输入：** Maa job succeeded 仅代表控制器报告输入成功；实际页面是否处理必须重新观察。输入 outcome=`unknown` 后不补发、不自动重试。
- **歧义：** 正负候选或 OCR 冲突时给不确定状态；动作必须来源于唯一且验证过的目标。Maa `best_result` 不自动意味着可安全点击。
- **资源与生命周期：** native Resource/Tasker/Controller 不得在 job / callback 仍使用时销毁；同步 `.wait()` 不能发生在 CDP owner loop；取消时先停止新业务入口、排空 worker，再关闭 Bridge/providers/session。
- **分发与维护：** Maa v5.16.1 固定；模型及图像的来源、许可、文件哈希清楚；记录 LGPL 与资源模型各自许可要求，不假定都与 maafw 一样。

## 5. 对 Codex 的验收清单

1. 真实 Maa Framework 模板匹配成功：正例至少 10 个场景；负例至少 10 个；报告匹配位置误差与阈值，不使用旧 BCA RMSE。
2. 真实 Maa OCR 成功：至少 `0..9` 全部十种单数字；负号/多位数至少各 3 类场景；检测不同字体或字号的变化，记录成功率/失败率与模型依赖。
3. 证明**两条 Maa 识别 API** 由实际 DLL 运行，并说明为何选定日常业务 API。
4. 多目标/歧义情况下不得返回一个看似确定的可点击业务目标；NOT_FOUND / AMBIGUOUS / ERROR 状态明确。
5. 1Hz 有效读取：在目标测试机、真实 Edge 条件下记录至少 120 个连续完成周期，成功率和 `observed_at` 间隔分布；不能只靠单次截图 median 推算。
6. 图片像素坐标与 CSS 映射：DPR/ROI/raw 和缩放有真实验证，点击 target 来源于 Maa 识别；失效/导航/超时后零误输入。
7. 占用与清理：测试期间 CPU/RSS 趋势可复核；结束后无挂起 Maa/CDP 工作、用户原有页面不受影响。
8. 构建和质量：全量离线回归、lite+Edge 实测、mypy strict、Ruff check/format、wheel/sdist、独立安装与资源加载验证；环境、模型版本和可复现命令清楚。
9. 包内或插件独立资源布局可从非仓库工作目录加载；缺资源/模型时报可解释错误，不意外访问公网。
10. 不修改 `main`、不自动升级 Maa、不自动合并；交付日志和源码提交在 `lite`，不会伪造或覆盖原始失败证据。

> 本清单是建议的可复现最小矩阵。若个别阈值与实际测试预算冲突，Codex 需在动手前提出等价的可测方案并留下设计说明，不能删除测试项后照样宣称验收通过。

## 6. 阶段交付物与报告模板

- 设计决策：`docs/lite/LITE-02_DESIGN.md`（先完成，供架构审查；需说明 Native owner、API 选型、Snapshot/Plugin Protocol、坐标空间）。
- 完成报告：`docs/lite/LITE-02_HANDOFF.md`（列文件、API、代码提交、命令、每组测试结果、真实 Edge 条件、性能、缺口与下一步）。
- 接口文档：`docs/lite/PLUGIN_CONTRACT.md`（调用时序、实例创建/销毁、typed 结构示例、不同坐标空间定义）。
- 原始证据：`docs/evidence/LITE-02/`（日志、JSON、fixture 标签和受控图片/资源信息，避免私人游戏截图）。
- 可以运行的 `examples/lite_vision.py` 与 fixture 插件及相应 tests。
- 更新当前阶段局部说明与精确测试命令；正式 Accepted 由架构主会话决定。只有 Accepted 后才按总纲要求同步 `docs/md/BCA_PROJECT_CONTEXT.md` 和 `lite` README。

### 推荐每个子阶段的 Git 提交粒度

- `feat(lite): integrate Maa Resource and template OCR recognition`
- `feat(lite): add minimal visual plugin contract and observation loop`
- `test(lite): verify visual observations with real Edge and package assets`
- `docs(lite): archive LITE-02 handoff and evidence`

提交粒度仅是示例，可随实现调整；实际 SHA 必须来自 `git log`。

## 7. 给 Codex 的即时开工指令

请先阅读本文件和 `docs/md/BCA-LITE_MASTER_HANDOFF.md`，再阅读 LITE-00、LITE-01 的真实源码、测试与报告。首先报告当前 `lite` commit、`git status`、maafw==5.16.1 以及两个 LITE-01 定向补证的待完成状态。仅依据已实现的 `CDPBridge` / `MaaCDPController` 接口设计 LITE-02，不要自创不在上游的 Maa API。

先提交 **LITE-02_DESIGN.md**：说明 `Tasker.post_recognition` vs Pipeline 的选择，Maa 视觉数据如何绑定 `ObservationRef`、坐标框与结果如何归一化，以及 native Resource/Tasker/Controller 的拥有权和关闭顺序。设计讨论通过后按 **02.1 → 02.2 → 02.3** 顺序实现；每步保留原始测试与失败证据。未经用户明确请求，勿自行修改 `main` 或替架构主会话宣布 Accepted。
