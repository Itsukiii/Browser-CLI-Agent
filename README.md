# Browser CLI Agent (BCA)

> **BCA-lite / `lite` 分支 — 当前研发路线。** 本分支采用 [MaaFramework v5.16.1](https://github.com/MaaXYZ/MaaFramework) 作为通用视觉与任务底座，BCA 自身保留 Chromium/Edge CDP Target 控制、可信观察授权与后续终端交互。**LITE-00 已交付；LITE-01 CDP × Maa 于 2026-11-24 Accepted；LITE-02 Vision & Plugin 和 LITE-03 Interactive CLI 均于 2026-11-26 正式 Accepted；当前启动 LITE-04 Quiz Demo。** 历史 BCA-00～04 的完整基线保留在 [main](https://github.com/Itsukiii/Browser-CLI-Agent/tree/main)。

### BCA-lite 当前进度

| 阶段 | 状态 | 交接 / 证据 |
| --- | --- | --- |
| LITE-00 · 基线审计 | 已交付 | [审计](docs/lite/LITE-00_HANDOFF.md) |
| **LITE-01 · Maa CDP Bridge** | **Accepted（2026-11-24）** | [验收结论](docs/lite/LITE-01_ACCEPTANCE_2026-11-24.md) · [交接](docs/lite/LITE-01_HANDOFF.md) · [最终 G1/G2 证据](docs/evidence/LITE-01-addendum/final-2026-11-24/) |
| **LITE-02 · Maa Vision / Plugin** | **Accepted（2026-11-26）** | [正式验收](docs/lite/LITE-02_ACCEPTANCE_2026-11-26.md) · [阶段索引](docs/lite/LITE-02_HANDOFF.md) · [02.3 证据](docs/evidence/LITE-02/02.3/README.md) |
| **LITE-03 · Interactive CLI** | **Accepted（2026-11-26）** | [正式验收](docs/lite/LITE-03_ACCEPTANCE_2026-11-26.md) · [交接](docs/lite/LITE-03_HANDOFF.md) · [CLI 用法](docs/lite/CLI.md) |
| **LITE-04 · Quiz Demo** | **设计准备** | [启动交接](docs/lite/LITE-04_KICKOFF_2026-11-26.md) · [完整规格](docs/md/BCA-LITE_MASTER_HANDOFF.md) |
| LITE-05～06 · 雀魂 / Release | 规划中 | [总交接书](docs/md/BCA-LITE_MASTER_HANDOFF.md) |

#### LITE-03 已验收的交互式 CLI

- 正式入口 `bca-lite` / `python -m bca.lite`，PowerShell 上使用 `prompt_toolkit` 保持可编辑输入、后台增量更新和单条命令串行；TOML 配置/CLI 参数、精确 Target 选择、`--check`/`--list-targets`/`--once`、显式 fixture 插件。
- 已验收操作：`?` 强制拍摄新图；`click <visible-round>` 基于 Maa 可见回合和唯一视觉候选执行单步安全点击；`stop`/`resume`/`quit`、Ctrl+C、EOF 和失效/unknown 提示。不把输入确认冒充页面业务结算。
- Windows/Edge ConPTY **7 passed**，全新 wheel+系统 Temp cwd ConPTY **6 passed**，过期观察单独 **1 passed**；人工 PowerShell 记录的 `click123→124→125` 与三次 `?` 新帧可复核。CLI 65 秒周期运行 **87/87 有效，1.31495Hz**，同内容只输出一次状态。
- 最终离线 **907 passed / 66 deselected**（浏览器测试单独执行），mypy strict、Ruff、build 与干净 wheel 安装通过。原生未释放则结束 CLI 自有进程（exit3），不重试不确定指针；原有浏览器 Target 保留。
- **体验与性能边界：** 实际中文 IME 候选窗、退格、闪屏体验暂无明确人工确认；单进程 CPU 监控约 **397%（约3.97逻辑核）**，测试期间有其他构建/安装活动，不与 LITE-02 的 3.26 核直接作性能回归判断；历史 OpenCV access violation 仍未归因。

配置与运行（需先准备隔离 CDP Edge、OCR 模型和来源 manifest，详见 CLI 文档）：

~~~powershell
bca-lite --help
bca-lite --endpoint http://127.0.0.1:9341 --list-targets
bca-lite --config configs/lite.example.toml --create-fixture
~~~

完整使用方式见 [CLI.md](docs/lite/CLI.md)。目前生产 CLI 的内置插件为受控 `fixture`，LITE-04 将接入正式 Quiz 示例。

#### LITE-02 已验收的 Vision / Plugin 基础

- `MaaVisionFacade` 独占单 native worker，实际 Maa TemplateMatch / OCR、Bundle 和显式哈希校验模型；`RecognitionBatch` 保存精确 `ObservationRef`、坐标、歧义/错误/超龄语义，模型二进制不进入发行包。
- `BusinessPlugin` 负责纯业务 plan/observe/format/parse/resolve；`ObservationCoordinator` 负责新帧观察、业务 signature 去重、可见 `interaction_revision`、单门串行操作及 native Job 与本次 CDP 输入确认一致性。点击结果 `confirmed` 不代表业务已经结算。
- **真实 Edge**：12 组 DPR1/1.5/2 × raw/nonraw × 全图/ROI、80%/100%/125% 桌面缩放；OCR 负数/多位/字体变化、缺失/歧义安全拒绝、视觉定位点击后 DOM 核验；歧义时只允许显式 ROI 和新观察恢复。
- **长时**：185.0128s、245 次完成、239 次有效、**1.2918Hz**；应用进程树平均 CPU 约 **325.63%（约 3.26 个逻辑核）**、峰值 RSS 约 **164.60MiB**（树内共享页可能重复计数）；LITE-03/06 需要针对目标机器评估 CPU 预算。
- **稳定性**：legacy / Maa / 双向混合各三轮共 12 个独立进程正常退出；旧 OpenCV access violation 本轮未复现、**仍未归因**。Native stop 成功但 running 暂未归零时有至多 1s 的状态等待，无法确认 idle 仍保留句柄。
- **发行**：干净 venv 安装 wheel[lite]、临时 cwd 资源加载、OCR 模型哈希拒绝、真实 Edge wheel 示例通过。最终离线记录 **878 passed / 57 deselected**（浏览器测试单独记录，不与旧轮次累加）。

使用已准备好的隔离 Edge、本地 OCR 模型及来源 manifest 体验真实端到端示例：

~~~powershell
python examples/lite_vision.py --endpoint http://127.0.0.1:9341 --model "ABSOLUTE_MODEL_DIRECTORY" --manifest "ABSOLUTE_MANIFEST_JSON"
~~~

> 此旧示例仅演示受控自有网页的单次视觉交互；已交付的正式交互式入口及具体使用见上方 LITE-03 和 CLI 文档。

#### LITE-01 已验证能力

- Python `maafw==5.16.1` native 控制器通过 CDP 绑定显式 Edge Target；BGR 全图/区域截图、raw/non-raw 缩放、像素到 CSS 映射和单次点击。
- 一次性 `ObservationRef` 授权、固定 Target 身份、取消排空、原生对象生命周期、未知输入结果阻断及无重试。
- 报告中的原始证据：先前 12 组 DPR/ROI/raw 矩阵 36 次点击；新增 Edge **80%/100%/125% × raw/non-raw** 六组，最大误差 **0.993598 CSS px**；真实代理 G2 丢 ACK、断连、关闭竞争；最终 **29 passed / 0 skipped** 的完整 lite 测试集合。
- 相关离线证据为 786 passed / 50 skipped（单独轮次），Python 3.14.7 / Windows 11 / Edge 158；未把这些结果宣称为 OCR、CLI 或雀魂真实业务验收。

在 Windows 开发环境安装已验证的基础集成：

~~~powershell
git switch lite
python -m pip install -e ".[lite,dev]"
python examples/browser_session.py --endpoint http://127.0.0.1:9341
python examples/lite_maa_cdp_smoke.py --endpoint http://127.0.0.1:9341 --target-id YOUR_TARGET_ID
~~~

> 下文所述 BCA-00～04 Runtime、Plugin System 和 Vision SDK 是**已保留的原架构资料**，不是 BCA-lite 的当前主集成路线；原 CLI 开发计划以 [LITE 总交接书](docs/md/BCA-LITE_MASTER_HANDOFF.md) 为准。


**一个面向浏览器页面的可扩展感知与输入控制框架。**

Browser CLI Agent（BCA）将浏览器连接、截图采集、页面状态解析和命令执行分离。Core 提供通用的 Browser、Provider、Runtime 和 Plugin 能力；具体页面的识别、状态格式和交互规则由插件提供。项目目标是在终端中读取指定页面的结构化信息，并通过命令与该页面交互。

**历史基线：BCA-00～04 均完成原架构阶段验收。** 这些源码和示例保留用于回归和参考；当前 lite 开发顺序为 LITE-04 Quiz → LITE-05 雀魂 → LITE-06 集成发布。

> 当前 lite 分支具备已验收的 MaaFramework-CDP 控制器、视觉 OCR/模板、业务插件、持续观察和交互式 CLI；Quiz 与雀魂业务插件按后续阶段推进。

## 功能与模块

| 模块 | 当前交付内容 | 文档 |
| --- | --- | --- |
| **Protocol / BCA-00** | 冻结数据模型、统一错误体系、显式 JSON codec、Provider / Plugin 契约 | [Interfaces](docs/INTERFACES.md) |
| **Browser / BCA-01** | 本机 CDP 连接、目标发现与绑定、PNG 全图/区域截图、CSS 坐标映射、七类鼠标/键盘输入 | [Browser](docs/BROWSER.md) · [交接](docs/BCA-01_MAIN_SYNC.md) |
| **Runtime / BCA-02** | Scheduler、StateStore、EventBus、观察管线、FIFO 动作批次、可信观察引用、取消与显式恢复 | [Runtime](docs/RUNTIME.md) · [交接](docs/BCA-02_MAIN_SYNC.md) |
| **Plugin System / BCA-03** | 静态 Manifest 发现、可信本地模块加载、版本及能力校验、插件生命周期、Provider 视图和 Runtime Host | [Plugin Spec](docs/PLUGIN_SPEC.md) · [交接](docs/BCA-03_MAIN_SYNC.md) |
| **Vision & Assets / BCA-04** | JSON Manifest、INI Profile、多变体模板、只读像素与 LRU 缓存、Frame 解码、ROI、缩放、加权模板匹配与歧义结果 | [Assets](docs/ASSETS.md) · [Vision](docs/VISION.md) · [交接](docs/BCA-04_MAIN_SYNC.md) |

### 工作链路

~~~text
                   Application / future CLI
                      |              ^
                   Command      PageState / BatchResult
                      v              |
                 PluginRuntimeHost
                      |
                   PluginManager
                    /       \
                 observe   parse / handle
                   |            |
                 Frame       ActionBatch
                   |            |
            CaptureProvider     v
                   |       RuntimeController
            BrowserFreshness    |
                   |       InputProvider
                   +------- BrowserSession ------> Chromium / Edge (CDP)

       Scheduler · StateStore · EventBus · ProviderLookup
~~~

- **观察：** 截图 → 可选 Vision SDK 解码/模板匹配 → 插件业务识别 → PageState → Runtime 单次提交 → 上层读取结构化状态。
- **操作：** 命令解析 → 插件映射 Action → ActionBatch → Runtime 验证来源和顺序 → 浏览器输入 → 再次观察。
- **坐标：** 截图像素转换为 CSS viewport 坐标，使用 Frame.pixel_to_css()；不重复应用 DPR 或滚动偏移。
- **执行语义：** 输入 SUCCEEDED 只表示输入已被确认，实际网页效果需要下一次观察验证。

更多架构细节参阅 [ARCHITECTURE.md](docs/ARCHITECTURE.md) 和 [INTERFACES.md](docs/INTERFACES.md)。

## 开发环境与安装

- Python **3.12+**；当前阶段实际验证环境为 Windows / Python 3.14.7 / Edge 157，Python 3.12/3.13 的实机矩阵仍待补齐。
- 优先 Windows 与 Chromium / Microsoft Edge。
- 基础运行依赖：websockets 15.x、Pillow 12.x；`[assets]` 增加 NumPy，`[vision]` 增加 NumPy 与 OpenCV headless；具体版本范围见 pyproject.toml。
- 真实浏览器集成测试使用显式配置的本机回环 CDP 端点。

在仓库根目录执行（Windows PowerShell）：

~~~powershell
git clone https://github.com/Itsukiii/Browser-CLI-Agent.git
cd Browser-CLI-Agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
~~~

Linux/macOS 将虚拟环境解释器路径替换为 .venv/bin/python；浏览器行为仍需按对应平台验证。常规包安装可使用 python -m pip install .。

## 快速体验

### 1. 无浏览器：运行插件闭环

~~~powershell
.\.venv\Scripts\python.exe examples/plugin_runtime.py
~~~

该示例使用模拟 Provider，完成 Catalog 发现、加载、Manager 初始化、Runtime 状态发布以及 Host 命令到 ActionResult 的整条调用链，不会操作真实页面。

其他模拟示例：

~~~powershell
.\.venv\Scripts\python.exe examples/runtime_basics.py
.\.venv\Scripts\python.exe examples/runtime_observation.py
.\.venv\Scripts\python.exe examples/runtime_actions.py
~~~

### 2. 真实浏览器：使用隔离 CDP 实例

使用独立用户数据目录启动自己控制的 Edge 或 Chromium，并显式启用本机调试端口。例如在 Windows PowerShell 中运行（安装位置可能不同）：

~~~powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9341 --remote-debugging-address=127.0.0.1 --user-data-dir="$PWD\.test-artifacts\edge-bca-demo" --no-first-run --no-default-browser-check about:blank
~~~

**注意：** 调试端口仅绑定本机，勿公开到外部网络；不要复用已登录个人账户的浏览器配置目录。示例自行创建并清理测试 Target，不主动关闭外部已存在的浏览器实例。

Browser 基础示例：

~~~powershell
.\.venv\Scripts\python.exe examples/browser_session.py --endpoint http://127.0.0.1:9341
.\.venv\Scripts\python.exe examples/browser_end_to_end.py --endpoint http://127.0.0.1:9341 --output .test-artifacts/browser-demo
~~~

### 3. 真实插件：截图、识别、点击、再观察

~~~powershell
.\.venv\Scripts\python.exe examples/plugin_integration.py --endpoint http://127.0.0.1:9341 --output .test-artifacts/plugin-demo --samples 3 --duration 3
~~~

此示例使用受控测试页面和像素识别插件：PNG 截图 → Plugin.observe → PageState / StateStore → Host.execute_text → Input → 新截图及 DOM 独立验证。覆盖 DPR 1/1.5/2、全图/区域，并记录动作、状态与帧的关联信息。

组合与运行时参考实现见 [plugin_browser.py](examples/plugin_browser.py)、[runtime_integration.py](examples/runtime_integration.py)。该测试示例不代表已在雀魂生产业务页面验收。

## 资源与视觉识别 SDK

BCA-04 在 `bca.plugin_sdk.assets` 与 `bca.plugin_sdk.vision` 提供独立的资源及视觉工具。安装与演示：

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,assets,vision]"
.\.venv\Scripts\python.exe examples/asset_foundation.py
.\.venv\Scripts\python.exe examples/vision_foundation.py
~~~

