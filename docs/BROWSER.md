# BCA-01.1：CDP 连接与目标会话

本阶段实现本机 CDP Transport、Target Discovery/Binding、BrowserSession；保留 `browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2` 以及 BCA-00 公开 API。唯一新增直接运行依赖为 `websockets>=15,<16`（本机验证 15.0.1）。截图、输入、Capture/Input Provider 及 Runtime 调度属于后续阶段。

## 用户执行的真实浏览器验收

用户已接手真实浏览器测试；以下步骤在用户本机 PowerShell、项目根目录执行。使用独立配置目录，测试只创建、导航和关闭它自己创建的两个标签页，不关闭浏览器或其他已有标签页。

1. 安装当前源码和开发工具：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

2. 启动独立 Edge 测试窗口（如果此目录对应的浏览器已启动，请先关闭那个测试实例再启动）。Chrome 可替换可执行文件路径：

```powershell
& "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$env:TEMP\bca-01-1-edge" --no-first-run about:blank
```

3. 确认发现端点和运行完整测试：

```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_browser.py -v -s
```

预期 **1 passed**，输出浏览器/CDP 版本、两个不同 Target ID/标题/URL、绑定的 sessionId/generation，以及导航保持绑定、关闭目标后失效、Reader/pending/socket 清理成功。测试会创建标题为 BCA-01.1-A/B 的 data URL 页面，再导航 A；只对测试创建的 Target 执行操作。测试结束后用户可关闭独立浏览器窗口。

若失败，请回传完整 pytest 输出及 `/json/version` 结果，尤其是最后观察到的测试页面信息。若停在标题就绪或 Runtime.evaluate，请确认该测试浏览器可以正常渲染页面。当前代理环境曾出现 GPU 子进程退出；采用进程内 GPU 的诊断启动后 CDP 可连接，但完整测试等待页面标题超时，因此不宣称完整真实验收已通过。

4. 默认模拟验收（清除端点变量后不会启动/连接真实浏览器）：

