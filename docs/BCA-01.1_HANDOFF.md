# BCA-01.1 阶段交接：CDP Transport & Target Session

日期：2026-11-12。基线保持 **browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2**。

## 完成状态

CDPConnection、TargetManager、BrowserSession、专属模型/错误、本机端点发现、使用示例及模拟测试已实现。**代码与本机模拟验收通过；完整真实浏览器验收待用户执行，未标记通过。** 用户明确提出接手浏览器测试后，代理停止启动新的浏览器测试实例。

已读取并对照 `docs/md/BCA_PROJECT_CONTEXT.md`、`BCA-00_MAIN_SYNC.md`、`BCA-01_Browser.md`、`BCA-01.1_Codex_Prompt.md` 和现有接口/代码。中途用户补充共享文件后重新核验，没有扩大到 01.2/01.3。与历史报告相比，目前目录已经是 Git 仓库；用户补充的总纲修改及三个任务/同步文件予以保留，未覆盖。

没有修改 Protocol 2 模型、Provider ABC 或 Plugin 公共 API。本轮新增运行依赖 `websockets>=15,<16`（实际 15.0.1），协议模块仍只依赖标准库和公共错误。

## 交付文件

新增源码：

- `src/bca/core/browser/connection.py`：单 Reader、id/Future 匹配、并发请求、事件订阅、断线与关闭清理。
- `src/bca/core/browser/endpoint.py`：asyncio HTTP 发现、回环地址解析/实际 peer 固定、信任边界及体积限制。
- `src/bca/core/browser/targets.py`：页面枚举过滤、显式 attach(flatten=True)/detach。
- `src/bca/core/browser/session.py`：单目标状态、并发生命周期、generation、失效/恢复和页面 send。
- `src/bca/core/browser/models.py`、`errors.py`：冻结 BrowserTarget/CDPEvent、SessionState 及 Core 兼容错误。
- `examples/browser_session.py`：可运行的枚举/显式绑定示例。

新增测试：`tests/core/browser/__init__.py`、`mock_cdp.py`、`test_connection.py`、`test_session.py`、`test_real_browser.py`。本机模拟 HTTP/WebSocket 服务器没有外部网络依赖；真实测试以 browser_integration 标记并要求环境变量显式启用。

修改：`src/bca/core/browser/__init__.py` 导出；`pyproject.toml` 依赖、标记和示例类型检查；`MANIFEST.in` 收入示例；`tests/app/package_smoke.py` 从“零运行依赖”验收更新为仅 websockets 运行依赖；`README.md`、`docs/ARCHITECTURE.md`、`INTERFACES.md`、`DEVELOPMENT_PLAN.md` 同步阶段状态。新增 `docs/BROWSER.md` 和本报告。

## 公共接口与设计决策

完整签名、属性、错误及用户测试步骤见 [BROWSER.md](BROWSER.md)，稳定入口为 `bca.core.browser`：

- `CDPConnection`：异步 connect(endpoint)、send(method, params, *, session_id, timeout)、close；同步 subscribe/on_disconnect 返回注销函数；只读 connected/pending_count/reader_running/last_error。
- `TargetManager(connection)`：async list_targets()、bind(target_id)->(BrowserTarget, sessionId)、unbind(session_id)。它不管理单目标策略，不关闭借用连接。
- `BrowserSession(endpoint, *, connect_timeout, request_timeout, close_timeout)`：async connect/list_targets/bind/unbind/close/send；只读 state、connected、is_ready、bound_target、page_id、session_id、generation、previous_target_id、last_error、connection。
- `BrowserTarget`：target_id/title/url/type；`CDPEvent`：method/params/session_id；`SessionState`：DISCONNECTED/CONNECTED/BOUND/CLOSED。
- 错误：BrowserError、EndpointError、CDPConnectionError、CDPDisconnectedError、CDPTimeoutError、CDPMessageError、CDPCommandError、TargetNotFoundError、TargetBindingError、TargetLostError；对应 Core 的 ProviderError、CapabilityUnavailableError 或 ValidationError，保留 cause。

