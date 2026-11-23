# BCA-lite — MaaFramework 架构迁移与完整产品开发主交接书

> **文档版本：** v1.0  
> **编制日期：** 2026-11-23  
> **文件角色：** 新工作目录中 Codex 的总上下文、研发分阶段任务书与验收边界；**不是**原 BCA `BCA_PROJECT_CONTEXT.md` 的覆盖版本。  
> **项目仓库：** https://github.com/Itsukiii/Browser-CLI-Agent  
> **唯一研发分支：** `lite`  
> **文档核对时 `lite` HEAD：** `88ba80e68897ef8e40834d03696cb26d7a5d8504`  
> **历史稳定分支 `main` HEAD：** `6763016ff5fee86fb194ebe0e0c9ca17d775adfe`  
> **上游技术基线：** MaaFramework `v5.16.1`（2026-11-13 Release；开发前仍应核对 API 与依赖的实际安装版本）。  
> **状态：** 架构重定向已决定；原 BCA-00～04 为已验收历史基线；BCA-lite 尚未完成任何正式阶段验收。`lite` 仅有一笔未完成真机验收的实验桥接实现。

---

## 0. 致 Codex：先读这个

你的任务不是继续为 BCA 编写一套新的底层自动化框架，而是把项目重构为 **基于 MaaFramework 的轻量化、可扩展、面向指定浏览器页面的交互式 CLI 自动化应用**，名称 **BCA-lite**。

**团队分工：** Codex 在用户本地新工作目录中负责实际阅读、开发、测试、提交和阶段交接；ChatGPT 架构主会话负责规划、公共接口协调与正式验收。未经用户另行授权，架构主会话不再直接修改 GitHub 代码。本文件为 Codex 的开发起点，而不是已经实现的成果。

**优先级顺序：** 真实端到端可用性 > 明确页面与动作安全 > 稳定可维护的轻量接口 > 复用 MaaFramework > 抽象优雅程度。避免借由“可扩展”重新造出一套 MaaFramework。

**开始阶段仅限审计与基础桥接：** 先完成 LITE-00 的仓库审查、MaaFramework 安装/API 验证，再进入 LITE-01 的浏览器适配。不要在第一笔代码里同时引入完整 CLI、重写插件系统、搬迁所有历史源文件和实现雀魂。

### 0.1 开始前必须核对工作目录

```powershell
# 在新的 BCA-lite 工作目录执行
git branch --show-current
git status --short
git rev-parse HEAD
git remote -v
git log -5 --oneline
```

要求当前分支为 `lite`，工作树干净；如当前 HEAD 晚于文档列出的 `88ba80e`，以**实际远端提交及工作区内容**为准，先调查差异，不能覆盖用户新增代码。不要在 `main` 开发，不强推或变基已发布的稳定历史。

### 0.2 阅读顺序（按需深入而不是盲目全量复制）

**本项目历史资料：**

1. `README.md`（注意 `lite` 顶部实验状态说明）；`pyproject.toml`。
2. `docs/md/BCA_PROJECT_CONTEXT.md`（历史架构共享背景，不作为 lite 最终技术架构约束）。
3. `docs/BCA-01_MAIN_SYNC.md` + `docs/BROWSER.md`：CDP Target、Frame、坐标、截图/输入约定。
4. `docs/BCA-02_MAIN_SYNC.md` + `docs/RUNTIME.md`：来源新鲜度、动作不确定结果与恢复设计，作为必须理解的安全目标，但不要求保留整套旧 Runtime。
5. `docs/BCA-03_MAIN_SYNC.md` + `docs/PLUGIN_SPEC.md`：原插件生命周期、资源归属与业务分离思想。
6. `docs/BCA-04_MAIN_SYNC.md` + `docs/ASSETS.md` + `docs/VISION.md`：历史视觉能力、截图坐标、歧义与素材语义。
7. `docs/BCA-LITE-01.md`：已提交的 **实验** MaaFramework CDP Bridge 说明。
8. `docs/DEVELOPMENT_PLAN.md`、原任务书 `docs/md/BCA-04_Vision_Assets.md` 如有，以及当前项目共享的 `BCA-05_CLI.md`：历史路线和 Quiz Demo 的详细用户需求。仓库中若不存在某个外部任务书，使用本交接书第 9 节完整需求即可。
9. 对应 `examples/`、`tests/core/browser/`、`tests/core/runtime/`、`tests/plugin_sdk/` 的具体测试实现；以实际代码为准。

**必须检查的关键代码：**

```text
src/bca/core/browser/session.py
src/bca/core/browser/capture.py
src/bca/core/browser/input.py
src/bca/core/browser/geometry.py
src/bca/core/protocol/models.py
src/bca/core/runtime/browser_freshness.py
src/bca/lite/bridge.py
src/bca/lite/maa_controller.py
examples/lite_maa_cdp_smoke.py
tests/lite/test_cdp_bridge.py
pyproject.toml
```

**MaaFramework 官方资料（优先以安装版本及对应 tag 对齐）：**