```powershell
Remove-Item Env:BCA_CDP_ENDPOINT -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## 手工枚举与显式绑定示例

```powershell
.\.venv\Scripts\python.exe examples/browser_session.py --endpoint http://127.0.0.1:9222
.\.venv\Scripts\python.exe examples/browser_session.py --endpoint http://127.0.0.1:9222 --target-id <上一步的目标ID>
```

示例不自动选择页面，执行完即关闭自身连接并释放 attach；不会关闭目标页面。源码可作为 BCA-01.2/01.3 生命周期编排示例。实例需在同一个 asyncio 事件循环内使用。

## 公开接口

均从 `bca.core.browser` 导入。传入参数用现有 `JsonObject` 类型，结果为 JSON 兼容字典；不改动公共 Frame/Action 模型。

| 类型/方法 | 实际签名和职责 |
| --- | --- |
| CDPConnection | `CDPConnection(*, connect_timeout: float=10.0, request_timeout: float=10.0, close_timeout: float=2.0, max_message_size: int=16777216)` |
| connect | `async connect(endpoint: str) -> None`：HTTP 发现与 WebSocket 握手；同端点已连接时幂等；显式 close 后不可复用 |
| send | `async send(method: str, params: JsonObject|None=None, *, session_id: str|None=None, timeout: float|None=None) -> JsonObject`：不重试；timeout 默认实例配置 |
| subscribe | `subscribe(method: str, handler: EventHandler, *, session_id: str|None=None) -> Callable[[],None]`：返回幂等注销函数；None 只订阅 browser-level 事件，`"*"` 表示全部 session，字符串表示精确 session |
| on_disconnect | `on_disconnect(handler: DisconnectHandler) -> Callable[[],None]`：返回注销函数；每次连接失效只发一次通知 |
| invalidate_session | `invalidate_session(session_id: str, error: BrowserError) -> None`：结束该 session 的 pending 请求，供会话层使用 |
| abort | `abort(error: BrowserError) -> None`：同步失效并中断 socket；最终资源回收仍由 close 完成 |
| close | `async close() -> None`：幂等、取消屏蔽的共享清理任务；调用者取消不会取消清理，之后可再次 await close 等待完成 |
| 连接只读属性 | `connected: bool`、`pending_count: int`、`reader_running: bool`、`last_error: BrowserError|None`（最近的连接失效原因） |
| TargetManager | `TargetManager(connection: CDPConnection)`；无状态请求辅助，不拥有连接 |
| TargetManager.list_targets | `async list_targets() -> tuple[BrowserTarget,...]`：调用 Target.getTargets，过滤 page |
| TargetManager.bind | `async bind(target_id: str) -> tuple[BrowserTarget,str]`：重新枚举并核验目标为 page，调用 attachToTarget(flatten=True)，返回目标和新 sessionId |
| TargetManager.unbind | `async unbind(session_id: str) -> None`：明确 detach，该辅助层直接返回底层结果/异常；上层 BrowserSession 管理重复解绑语义 |
| BrowserSession | `BrowserSession(endpoint: str, *, connect_timeout: float=10.0, request_timeout: float=10.0, close_timeout: float=2.0)` |
| Session 生命周期 | `async connect() -> None`、`async list_targets() -> tuple[BrowserTarget,...]`、`async bind(target_id: str) -> None`、`async unbind() -> None`、`async close() -> None` |
| Session.send | `async send(method: str, params: JsonObject|None=None, *, timeout: float|None=None) -> JsonObject`：只向当前绑定 session 发送，返回前再检查 generation 和绑定身份 |
| Session 只读属性 | `connection: CDPConnection`（借用的 browser-level 连接）、`state: SessionState`、`connected/is_ready: bool`、`bound_target: BrowserTarget|None`、`page_id/session_id/previous_target_id: str|None`、`generation: int`、`last_error: BrowserError|None` |

`BrowserTarget` 为冻结、关键字 dataclass：`target_id/title/url/type: str`；`BrowserTarget.from_cdp(info: JsonObject) -> BrowserTarget` 验证 CDP TargetInfo。`CDPEvent` 为冻结、关键字 dataclass：`method: str, params: JsonObject, session_id: str|None=None`；事件载荷按只读使用。

`EventHandler = Callable[[CDPEvent], Awaitable[None]|None]`；`DisconnectHandler = Callable[[BrowserError], Awaitable[None]|None]`。事件同步回调在 Reader 收取消息时按订阅顺序调用，必须快速且不阻塞；异步回调独立调度，不保证完成顺序，可重入 send。异常仅记录类别，不终止 Reader。最多 256 个未完成异步回调，超过则中断连接以避免无限积压。回调必须响应取消；close 取消未完成事件任务，给本次 close 的断线通知最多 close_timeout 秒完成，随后取消剩余任务。回调调用点不持有连接内部锁。

## 连接与安全边界

仅接受 `http://localhost:<port>` 或字面回环 IP（含 IPv6），路径只能为空或 `/`，不接受凭据、查询、片段和远端主机。通过 asyncio DNS 核验 localhost 的所有地址均为回环，HTTP 使用核验后的数值 IP，检查实际 peer。请求固定 `/json/version`，要求 200，不跟随重定向。

发现的 URL 必须为同一实际 peer、相同端口的 `ws://.../devtools/browser/...`；连接前固定数值地址、关闭代理，并禁止 WebSocket 握手重定向。不会默默转向远端或 page-level socket。该限制是本阶段明确范围；HTTPS/WSS、远端调试、HTTP chunked 发现响应暂不支持。HTTP 头限制约 32 KiB、发现 body 最大 1 MiB，WebSocket 单消息默认 16 MiB，后续大截图需评估是否调整。

HTTP 发现与 WebSocket 握手共享 connect_timeout 总预算。单次请求 timeout 覆盖等待发送锁、发送和响应；asyncio.timeout 使用单调时钟。编号在发送锁内递增，整个对象生命周期不重用；Reader 是唯一 recv 调用者，乱序响应按 id/Future 对应。sessionId 位于 CDP 消息顶层，响应 sessionId 必须匹配。

请求取消/超时移除 pending，迟到或重复响应丢弃；如在发送中途被打断，则中断连接避免继续使用不确定的帧边界。响应等待阶段的超时/取消不会自动断开连接，但命令可能已执行，禁止盲目重试。日志只记录 ID/method/session/耗时和错误类别，不输出 params/result、页面内容或大缓冲。调试日志应避免启用第三方库的原始消息日志。