- **Assets：** JSON Manifest 定义稳定语义 ID 与多模板变体，INI Profile 选择主题/场景；`AssetStore` 支持解析、按需加载、缓存与显式失效，返回只读 RGB 像素及权重 Mask。
- **Vision：** `decode_frame` 完整校验 PNG/JPEG；`match_frame` / `match_templates` 支持 RGB/GRAY、ROI、两轴缩放和加权 RMSE 模板匹配，输出 `MATCHED`、`NOT_FOUND` 或 `AMBIGUOUS`。默认 0.96 是像素相似度阈值，并非识别正确概率。
- **坐标与安全：** `MatchCandidate` 使用来源 Frame 的像素坐标；插件用 `frame.pixel_to_css(*candidate.center)` 形成 CSS 视口动作。视觉结果不替代 Runtime 的来源授权；歧义需要由业务插件明确处置。
- **异步与性能：** 同步计算可在插件中通过 `asyncio.to_thread` 卸载，并须等待取消时的原生工作完成。提前确定 ROI 与尺度通常能明显降低计算时间。

真实 Edge 视觉插件集成入口：

~~~powershell
.\.venv\Scripts\python.exe examples/vision_integration.py --endpoint http://127.0.0.1:9341 --samples 3
~~~

该示例针对受控测试页面，验证主题、DPR、区域截图、来源引用和输入后的页面变化。公开 API 和示例详情见 [ASSETS.md](docs/ASSETS.md)、[VISION.md](docs/VISION.md) 与 [BCA-04 交接](docs/BCA-04_MAIN_SYNC.md)。