- 项目 README / 快速开始：https://github.com/MaaXYZ/MaaFramework
- Python CustomController：https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/controller.py
- Python Tasker：https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/tasker.py
- Python Resource：https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/resource.py
- Python Context：https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/context.py
- 集成 API：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.2-集成接口一览.md
- Pipeline：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.1-任务流水线协议.md
- 控制方式：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.4-控制方式说明.md
- Custom & Agent：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/1.3-Custom%26Agent.md
- ProjectInterface V2：https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/3.3-ProjectInterfaceV2协议.md
- LGPL-3.0 License：https://github.com/MaaXYZ/MaaFramework/blob/main/LICENSE.md
- 上游 CustomController + PI 支持请求：https://github.com/MaaXYZ/MaaFramework/issues/1271 （编制时 Open；开发中重新核对）

严禁仅根据旧交接文档猜测 MaaFramework 的参数签名、坐标系或 Tasker 事务语义。源码、官方文档、真实运行结果不一致时，记录差异，按当前锁定的已安装版本纠正。

---

## 1. 产品定位与范围

### 1.1 BCA-lite 最终用户体验

用户在本机终端连接自己的 Chromium / Edge **指定 CDP Target**，选择业务插件，持续读取该页面的视觉识别结果；只有业务状态改变时刷新终端信息。用户输入简短命令，应用利用该插件对应的识别与动作规则控制浏览器，并用新的实际视觉观察报告结果。

首个验收样例是 **Quiz Demo**：终端显示页面里的数字题目、A/B/C/D 四项、视觉识别得到的当前分数；每 10 秒或提交后页面变更；用户输入单字母或 `?` 即可操作或查分。第一个正式业务插件是 **Mahjong Soul / 雀魂**，以视觉读取牌局状态及手工命令交互为主。

### 1.2 原则上的精简

- **MaaFramework 管：** 图像识别（模板/特征/OCR/模型）、资源 Bundle、识别结果、底层 Tasker/任务与可复用动作原语、Custom 逻辑扩展。
- **BCA-lite 管：** 明确浏览器 Target 绑定、CDP 截图/输入适配、跨线程和坐标协议、每轮观察来源授权、可观察的业务状态、交互式 CLI、业务插件的页面专属语义。
- **业务插件管：** 如何从视觉结果得出场景和对象；如何解析命令；如何映射意图和按钮位置；如何在新观察中确认业务结果。
- 旧 BCA-00～04 保留为历史回退与测试参考。新架构不必兼容历史的全部 `PluginManager`、`StateStore`、Vision RMSE、Manifest/Profile 或 Protocol 2 类型；需要保留的行为以小而明确的接口重述。
- 按需采用 Python 全代码 + MaaFramework API；只将确实可复用的静态规则写成 Pipeline / Bundle。不要为了使用 Pipeline 牺牲交互式状态或安全要求。

### 1.3 明确的完成定义

“BCA-lite 完整功能”指能够在指定浏览器 Target 上，**安装 → 启动 → 选择插件 → 稳定连续视觉观察 → 增量展示 → 人工命令 → 实际浏览器输入 → 重新观察验证 → 安全退出**，并拥有可运行的 Quiz Demo 和可按真实资料验证的雀魂插件。不能以“框架类已存在”“单次截图成功”“Tasker 返回 success”代替完整功能完成。

---

## 2. 当前 GitHub 仓库的真实状态

### 2.1 已验收的历史资产

`main` 对应旧架构 BCA-00～04，已分别验收 Protocol、Browser/CDP、Runtime、Plugin System、Vision & Assets；它们的测试报告只证明**各自旧架构的既有阶段**，不能直接声明新的 MaaFramework 架构已通过相同测试。

最值得复用的是 BCA-01：`BrowserSession` 显式绑定 `Target`、`BrowserCaptureProvider` 生成 `Frame`、`BrowserInputProvider` 安全输入，以及 `Frame.pixel_to_css()` 的区域裁剪/DPR 坐标模型。BCA-02 对过期观察、未知输入结果和资源恢复的设计可以作为 **lite 安全需求** 复用，而未必需要继续运行其完整 Controller/Scheduler。

### 2.2 `lite` 分支已存在的实验代码（不是验收结论）

- `src/bca/lite/bridge.py`：`CDPBridge`，经 `asyncio.run_coroutine_threadsafe()` 桥接到 `BrowserSession` 所在事件循环；提供 `screencap()` 与 `click()`。
- `src/bca/lite/maa_controller.py`：`MaaCDPController(CustomController)`；已接入连接状态、截图与左键点击。
- `examples/lite_maa_cdp_smoke.py`：真实 CDP 连接 → Maa 控制器截图，可选一次点击。
- `tests/lite/test_cdp_bridge.py`：模拟 Session/Provider 的初级单测；并非真实 Maa 原生控制器联调。
- `pyproject.toml`：新增可选 `[lite] = ["maafw>=5.16.1,<5.17", "numpy>=2.4,<3"]`。
- `docs/BCA-LITE-01.md` 与 `lite` README 顶部：明确这是第一条实验链路。

以上是先行实验代码。Codex 有权根据 **MaaFramework 实际回调语义** 修正、重构甚至替换其实现，但应保留原本 CDP 安全行为的回归测试，解释为何修改。实验源码中出现的注释、未使用导入及单测数量都不能当作质量证据。