## Target、会话身份与 generation

`page_id = target_id`：在该 Target 存续期间稳定。CDP sessionId 属于一次 attach，重连/重新 attach 后重新获取，不能持久缓存。BrowserSession 只有一个当前绑定；同一有效目标重复 bind 幂等，切换先解绑旧目标再 attach 新目标。如果新目标无效，旧目标已经解绑，不回退或自动选其他页面。

状态枚举 `SessionState`：DISCONNECTED、CONNECTED、BOUND、CLOSED（值为小写）。connect 完成发现后进入 CONNECTED；绑定成功进入 BOUND；解绑或目标丢失回到 CONNECTED；网络断开进入 DISCONNECTED；close 永久进入 CLOSED。

generation 从 0 起：成功 connect +1，成功 bind +1，清除现有绑定 +1，已连接状态失去连接 +1，首次 close +1。幂等 connect/bind/unbind/close 不重复增加；切换页面通常 +2。普通导航只刷新 title/url，不增加 generation 或更换 attach。generation 是连接/绑定身份，不代表页面 DOM 或截图内容版本；页面刷新中新鲜度策略需 01.2/01.3 另行落实。

监听 Target.targetInfoChanged、targetDestroyed、detachedFromTarget；当前目标销毁/当前 session detach 会在 Reader 处理事件当次清除绑定，并终止其 pending 页面操作。旧 session 的迟到 detach 不影响新绑定。attach 中收到销毁或提前 detach 的事件，不提交过期绑定；如果 attach/detach 超时或取消造成远端结果不确定，主动断开该连接以释放可能残留的 attachment。

connect/bind/unbind/close 经 Session 锁串行。重连由调用方显式触发 `connect()`：关闭旧连接、重新发现端点、启用 Target 发现并重新枚举；不自动恢复绑定。`previous_target_id` 保留最后成功目标供调用方确认，再显式 bind；bind 始终重新核验目标仍存在且为 page。

BrowserSession 拥有连接关闭权，未来 Provider 只借用 Session。优先使用 `session.send()`；不要缓存重连前的 connection/sessionId，或在 Provider.close 中关闭共享 Session。关闭 CDP 浏览器 socket 会释放它自己的 attach，不会关闭浏览器本体或目标标签页。

## 错误与后续接入

以下错误从 `bca.core.browser` 或 `bca.core.browser.errors` 导入：

| 类型 | Core 关系与语义 |
| --- | --- |
| BrowserError | ProviderError 子类，code=browser.error |
| EndpointError | ValidationError 子类，browser.endpoint，非法或不信任的端点/发现文档 |
| CDPConnectionError | BrowserError，browser.connection，HTTP TCP/WS 连接失败，保留 cause |
| CDPDisconnectedError | BrowserError 和 CapabilityUnavailableError，browser.disconnected，连接不可用 |
| CDPTimeoutError | BrowserError 和 TimeoutError，browser.timeout，发现/握手/请求超时 |
| CDPMessageError | BrowserError，browser.message，非法消息或回调积压 |
| CDPCommandError | BrowserError，browser.command，提供 method、cdp_code、message；code 属性仍为稳定 BCA 错误码 |
| TargetNotFoundError | BrowserError，browser.target_not_found，明确 ID 不存在 |
| TargetBindingError | BrowserError，browser.target_binding，非 page 或 attach/detach 被拒绝；保留原 CDPCommandError cause |
| TargetLostError | BrowserError 和 CapabilityUnavailableError，browser.target_lost，未绑定/失效/过期结果 |

非法方法、参数与 timeout 使用已有 ValidationError；关闭后的生命周期调用使用 LifecycleError；asyncio.CancelledError 原样传播。

BCA-01.2 负责截图编码、Frame 元数据和捕获时序；01.3 负责标准 Action → CDP 映射、ActionResult、超时后的输入状态与释放。这些不由原始 CDP send 保证。Protocol 2 未调整，具体 Provider 注册/启动仍由后续 Core 编排。

实现核对了已安装 websockets 15.0.1 的 connect/redirect API；参考协议入口为 [CDP Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/) 与 [websockets asyncio client](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html)。本环境网页工具未能获取在线文档；当前证据以安装源码、模拟测试和记录的真实 CDP 结果为准。
