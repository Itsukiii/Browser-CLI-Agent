# Browser CLI Agent (BCA)

**一个面向浏览器页面的可扩展感知与输入控制框架。**

Browser CLI Agent（BCA）将浏览器连接、截图采集、页面状态解析和命令执行分离。Core 提供通用的 Browser、Provider、Runtime 和 Plugin 能力；具体页面的识别、状态格式和交互规则由插件提供。项目目标是在终端中读取指定页面的结构化信息，并通过命令与该页面交互。

**当前进度：BCA-00～03 已完成阶段验收。** 核心协议、Chromium/Edge CDP 适配、异步 Runtime 和插件系统均已交付，并提供模拟与受控浏览器集成示例。下一阶段为 **BCA-04 / Vision & Assets**，之后是终端 CLI 与首个业务插件——雀魂（Mahjong Soul）。

> 当前仓库提供可运行的框架与集成示例。统一交互式产品 CLI 和雀魂业务插件将在后续阶段交付。

## 功能与模块

| 模块 | 当前交付内容 | 文档 |
| --- | --- | --- |
| **Protocol / BCA-00** | 冻结数据模型、统一错误体系、显式 JSON codec、Provider / Plugin 契约 | [Interfaces](docs/INTERFACES.md) |
| **Browser / BCA-01** | 本机 CDP 连接、目标发现与绑定、PNG 全图/区域截图、CSS 坐标映射、七类鼠标/键盘输入 | [Browser](docs/BROWSER.md) · [交接](docs/BCA-01_MAIN_SYNC.md) |
| **Runtime / BCA-02** | Scheduler、StateStore、EventBus、观察管线、FIFO 动作批次、可信观察引用、取消与显式恢复 | [Runtime](docs/RUNTIME.md) · [交接](docs/BCA-02_MAIN_SYNC.md) |
| **Plugin System / BCA-03** | 静态 Manifest 发现、可信本地模块加载、版本及能力校验、插件生命周期、Provider 视图和 Runtime Host | [Plugin Spec](docs/PLUGIN_SPEC.md) · [交接](docs/BCA-03_MAIN_SYNC.md) |

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

- **观察：** 截图 → 插件识别 → PageState → Runtime 单次提交 → 上层读取结构化状态。
- **操作：** 命令解析 → 插件映射 Action → ActionBatch → Runtime 验证来源和顺序 → 浏览器输入 → 再次观察。
- **坐标：** 截图像素转换为 CSS viewport 坐标，使用 Frame.pixel_to_css()；不重复应用 DPR 或滚动偏移。
- **执行语义：** 输入 SUCCEEDED 只表示输入已被确认，实际网页效果需要下一次观察验证。

更多架构细节参阅 [ARCHITECTURE.md](docs/ARCHITECTURE.md) 和 [INTERFACES.md](docs/INTERFACES.md)。

## 开发环境与安装

- Python **3.12+**；当前阶段实际验证环境为 Windows / Python 3.14.7 / Edge 157，Python 3.12/3.13 的实机矩阵仍待补齐。
- 优先 Windows 与 Chromium / Microsoft Edge。
- 运行依赖：websockets 15.x、Pillow 12.x；开发依赖见 pyproject.toml。
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

**BCA-03 阶段交接报告（Windows / Python 3.14.7 / Edge 157）：**

| 验证项目 | 报告结果 |
| --- | --- |
| 全量测试（专用 CDP） | **533 passed / 0 skipped** |
| 全量测试（无 CDP） | **497 passed / 36 skipped** |
| 新增插件真机专项 | **24 passed** |
| DPR 1 / 1.5 / 2、全图/区域点击矩阵 | 3 轮合计 **54 次成功** |
| mypy strict / Ruff / wheel / sdist | 通过 |

交接性能样本：execute_text 到 BatchResult 的 median/p95 为 **6.34 / 18.90 ms**；命令至下一状态提交为 **67.16 / 96.09 ms**。这些包含上层协调及校验步骤，不是裸浏览器截图或通用网页的性能保证。详细测量边界参阅 [03.2 HANDOFF](docs/BCA-03.2_HANDOFF.md)、[性能 JSON](docs/BCA-03.2_PERFORMANCE.json)。

上述结果取自阶段测试报告；仍需补充 Python 3.12/3.13 实机、长时间压力、native/Edge RSS 和真实业务页面测试。

## 路线图

| 阶段 | 主题 | 当前状态 |
| --- | --- | --- |
| BCA-00 | Protocol / 公共契约 | 已验收 |
| BCA-01 | Browser / CDP、截图与输入 | 已验收 |
| BCA-02 | Runtime / 状态、调度与动作 | 已验收 |
| BCA-03 | Plugin System / 插件管理与 Host | 已验收 |
| BCA-04 | Vision & Assets / 图像识别与资源管理 | 规划中 |
| BCA-05 | CLI / 终端应用 | 规划中 |
| BCA-06 | Majsoul / 雀魂适配 | 规划中 |
| BCA-07 | Integration / 全系统验证 | 规划中 |

完整规划与阶段历史见 [DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)。

## 文档索引

- **核心规范：** [ARCHITECTURE.md](docs/ARCHITECTURE.md) · [INTERFACES.md](docs/INTERFACES.md) · [BROWSER.md](docs/BROWSER.md) · [RUNTIME.md](docs/RUNTIME.md) · [PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md)
- **跨模块交接：** [BCA-01](docs/BCA-01_MAIN_SYNC.md) · [BCA-02](docs/BCA-02_MAIN_SYNC.md) · [BCA-03](docs/BCA-03_MAIN_SYNC.md)
- **插件交付证据：** [BCA-03.1_HANDOFF.md](docs/BCA-03.1_HANDOFF.md) · [BCA-03.2_HANDOFF.md](docs/BCA-03.2_HANDOFF.md)
- **项目路线：** [DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md)

---

BCA 采用 **通用 Core + 可替换 Provider + 页面专属 Plugin** 的方式组织能力，让识别与输入可以在稳定的状态、动作和生命周期契约下组合。