### 2.3 已知审查重点／可能的缺陷

1. **回调线程与重入：** native C → Python 的 CustomController 回调线程、同步调用 `future.result()` 是否可能阻塞 asyncio owner loop；异步取消后后台 Future 是否仍在执行；`threading.Lock` 和关停顺序是否可能死锁。
2. **任务关闭时序：** `bridge.invalidate()`、正在运行的 Maa Job、Python wrapper/native 对象、InputProvider/Session 之间谁先停谁先关。不可只依赖 `__del__` 或 `gc`。
3. **坐标尺度：** Maa 缺省截图缩放与 CDP Frame 原始像素不同；必须用真实浏览器 DPR 和非 720p 窗口验证 Maa `post_click` 回调实收的坐标，不能推测两层都已经转换。
4. **来源授权：** 现在的“一帧只容许一次点击”只是暂时的保守策略。Quiz 必须点击选项和确认，需设计业务事务/连续动作的正确授权方式。不能简单删去限制让任意后续点击复用旧帧。
5. **同页变化：** Target、URL、时间原点和几何不变时，十秒更新题目或 DOM 局部变化可能不触发原 `BrowserFreshness` 指纹。需定义同页回合签名/新观察/结算防竞态机制。
6. **失败返回：** `MaaCustomController` 同步回调将 Python 异常映射成 C 层布尔失败；要有 last_error/日志，区别“确定未执行”与“动作可能已经发出但确认丢失”，后者不得自动重发。
7. **控制器特征标记：** `MaaCDPController.get_features()` 当前直接返回 `0`，需对照 MaaFW C API/绑定/真实运行确认 `Click` 是直调还是合成 Down/Up，不能把默认行为当已验证。
8. **包与类型检查：** `src/bca/lite` 使用 NumPy 和 MaaFW optional extras；基础包、`[lite]`、开发安装的 import 边界及 mypy/Ruff 检查需要明确，确保旧代码不被无意破坏。
9. **安全的停机：** 失联、取消、超时后拒绝老动作；恢复必须基于新观察、新授权，而非猜测原点击未生效。
10. **MaaFW PI 限制：** 现有 `ProjectInterface V2` 没有已验证的 `Custom` 类型；上游 issue #1271 在编制时尚未关闭。因此 **自行实现轻量 CLI 宿主**，不能承诺直接套 MaaPiCli 等客户端加载 CDP CustomController。

这些都是需要 Codex **核实的风险清单**，不是已逐条复现的 bug 清单；每条应以源码分析与测试归因。

---

## 3. 目标架构与边界

```text
+----------------------------------------------------------+
| BCA-lite Application / CLI                               |
| 命令输入  状态去重显示  插件选择  配置  诊断  安全退出     |
+-------------------------+--------------------------------+
                          |
                  BCA-lite Coordinator
           观察/动作序列化、来源校验、错误恢复
                          |
               BCA-lite Business Plugin
      observe/format/parse/intent + asset binding
                          |
+-------------------------v--------------------------------+
| MaaFramework Python Binding / Core                       |
| Resource/Bundle | Vision/OCR/Template | Tasker/Events     |
+-------------------------+--------------------------------+
                          |
                  Maa CustomController
                          |
                BCA-lite CDP Bridge
       同步 callback <-> asyncio；来源与坐标守卫
                          |
       BCA-01 BrowserSession / Capture / Input
                          |
             指定 Chromium / Edge Target
```

**建议新的最小包分层（示意，不是强制要求）：**

```text
src/bca/lite/
  bridge.py               # 保留/修正 CDPBridge
  maa_controller.py       # 保留/修正 CustomController
  runtime.py              # 应用级协调/安全动作生命周期
  observation.py          # frame/version/业务快照/去重
  vision.py               # Maa Tasker/Resource 的轻量 Facade
  plugin.py               # 简明业务插件 Protocol
  config.py               # TOML 配置
  cli.py                  # 异步终端应用
plugins/quiz_demo/       # 页面的识别与交互语义
plugins/majsoul/         # 有真实数据后逐步开发
examples/quiz_demo/      # 可本地启动的固定网页
```

可以调整结构，但设计原则是 **尽量少的长期状态对象、明确单一拥有者、不要重复 MaaFW 的调度器/资源管理器/识别框架**。应用级 Coordinator 只负责框架未提供的安全授权、人工交互和输出状态，不等于新通用 Runtime。

### 3.1 MaaFramework 的使用约定