关键约定：

1. HTTP `/json/version` 发现 browser-level WebSocket，使用 asyncio 非阻塞 I/O。只允许本机回环地址，校验解析结果与实际 peer，发现 URL 必须同 peer/端口，不接受代理或 HTTP/WS 重定向。
2. 单 Reader 接收所有消息，发送锁保护递增 id 和消息发送，允许多请求乱序响应。flattened sessionId 写在消息顶层。超时覆盖锁等待/发送/响应，采用 asyncio 单调超时。
3. 参数/响应负载不写日志；保留 method、id、session、耗时和错误类别。回调异常隔离，异步回调支持重入 send；有 256 个未完成回调上限和关闭取消约定。
4. `page_id=target_id`，sessionId 属于一次 attach；重连不自动选择/恢复页面。调用方 connect 后重新列出并确认 ID，再 bind。每次 bind 重新检查 Target 存在且为 page。
5. Session 生命周期锁串行 connect/bind/unbind/close；同有效目标重复绑定幂等。切换先解除旧绑定，失败不偷偷回退或改绑其他页面。
6. generation 在连接/绑定/解绑/失效/首次关闭时递增；普通导航刷新描述但不更换绑定。旧 session 的迟到 detach 不会使新 attach 失效；attach 中目标销毁或 detach 时不提交过期状态。
7. Session.send 捕获并复核 generation/连接/会话身份，目标丢失时结束该 session 的 pending 请求。generation 不表示 DOM 内容版本，后续截图新鲜度仍需专门定义。
8. attach/detach 取消或超时可能留下远端副作用，断开该连接以释放不确定的 attachment，不自动重试。BrowserSession 拥有关闭权，未来 Provider 仅借用 Session。
9. close 幂等且使用独立清理任务/取消屏蔽；调用者取消后可再次 await close。同步回调须快速，异步回调须响应取消；不提供线程安全或后台永久重试。

## 已执行验证

实际环境：Windows，Python **3.14.7**，websockets **15.0.1**，pytest **9.2.0**，mypy **2.4.1**，Ruff **0.17.4**。

| 命令 | 实际结果 |
| --- | --- |
| `python -m pip install -e ".[dev]"`（使用 .venv\Scripts\python.exe） | 成功，现有 0.2.0 安装更新并包含 websockets 依赖 |
| `python -m pytest -W error` | **117 passed / 1 skipped / 0 failed**；82 项原有测试保留通过，35 项新增模拟测试通过；真实测试因未配置端点而跳过 |
| `python -m mypy` | strict 通过，28 个源码/示例文件 |
| `python -m ruff check .` | 通过 |
| `python -m ruff format --check .` | 通过；后续仅交接文档补充，不改变实现 |

覆盖：正常发现和连接、并发请求与乱序返回、会话级事件、注销/异常回调/重入、CDP 错误、超时/取消/迟到响应、断线 pending 清理、非法消息、非法/远端端点、HTTP/WS 重定向、恶意 localhost 解析、发送锁等待超时、枚举过滤、显式绑定/重复/切换/解绑、导航/关闭/detach、attach 中销毁/取消/超时、生命周期并发、被取消的 close、部分初始化失败、重连目标重新核验及旧 detach 迟到场景。

构建与安装的最终补充验证记录在报告末尾。Python 3.12/3.13 尚未实际运行；mypy/Ruff 的 3.12 目标不是运行矩阵证据。

## 真实浏览器结果与用户接续

代理环境发现 Edge **157.0.4341.46**。独立 headless 配置启动后，部分尝试因浏览器进程退出而出现 ConnectionRefused/ConnectionReset；浏览器日志记录 GPU 子进程失败。使用 `--in-process-gpu` 的诊断实例后，BCA 成功完成 HTTP 发现、WebSocket 连接、Target 发现初始化，并取得 `Browser.getVersion`：**Edg/157.0.4341.46 / CDP 1.3**。