## 插件开发与装配

插件存放在显式配置的可信目录下，例如：

~~~text
plugins/
  example/
    plugin.toml
    __init__.py
~~~

Manifest 示例：

~~~toml
[plugin]
plugin_id = "example"
version = "0.2.0"
protocol_version = 2
required_capabilities = ["capture", "input"]
factory = "create_plugin"
~~~

- **PluginCatalog** 静态读取 Manifest 并筛选候选插件；重复 ID 会产生诊断并拒绝选择。
- **PluginLoader** 仅加载选定的本机插件包；支持相对导入，工厂同步创建实例。加载本机插件会执行 Python 代码，所以插件根目录必须可信。
- **PluginManager** 注入 PluginContext，校验所需能力并管理 initialize / start / stop / close。PluginSnapshot 报告生命周期状态与清理诊断。
- **ProviderLookupView** 提供只读能力查询；**FreshnessCaptureAdapter** 将浏览器截图接入 BrowserFreshness 的来源校验。
- **PluginRuntimeHost** 组合 Manager、RuntimeController 和 StateStore，通过 execute_text() 协调命令、观察引用和 ActionBatch。

插件的 observe() 返回 PageState，由 Runtime 统一 publish；handle_command() 返回 Action 列表，由 Runtime 统一执行。Application 拥有 Session、Provider、Store/Bus 及自建 Target 的清理责任；Host 管理 Controller 与插件 Manager。清理状态 CLOSED 不应直接等同资源完全释放成功，必要时检查 cleanup_status / cleanup_error。