- 经核实的 Python API 有 `maa.controller.CustomController`、`Controller.post_screencap()`、`Controller.post_click()`、`Tasker.bind()`、`Tasker.post_task()`、`Tasker.post_recognition()`、`Tasker.post_action()`、`Resource.post_bundle()`、`Resource.register_custom_recognition/action()`。
- Maa Framework 的 `Job.wait()` 会**阻塞调用线程**，不能直接在 CDP owner event loop 调用；用专门工作线程、`asyncio.to_thread` 或有界执行器，明确退出等待和取消语义。
- Maa CustomController `screencap()` 必须返回 BGR `numpy.ndarray`；CDP Frame 由编码 PNG 解码。每轮识别结果的位置如何反馈给动作、是否会自动按缩放换算，必须有实测断言。
- Maa `CustomController.click()` 是 `int` 像素坐标；BCA `Frame.pixel_to_css()` 返回 CSS viewport 坐标。页面滚动、截图 ROI、DPR 只能在明确的转换责任层应用一次。
- Maa `Tasker` 的 task/reco/action ID 用于任务追踪，不天然带 CDP Frame 身份、业务回合或 `ActionObservationRef`；这些必须由应用层额外关联。
- Maa 默认 TemplateMatch 分数与旧 BCA weighted-RMSE 分数**不兼容**；旧阈值 `0.96` 不可直接迁移。
- 所有操作以图像识别、交互目标为中心；读取浏览器 DOM 作为测试 oracle 可以，不能悄悄让业务插件用 DOM 获取答案然后宣称“视觉识别”。

### 3.2 核心状态与安全不变量

1. **显式绑定：** 只对用户指定、当前有效的 Target 发命令，拒绝自动切到其他页面；无 Target 不截图、不点击。
2. **一次观察的身份：** 记录至少 `(target_id, session_id, generation, frame_id, geometry/document fingerprint, observed_at, semantic_revision)`；同页动态题目还需插件层业务回合签名。不要求全部复用旧 Protocol 类，但必须测试来源关联。
3. **两种结果分离：** 识别匹配/置信度不等于业务真值；输入 Job 成功不等于页面处理完成；每次业务提交需要之后新的视觉观察。
4. **过期拒绝：** Target 切换、导航、几何变化、来源过期、错误/取消/不确定输入时拒绝继续操作；不重试原来那组动作。
5. **可解释的并发：** 观察可周期执行；人类输入可随时到来；同一 Target 的点击事务需要串行协调，保证正在输入的对象不会被下一次观察/命令悄悄替换。
6. **同页更新风险：** 对于具体业务的十秒刷新，单纯 URL/几何指纹不足以证明题目未变化；必要时提交前重新视觉读取，提交后用视觉分数/回合状态确认。
7. **主动清理：** 关闭顺序要先停止入口/轮询、等待或安全中止 Maa Jobs 和 callbacks，再失效 bridge、关闭 Input/Capture/Session；不能在仍有 native 回调时释放其 Python 对象。
8. **默认最小权限：** 本机回环 CDP、隔离浏览器 profile、显式 Target、不得将端口暴露公网，不访问真实账户资源作为自动化测试前提。

---

## 4. 分阶段交付总表

| 子阶段 | 名称 | 实际目标 | 通过后新增的稳定能力 |
| --- | --- | --- | --- |
| **LITE-00** | Baseline Audit & Maa Setup | 现状审计、依赖与运行时、架构最小接口决策 | 可复现的安装/测试基线 |
| **LITE-01** | CDP ↔ Maa Controller | 真实 MaaFW 控制器截图/点击、安全桥接、坐标、取消与关闭 | 可靠浏览器底座 |
| **LITE-02** | Maa Vision & Plugin Contract | Maa Resource / 模板/OCR、最简业务插件 API、持续结构化观察 | 可复用的视觉业务插件基础 |
| **LITE-03** | Interactive CLI | 正式可安装 CLI、插件选择、异步输入与增量展示 | 人可以使用的终端应用 |
| **LITE-04** | Quiz Demo End-to-End | 独立网页、视觉答题插件、10s 换题、分数结算 | 第一个完整闭环产品样例 |
| **LITE-05** | Mahjong Soul Plugin | 实际游戏场景/牌面识别、手动命令与结果核验 | 首个真实业务适配 |
| **LITE-06** | Integration & Release | 回归、长时、故障、打包、文档和版本验收 | 可复现的 BCA-lite 发布基线 |

**阶段纪律：** 严格依序推进。每阶段 Codex 可以小步提交多个 commit；只有测试和证据齐备后才能声明“提交验收”。架构主会话的正式 Accepted 与 Codex 自述“测试通过”相互独立。

---

## 5. LITE-00 — 仓库与依赖基线审计

**任务：**

- 核对 `lite` 的实际提交、包依赖、工作树，验证只修改 lite。
- 在用户开发环境创建 `.venv`，记录 Python、Windows、Edge、`maafw`、NumPy、OpenCV 的版本与平台轮子可用性。安装当前 `[lite,dev]` 并执行 smoke import / 现有离线测试。
- 对照 **安装的 v5.16.1 API** 而不是假设源码，审计 `CDPBridge` 与 `MaaCDPController`；识别 C 回调错误传播、线程安全、截屏缩放、native 句柄释放、包 extras 的所有风险。
- 列出可直接复用的 BCA-01 Browser 代码以及旧 BCA-02～04 哪些要保留、只借鉴、停止维护；给出最小模块 API 和一张拥有者/清理顺序表。
- 明确 `.gitignore` 排除 `.venv`、临时 CDP profile、截图、模型下载、凭据；确定测试 Edge 的隔离启动方式。
- 不追求在这一阶段美化或删除所有旧模块；原则上仅修改必要依赖和修复阻塞测试运行的问题。