完整测试随后在等待两个测试页的预期标题时 **10 秒超时（1 failed）**。尚不能据此宣称目标导航、页面脚本执行和完整真实会话流程已通过；标题未就绪的确切原因也未最终确定。没有通过放宽断言把这次失败转换为通过。关闭清理测试所创建 Target 的代码使用 finally，测试实例由对应启动脚本清理。之后用户明确接手浏览器测试，代理不再启动新的测试实例。

用户请按 [BROWSER.md：真实浏览器验收](BROWSER.md) 执行。关键命令：

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_browser.py -v -s
```

该测试须返回 **1 passed**，才能补记完整真实浏览器验收通过。当前状态是“代码及模拟验收完成，真实浏览器验收待用户结果”，不是 BCA-01 全部完成。

## 01.2 / 01.3 接入与遗留范围

- Core 创建/连接并显式绑定 BrowserSession；Capture/Input 共享引用，不在任一 Provider.close 中关闭它。
- 页面 CDP 调用使用 `session.send()`，避免缓存旧 sessionId/connection；必要时在跨多个 CDP 操作的事务前后额外检查 generation。
- Capture 仍须实现按需截图、PNG/JPEG 校验、Frame 时间/尺寸/viewport/capture 元数据和导航期间新鲜度。16 MiB 默认单消息上限可能需要针对大截图评估。
- Input 仍须实现 Action 映射、同页调用方调度、部分执行反馈、输入按键/按钮的取消释放。CDP 超时不证明没有副作用。
- 当前只支持本机 HTTP/WS、非 chunked 的发现响应；远端/HTTPS/WSS 不在本阶段范围。
- 只输出本阶段 HANDOFF；BCA-01_MAIN_SYNC 留待 BCA-01 子会话根据用户真实测试结果和后续阶段汇总。

## 构建与最终补充验证

以下均使用项目内 Python，不启动浏览器：

| 命令/检查 | 结果 |
| --- | --- |
| `.venv\Scripts\python.exe -m build` | sdist 与 wheel 构建成功，文件位于 dist，版本仍为 0.2.0 |
| `.venv\Scripts\python.exe -m venv .venv/browser-package-check` | 创建独立安装验证环境 |
| `.venv\Scripts\python.exe -m pip download --no-deps --dest .venv/wheelhouse 'websockets>=15,<16'` | 保存 15.0.1 wheel 用于离线依赖安装 |
| `.venv\browser-package-check\Scripts\python.exe -m pip install --no-index --find-links .venv/wheelhouse dist/browser_cli_agent-0.2.0-py3-none-any.whl` | 完全从本地文件安装 BCA 与 websockets 成功 |
| `.venv\browser-package-check\Scripts\python.exe -I tests/app/package_smoke.py` | 25 个模块、公开导出、py.typed、Frame/Action codec 及运行依赖检查通过，无 Pydantic |
| `.venv\browser-package-check\Scripts\python.exe -m pip check` | 无依赖冲突 |
| `.venv\Scripts\python.exe examples/browser_session.py --help` | 示例命令帮助可运行，不连接浏览器 |
| `.venv\Scripts\python.exe -m ruff format --check .` | 最终格式检查通过（当时 61 个文件） |
| Python 3.12 语法解析 | 28 个源码/示例文件通过；不等同 3.12 实际运行 |
| sdist 内容检查 | 包含 BROWSER/HANDOFF、可运行示例及模拟/真实测试文件 |

`git diff -- src/bca/core/protocol src/bca/core/providers src/bca/core/plugins` 为空，确认现有共享 API 源码未改变。全树 `git diff --check` 唯一报告来自用户补充的 `docs/md/BCA_PROJECT_CONTEXT.md` Markdown 行尾双空格；保留原文，排除 `docs/md/*` 后本轮变更的检查通过。没有替用户提交 Git commit。

本轮未升级包版本，因此 dist 中同名 0.2.0 产物是当前 Browser 阶段构建，不能与历史 BCA-00 的同名构建按版本号区分；使用源码状态及本报告判定阶段。上述打包与导入验证不替代待用户执行的真实浏览器测试。