详细开发规范与实际签名见 [PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md)、[03.1 交接](docs/BCA-03.1_HANDOFF.md)、[03 正式交接](docs/BCA-03_MAIN_SYNC.md)。

## 测试与质量

普通测试默认不需要真实浏览器。要运行真实 CDP 测试，需要先启动已授权的独立浏览器实例，并设置 BCA_CDP_ENDPOINT。

~~~powershell
# 默认：非浏览器测试（真实集成项按配置跳过）
.\.venv\Scripts\python.exe -m pytest -q -W error

# 类型、风格、构建
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build

# 已启动隔离 Edge / Chromium 后执行真实测试
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9341"
.\.venv\Scripts\python.exe -m pytest -q -W error
Remove-Item Env:BCA_CDP_ENDPOINT
~~~

**BCA-03 阶段历史交接报告（Windows / Python 3.14.7 / Edge 157）：**

| 验证项目 | 报告结果 |
| --- | --- |
| 全量测试（专用 CDP） | **533 passed / 0 skipped** |
| 全量测试（无 CDP） | **497 passed / 36 skipped** |
| 新增插件真机专项 | **24 passed** |
| DPR 1 / 1.5 / 2、全图/区域点击矩阵 | 3 轮合计 **54 次成功** |
| mypy strict / Ruff / wheel / sdist | 通过 |