**验收：** 能用清晰的命令从新工作目录创建环境、导入 `maa`、导入 `bca.lite`；模拟单测和既有基础回归的运行结果可复核；已记录原生与绑定版本；审计报告列明按严重级别排序的问题及修复计划。

**交付：** `docs/lite/LITE-00_HANDOFF.md`（版本、命令输出、差异、风险、架构最小 API）；如遇阻塞附最小复现与结论。先交主会话讨论公共接口，再进入大规模改造。

---

## 6. LITE-01 — 稳定 MaaFramework CDP 控制器

**任务：**

- 修正/替换初版 `bridge.py`、`maa_controller.py`，用独立于 CDP owner loop 的 Maa callback 线程安全调用截图与输入；证明不会因为同步等待/重入锁/主动关闭而死锁。
- 将 MaaFW `CustomController` 实际截图原生回调接上 `BrowserCaptureProvider`，以 BGR ndarray 返回；检查 RGB/BGR、宽高、stride/continuous、内存持有及 16:9/非 16:9 分辨率。
- 依据 `CustomController` 的实际 `get_features()` 语义实现单次 Click，确认 Maa 采用直调 Click 还是 Down/Up 组合；仅实现本阶段必须的输入原语。
- 同一份可复现 HTML 测试页对照截图像素坐标 → Frame viewport → CSS 事件坐标；验证全图、区域情况、DPR 1/1.5/2、浏览器 zoom/scroll、Maa raw/非 raw 缩放。若不支持某配置，明确拒绝并给出诊断。
- 危险状态测试：目标页被销毁、切换/失联、导航、Resize、超时、异步取消、重复点击、原生任务关闭中回调、未知输入结果；不允许旧引用操作另一个页面。
- 设计有限多动作的**观察授权对象**及生命周期：为 LITE-04 的选项→确认做好可证明的顺序协议，但不要允许 arbitrary 第二次点击复用无效截图。
- 本机 Edge 由用户自己控制，CDP 仅回环，测试均针对独立测试页。

**验收：** Maa `Controller.post_connection/post_screencap/post_click` **真正从 Maa native 调用了 CDP bridge**；受控测试页 DOM 记录的点击 CSS 目标与预期位置一致；没有不可恢复死锁、未释放输入或失联后重新派发；测试提供截图/事件/线程日志。单纯 fake Session 5 个测试不足以通过。

**交付：** `docs/lite/LITE-01_HANDOFF.md`、可重复运行 smoke、真实 Edge 测试、故障测试、执行日志与坐标结果。保证公共 `Bridge` API 文档化。

---

## 7. LITE-02 — MaaFramework Vision + 轻量插件契约

**任务：**

- 通过真实 `MaaResource`/`MaaTasker` 接入 TemplateMatch 和 OCR（必要时引入 FeatureMatch/ColorMatch，不自写通用算法）。可以先从一个拥有确定字体和模板的小页面起步。
- 验证两条可行调用路线：`Tasker.post_recognition(type, params, image)` 的直接识别，以及加载 Bundle/Pipeline 后的 Tasker 识别；选择较少冗余的一条作为常规 API，并用实际识别详情测试分数/框坐标。
- 形成极小业务插件接口：插件 ID、资源装载/释放、识别为业务快照、格式化变化、解析用户命令、映射授权动作、查询读操作。该接口不应重新暴露一整套 Maa Controller/Tasker 或重造通用 Pipeline DSL。
- 定义业务快照版本与观察来源、稳定状态签名、`MATCHED/NOT_FOUND/AMBIGUOUS/ERROR` 等必要应用决策；在多候选/歧义时禁止猜测性点击。
- 检查 Maa Bundle/image/model 打包与路径安全、主题/场景资源选择的最小约定。只迁移真正需要的旧 BCA JSON/INI 语义 ID，不要求无损兼容旧 Manifest 与 weighted-RMSE 分数。
- 让至少一个简单插件对连续帧生成状态，按**业务内容**去重；恢复/错误状态应显式输出，且观察循环能被停止与重新启动。
- 观察周期目标至少 1Hz（有效观察而非空计时 tick）；时间戳和完成次数需要有测试可判断。

**验收：** 真实 Maa Vision 在 CDP 的截图上成功识别指定目标，能输出来源可信的区域/内容；正例、负例、歧义、尺度与不同字体样本覆盖；资源/模型可随 wheel 或项目独立打包被加载；不阻塞 CDP owner loop。

**交付：** `docs/lite/LITE-02_HANDOFF.md`、插件接口文档、素材 fixture/标签、Maa 识别性能记录。

---

## 8. LITE-03 — 可日常使用的交互式 CLI

**任务：**

- 添加正式入口（例如 `bca-lite` console script 或 `python -m bca.lite`），提供 `--help`、配置路径、CDP endpoint、Target 选择、插件选择与诊断输出。
- TOML 配置控制 CDP 地址、观察频率、插件资源目录、日志等级、输入/截图超时；建立合理默认值，保证凭据或私人数据不直接写日志。
- 输入与后台截图/识别并发：用户键入中后台可以更新，但要保持整行输入可编辑、避免打印不断打断输入；同题不重复刷屏、变化时打印提示。
- 命令队列串行化，完成之前拒绝或排队多次手动操作；只读查询能触发新视觉观察，不得用缓存假冒“现在的分数”。
- 显示关键诊断：Target 丢失、无法截图、识别歧义、输入结果未知、插件崩溃、关闭结果；日志细节与用户可读错误分层。
- Ctrl+C / EOF / 重复 stop 的完整关闭；确保 native Maa job、桥接线程、CDP 连接、插件资源按所有权依次回收。

**验收：** 在独立 Edge Target 上，用人工终端同时输入和观察，命令可执行、状态变化只输出一次、无竞争性重绘；对 Linux 等非主平台的兼容性不能假称已验。无浏览器离线测试能覆盖 CLI 路由、配置校验与取消。

**交付：** `docs/lite/LITE-03_HANDOFF.md`、最小配置样例、CLI 使用文档、交互记录与测试日志。

---

## 9. LITE-04 — Quiz Demo：必须完整跑通的垂直场景

这个阶段体现用户已确定的**真实产品需求**，不得在重构过程中缩减成纯脚本演示。

### 9.1 页面规格

页面提供：**一个题目显示框、A/B/C/D 四个选项按钮、一个确认按钮、一个分数框**。

- 题目显示一个随机 `0～9` 的一位整数，以固定但可通过截图可靠识别的字体显示。
- 四个选项各为一位整数，**互不重复且恰好一个与题目相等**；当前正确答案在 A/B/C/D 间变化。
- **每 10 秒**自动刷新一整题（至少改变题目数字），并重新计时；到期题目覆盖之前未提交的选择。
- 用户先点击选项，再点击“确认”才完成一次选择；正确则分数 `+1`，错误则 `-1`，允许负数、多位数和零分。
- **成功提交（不论答对答错）立即结算并异步生成下一题**，新题出现后重新开始 10 秒计时。
- 必须考虑倒计时恰好与选项/确认交叉：已经失效的选择不应被误算到下一轮。页面提供确定性测试种子/时钟注入以便回归。
- 页面可由本地静态文件/受控本地 HTTP 服务运行；视觉插件只从截图读取信息。DOM/JS 内部数据仅允许测试程序作为真值读取。

### 9.2 视觉插件的实时行为

- **≥1Hz 有效视觉读取**题目数字、四个选项内容以及需要时的分数。频率以完成的截图+识别为准，并输出测量值。
- 显示题目与选项；若这些内容没有变化不重复输出；内容变化时打印 **`【题目已更新】`** 和新题目、A/B/C/D。
- 支持输入 `A/B/C/D`（大小写兼容）然后回车：点击对应选项与确认；点击的位置必须来自当轮视觉识别/经授权的按钮目标，而非硬编码浏览器 CSS 或读取 DOM。
- 提交前后视觉读取分数，`+1` 通知回答正确，`-1` 通知错误，`0` 不当作答错，而是报告待结算/未知并在有限时间内重新观察；更大跳变或并发竞争需明确报告无法归属。
- 提交后读取新题，直到成功变更或显式超时/错误；**不以 `MaaJob.succeeded` 代表业务结算完成**。
- 输入 `?` 并回车，在任何时刻请求**新视觉观察**并显示当前分数；若正在提交，按已定义顺序在安全点执行；即使历史分数已缓存，也不得直接把缓存冒充实时读取。
- 截图失败、OCR 未读出数字、歧义、页面换题、点击未确认、Target 丢失、关闭过程中均具有明确状态与安全路径。

### 9.3 必备验收矩阵

| 维度 | 必测事项 |
| --- | --- |
| 页面计时 | 10 秒刷新、提交后即时刷新并重新计时、旧选择失效 |
| 视觉数据 | 题目 `0～9`、四个按钮、正确项随机位置、零/负/多位分数、易混字符 |
| 命令 | A/B/C/D 正误、大小写、无效输入、输入中题目变化 |
| 查询 | `?` 真正重新截图；提交中有序查询；识别失败返回未知而非旧值 |
| 结算 | `+1`、`-1`、`0` 未结算、并发导致无法归属、题目已刷新 |
| 安全 | 截图与点击之间切换 Target/导航/改变 DOM；无旧题误操作 |
| 频率与性能 | ≥1Hz 有效更新、命令→结算延迟 median/p95、CPU 和内存 |
| 生命周期 | Ctrl+C、截图超时、Maa job 取消、退出后无悬挂回调和输入 |

**验收：** 真正在 Windows/Edge 的受控页面上运行至少跨越多次自动换题；由真人或自动化终端输入完成多轮正确与错误作答、查分和退出；提供截图/识别/DOM oracle 及分数轨迹相互一致的原始证据。纯模拟测试或 HTML 能单独跑不算通过。

**交付：** `docs/lite/LITE-04_HANDOFF.md`、示例网页、插件与素材、可复现的回归脚本和演示使用方法。它应成为以后 Majsoul 与升级 MaaFW 的长驻集成测试基线。