交接性能样本：execute_text 到 BatchResult 的 median/p95 为 **6.34 / 18.90 ms**；命令至下一状态提交为 **67.16 / 96.09 ms**。这些包含上层协调及校验步骤，不是裸浏览器截图或通用网页的性能保证。详细测量边界参阅 [03.2 HANDOFF](docs/BCA-03.2_HANDOFF.md)、[性能 JSON](docs/BCA-03.2_PERFORMANCE.json)。

**BCA-04 正式交接报告（Windows 11 / Python 3.14.7 / Edge 157）：**

| 验证项目 | 报告结果 |
| --- | --- |
| 全量测试（专用 CDP） | **805 passed / 0 skipped** |
| 全量测试（无 CDP） | **760 passed / 45 skipped** |
| 视觉固定标签集 | **76 场景**：32 正例、32 负例、6 歧义、6 双位置均符合预期 |
| 真实 Edge 视觉闭环 | 两主题 × DPR 1/1.5/2 × 全图/区域：**360 次点击成功** |
| 坐标验证 | Action 浮点请求最大偏差 0.5 CSS px；DOM 整数事件最大偏差 1 CSS px |
| mypy strict / Ruff / wheel / sdist / 独立安装矩阵 | 报告全部通过 |

Vision 耗时随 DPR、ROI、模板数量与尺度显著变化：交接样例中 light / DPR 2 的全图 Vision total 中位 **385.60 ms**，区域为 **65.36 ms**。区域视觉计算更快，但区域截图仍可能经历浏览器完整 surface 捕获，不能把算法耗时等同纯截图耗时。完整原始数据见 [04.2 交接](docs/BCA-04.2_HANDOFF.md) 与 [验证汇总](docs/evidence/BCA-04.2/verification.json)。