---

## 10. LITE-05 — Mahjong Soul / 雀魂业务插件

**目标：** 将固定示例推广到真实 WebGL 网页游戏，实现对目标页面的稳定视觉状态读取、结构化输出和手动命令操作，复用 MaaFW 资源与识别能力，而不是为了雀魂写死一套公共 Core。

**建议业务阶段：**

1. `MJS-01` 页面和场景识别：未进入对局、加载、等待、牌桌、轮到自己、结算等可见场景，输出未知/低置信状态。
2. `MJS-02` 手牌和公开信息识别：梳理牌面语义 ID、候选区域与多外观模板，建立来自真实截图的标注集合，处理吃碰杠等操作按钮；实际可观测范围以截图与游戏规则为准。
3. `MJS-03` 手工命令与视觉核验：CLI 将合法操作映射成“选择 → 执行 → 再观察”，每次操作前确认场景/回合/目标，报告实际是否发生，不替用户做不可靠猜测。
4. `MJS-04` 真实浏览器测试：DPR、缩放、窗口尺寸、场景切换、动画、识别不确定与网络延迟；避免在没有实际页面资料时臆造识别效果。

**插件边界：** 麻将规则、牌码、操作按钮和场景语义在 `plugins/majsoul` 内；Maa `Resource/Template/OCR` 负责视觉；BCA-lite 协调层负责 CDP 与安全动作。训练/测试数据来自用户实际有权使用的素材或截图，尽量剥离账户标识、聊天和私人数据。

**验收：** 不能只提供 UI 假截图或空 `plugin.toml` 就宣布“雀魂适配完成”。必须列出已支持的可见场景和命令、每个场景的截图标签样本、真实浏览器验证证据与仍未覆盖的情况。如果某些场景因缺少真实素材/测试环境无法完成，应如实标为部分交付，不影响前面已通过的 lite 通用组件。

**交付：** `docs/lite/LITE-05_HANDOFF.md`、场景/命令表、资源采集与标注方案、测试样本集、实际验证记录。

---

## 11. LITE-06 — 系统验收、可发布版本与迁移收尾

- 全量验证 LITE-01～05 接口、装载、观察和输入，运行完整 Quiz 与已覆盖的雀魂真实用例；复测导航失效、连接断开、异步取消、异常退出、输入不确定、资源清理。
- 安装矩阵：无开发依赖的独立 venv、wheel/sdist、Windows Python 版本；MaaFW native 包、OCR 模型/图像资源的版本/路径/分发体积及离线可用性。不要把当前 CI 不能覆盖的平台写成“支持”。
- 检查 CPU、内存、长时间观察的泄漏与线程/Job 数；性能统计分开记录 Capture、解码、Maa Recognition、状态转换、Input、业务结算，报告 median/p95 和样本数。
- 整理旧 BCA Runtime/Plugin SDK 代码：只在完成新架构的真实验证后决定哪些成为 historical/legacy、哪些仍被引用；删除或迁移前分析所有 import、测试与公开依赖，不进行破坏历史的重写。
- 完成错误提示、安装、配置、安全说明、例子、版本兼容策略、LICENSE/NOTICE 和上游 LGPL-3.0 义务核对；确认不会误把 MaaAssistantArknights 的应用素材/代码当作 MaaFramework 可自由复制资源。
- 准备新架构最终图和完整发布交接。新的 lite 状态不能沿用 BCA-04 的 805 tests/360 clicks 当作本次测试。

**正式验收交付：** `docs/lite/LITE-06_HANDOFF.md`、`docs/lite/BCA-LITE_MAIN_SYNC.md`、安装与运行文档、原始测试证据（日志/JSON/测试覆盖表）。由架构主会话确认可发布基线后再研究是否将 `lite` 合并至 `main`；**不得自动合并**。

---

## 12. 全阶段质量、接口与证据要求

### 12.1 静态与测试命令（按环境/选装依赖调整）

```powershell
# 注意：先安装工具和 [lite]，并记录版本
python -m pip install -e ".[lite,dev]"
python -m pytest -q -W error
python -m mypy
python -m ruff check .
python -m ruff format --check .
python -m build

# 真实浏览器仅在用户显式启动隔离 Edge 后进行
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9341"
python -m pytest -q -W error
Remove-Item Env:BCA_CDP_ENDPOINT
```

Codex 应先确认项目真实 pytest marker、MaaFW optional import 及类型检查策略，避免因缺少浏览器而给出虚假“全部通过”。记录 Windows/Python/Edge/MaaFW 版本、通过数/跳过数/失败数与实际执行时间；不能把“写了测试”说成“运行了测试”。

### 12.2 核心故障矩阵

- Target 已解绑/销毁/导航中、同 Target URL 不变但 DOM/回合已更新；
- 截图时 DOM、滚动、Viewport、DPR 变化；Maa 控制器图像分辨率经过缩放；
- C 回调在不同线程、重入/锁竞争、native job still running 时关闭；
- 输入下发成功但 ack 丢失、输入未知、Maa job timeout/cancel；
- 多个 CLI 命令连续到达、用户正在键入时页面自动变化；
- Vision/OCR 正负例、歧义、假阳性、性能过慢；
- 初次无目标、连接中断和重连、正常停止、异常停止与可重复启动。

### 12.3 报告的最低证据格式

每个 `LITE-XX_HANDOFF.md` 必须包含：

1. **基线**：实际 Git 分支/起止 commit、Python/MaaFW/Edge 环境、依赖约束。
2. **范围**：目标、实际完成、与本任务书的偏差及原因、未实现但影响后续使用的能力。
3. **接口**：真正公开的类/函数/配置项、坐标单位、所有权和异常语义；实际示例调用。
4. **源码索引**：关键路径及其职责，重要代码变更和兼容性风险。
5. **测试证据**：执行命令、结果统计、浏览器实测条件、原始 JSON/log、失败用例、截图与必要的独立 DOM oracle。
6. **性能**：定义每个耗时口径、硬件/样本量、median/p95、是否包括 browser capture、native inference、CLI 输出。
7. **资源与安全**：Timeout、取消、关闭顺序、未知输入阻塞与恢复、存留进程/线程。
8. **交接**：下一阶段所需 API、已知缺陷、未覆盖场景、可以复现的最小命令。

报告不要仅靠 README 自述或测试名称来宣布通过；“已实现/已测试/已在真实浏览器验证/已被主会话正式验收”是不同等级的事实。

---

## 13. 分支协作和文档维护

- 开发目标仅 `lite`。`main` 现有 BCA-00～04 作为历史已验收归档，不自动覆盖或回写。
- Codex 开发时每次以实际工作树和本地新增改动为准，勿强制 reset、force push、删除未跟踪用户文件。
- 每个子阶段开发过程中可提交有意义的小 commit；收尾写 `LITE-XX_HANDOFF.md`，附实际 commit 与运行证据。
- **沿用既定大阶段验收规则：每次正式大阶段 Accepted，必须同步更新 `BCA_PROJECT_CONTEXT.md` 和 GitHub README。** 在 `lite` 开发期，对应仓库内 `docs/md/BCA_PROJECT_CONTEXT.md`（如需则新增明确的 lite 版段落）与 `lite` 分支 README；用户 ChatGPT 项目共享的 `BCA_PROJECT_CONTEXT.md` 也应由架构主会话同步替换。重大技术路线调整则另给 `BCA-LITE_MAIN_SYNC.md` 以避免覆盖历史事实。`main` 不在 lite 验收时自动改动。
- 临时阶段讨论不需要频繁更新首页；**正式验收时**再反映已经完成的能力、可复核测试和下一阶段方向。
- 避免重复写“某功能不实现”；以真实实现范围和验收边界为准。

---

## 14. Codex 的第一轮执行指令（可直接交给 Codex）

你现在位于 BCA-lite 新工作目录，分支应为 `lite`。请将 **本文件作为最高优先级的项目阶段任务书**，同时阅读仓库现有代码、历史交接 MD，以及锁定版本的 MaaFramework API。第一轮只需完成 **LITE-00 审计与 LITE-01 基础控制器集成**，之后按本文件顺序分阶段继续开发完整 BCA-lite。

具体要求：

1. 执行 `git status`、`git branch --show-current`、`git rev-parse HEAD`，核对真实基线，检查本地用户改动。
2. 阅读 `src/bca/core/browser/`、`src/bca/lite/`、`tests/lite/`、`examples/lite_maa_cdp_smoke.py`、`pyproject.toml` 及第 0.2 节所列历史交接文档；按需追查代码调用栈。
3. 对照 MaaFramework v5.16.1 的实际 Python Binding 和 C API，审查已有桥接：同步/异步、BGR、坐标、缩放、线程、取消、输入结果不确定和关闭归属。列出影响可运行性的阻塞项。
4. 在用户开发环境安装依赖并运行离线测试。根据实际测试修正现有 bridge；不破坏 `main`，不要大范围删除旧代码。
5. 通过隔离 Edge CDP 真实截图和像素坐标验证 Maa `CustomController`；没有真实浏览器时可先完成离线改造，但报告须明确真实验收仍未完成，不得虚构。
6. 按 LITE-00/LITE-01 输出接口、测试结果、日志和交接 MD；发生重要架构差异先向主会话提交设计变更说明。
7. LITE-01 阶段交付通过后，再推进 Maa Resource / Vision、CLI、Quiz Demo、雀魂和系统收尾。不得为了追求阶段数量忽略真实端到端验证。

**首轮回复请先简明展示：仓库真实状态、已读资料、目前桥接的 3～5 个最高优先级风险、准备修改的文件与测试命令。随后直接开展 LITE-00 工作，并在有证据时推进 LITE-01。**

---

## 15. 变更日志

- **v1.0 / 2026-11-23**：创建 BCA-lite 主交接书；基于 `lite@88ba80e` 与 MaaFW v5.16.1；明确实验桥接状态、7 个子阶段、Quiz Demo 与雀魂目标、证据/安全/双文档归档规则。架构主会话仅生成交接文件，未由本文件修改任何 GitHub 分支。