上述数字来自各阶段测试报告，不代表本次 README 更新重新执行了测试；仍需补充 Python 3.12/3.13、长时间压力、native/Edge RSS 和真实游戏/WebGL 页面验证。

## 路线图

| 阶段 | 主题 | 当前状态 |
| --- | --- | --- |
| BCA-00 | Protocol / 公共契约 | 已验收 |
| BCA-01 | Browser / CDP、截图与输入 | 已验收 |
| BCA-02 | Runtime / 状态、调度与动作 | 已验收 |
| BCA-03 | Plugin System / 插件管理与 Host | 已验收 |
| BCA-04 | Vision & Assets / 图像识别与资源管理 | 已验收 |
| BCA-05 | CLI / 终端应用 | 规划中 |
| BCA-06 | Majsoul / 雀魂适配 | 规划中 |
| BCA-07 | Integration / 全系统验证 | 规划中 |

完整规划与阶段历史见 [DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)。

## 文档索引

- **核心规范：** [ARCHITECTURE.md](docs/ARCHITECTURE.md) · [INTERFACES.md](docs/INTERFACES.md) · [BROWSER.md](docs/BROWSER.md) · [RUNTIME.md](docs/RUNTIME.md) · [PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md)
- **跨模块交接：** [BCA-01](docs/BCA-01_MAIN_SYNC.md) · [BCA-02](docs/BCA-02_MAIN_SYNC.md) · [BCA-03](docs/BCA-03_MAIN_SYNC.md)
- **插件交付证据：** [BCA-03.1_HANDOFF.md](docs/BCA-03.1_HANDOFF.md) · [BCA-03.2_HANDOFF.md](docs/BCA-03.2_HANDOFF.md)
- **视觉与资源：** [ASSETS.md](docs/ASSETS.md) · [VISION.md](docs/VISION.md) · [BCA-04_MAIN_SYNC.md](docs/BCA-04_MAIN_SYNC.md) · [BCA-04.1_HANDOFF.md](docs/BCA-04.1_HANDOFF.md) · [BCA-04.2_HANDOFF.md](docs/BCA-04.2_HANDOFF.md)
- **项目路线：** [DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)

---

BCA 采用 **通用 Core + 可替换 Provider + 页面专属 Plugin** 的方式组织能力，让识别与输入可以在稳定的状态、动作和生命周期契约下组合。