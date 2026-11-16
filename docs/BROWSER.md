# BCA-01.1：CDP 连接与目标会话

已实现本机 CDP Transport、Target Discovery/Binding、BrowserSession、PNG Capture Provider 及 Input Provider；保留 `browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2` 以及 BCA-00 公开 API。运行依赖为 `websockets>=15,<16` 和 `Pillow>=12,<13`。2026-11-16 的 01.4 本轮全量 **285 passed，零跳过**，含四阶段真实 Edge 验证，见 [01.4 交接](BCA-01.4_HANDOFF.md) 和 [Browser 正式跨模块契约](BCA-01_MAIN_SYNC.md)。Runtime 调度属于后续阶段；历史截图交付见 [01.2 最终交付](BCA-01.2_DELIVERY.md)。

## 完整集成示例（01.4）

```powershell
.\.venv\Scripts\python.exe examples/browser_end_to_end.py --endpoint http://127.0.0.1:9339 --output browser-artifacts --samples 3
# opt-in 测试使用相同流程：
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9339"
$env:BCA_BROWSER_OUTPUT = "$PWD\browser-artifacts"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_end_to_end.py -v --basetemp=.test-artifacts/pytest-01.4
```

端点需由使用者预先启动。示例只列出已有页面 ID，创建自己的受控页面并显式 bind，启动/注册 Capture 和 Input，通过 `registry.get(CaptureProvider)`、`registry.get(InputProvider)` 获取协议能力。区域采集是 Browser 扩展，因此使用 `registry.get(BrowserCaptureProvider).capture_region(...)`。

默认执行 DPR 1/1.5/2 × 全图/区域 × 3 次采样。每次从真实 PNG 找红色像素中心，用 Frame.pixel_to_css 生成 Action；DOM 只在输入后核验命中元素、坐标和计数，不参与点击位置决策。输出 browser-integration-report.json 及六张 PNG。报告含帧 ID/UTC 时间、session/generation、像素与 CSS 坐标、DOM、ActionResult、原始耗时及中位数。日志/报告不记录已有用户页面的标题或 URL。

示例的 Observation 只是调用方上下文，保存 capture 前后的绑定身份和几何/文档测量结果；执行前再次比较。可拒绝已观察到的重绑、导航、滚动和 resize，仍不能保证检查与点击之间 DOM 不变。该示例复用内部 geometry helper，不把它声明为新公共 API。Capture/Input 的锁仍各自独立，观察与动作没有新增全局互斥。

退出按 Input.close → Capture.close → 关闭自建 Target → Session.close 执行；清理任务持有强引用并屏蔽外部取消，重复取消也等待清理完成，然后传播 CancelledError。启动失败也记录失败阶段及清理结果。结束会验证自建页已关闭、预先存在的页仍在，并记录 pending=0/reader=false/connected=false。示例不关闭用户提供的浏览器；本轮代理自建实例的退出由测试编排负责。

## BCA-01.2 截图与坐标

公开入口：`from bca.core.browser import BrowserCaptureProvider, CaptureError`。

| API | 行为 |
| --- | --- |
| `BrowserCaptureProvider(session, *, timeout=10.0)` | 借用 Session；总超时涵盖锁等待、测量、截图、解码与复核 |
| `available` | 已 start、未 close 且 Session 当前 ready 时为真 |
| `await start()` | 要求已显式绑定；重复 start 幂等；已 close 后 start 抛 LifecycleError |
| `await capture(page_id)` | 完整可见内容视口 PNG，返回 Protocol 2 Frame |
| `await capture_region(page_id, *, x, y, width, height)` | CSS viewport 矩形；通过完整截图后的本地像素裁剪实现 |
| `await close()` | 幂等关闭 Provider，使在途结果失效；不关闭或解绑借用的 Session |

```python
from bca.core.browser import BrowserCaptureProvider
from bca.core.providers import ProviderRegistry

# session 已 connect 并显式 bind(target_id)
capture = BrowserCaptureProvider(session)
registry = ProviderRegistry()
registry.register(capture)  # 注册不启动 Provider
await capture.start()
try:
    frame = await registry.get(BrowserCaptureProvider).capture(target_id)
    region = await capture.capture_region(target_id, x=40.25, y=40.25, width=79.25, height=79.25)
    css_x, css_y = region.pixel_to_css(0, 0)
finally:
    await capture.close()  # Session 仍由调用方拥有
```

几何分别读取 `Page.getLayoutMetrics.cssVisualViewport` 和 cssLayoutViewport，使用 Runtime.evaluate 获取实际 DPR、滚动、innerWidth/innerHeight、URL 与 performance.timeOrigin。当前支持桌面 visual scale=1、offsetX/Y=0，但不要求两种视口宽高相等：逻辑内容范围为同原点的可见矩形与布局内容矩形的交集，CSS 宽高分别取两者的 min。两组尺寸必须为正，且前后测量都保持稳定。layout 的整数滚动允许与 visual/runtime 精确滚动相差最多 1 CSS 像素（取整），超出则拒绝；Runtime 滚动须与 visual 匹配。

截图使用 `fromSurface=true`、`captureBeyondViewport=false`，不传 CDP clip，不改变滚动或展开全文。原生 surface 包含滚动条，CSS 范围取 Runtime innerWidth/innerHeight；实际 PNG 像素对应此范围，再在本地去除非内容部分。内容右/下边缘向内取整到完整像素，防止把滚动条混入内容。Frame.viewport.width/height 为逻辑交集尺寸，capture_* 为实际像素覆盖范围；完整截图也可能少覆盖不到一个源像素。zoom/DPR 保留诊断及变化检查，不再用于设置文档 DIP clip，DPR 不参与 pixel_to_css。

截图前后测量必须一致，且 connection/Target ID/sessionId/generation 保持不变；导航造成 URL/timeOrigin 变化、滚动、缩放、resize 都会拒绝当前结果。这个检查不保证 DOM/Canvas 原子冻结，也不能检测两次测量之间变化又恢复的情况。没有后台采集循环或自动重试，调用方可在页面稳定后重试。

图像通过严格 Base64 解码、PNG 签名/结构/CRC 检查及 Pillow 完整像素解码；Frame.width/height 来自实际图像，不用 DPR 推算，也不强行要求等比缩放。压缩数据上限约 12 MB，解码上限 1600 万像素；CDPConnection 默认单消息上限仍为 16 MiB。PNG 解码/裁剪在线程中进行，取消会立即停止协程请求路径；已经进入线程的有界 CPU 工作会自行完成并释放图像，不能强杀线程，不会继续访问 CDP 或提交 Frame。

区域请求必须为正尺寸、非负坐标且位于逻辑内容视口。设原生 surface 栅格 W×H、CSS 范围 Sw×Sh，则像素左/上边界取 floor(x·W/Sw)、floor(y·H/Sh)，右/下取 ceil((x+w)·W/Sw)、ceil((y+h)·H/Sh)，限制在完整内容像素范围内。内部边界向外扩展不到一个源像素；最右/下边界可能向内少覆盖不到一个源像素。Frame.viewport.capture_* 从实际像素边界反算，不能假定与请求小数值完全一致。`pixel_to_css` 沿用 Protocol 2 两轴独立公式，不额外乘 DPR、不加滚动偏移。区域采集同样需要完整截图和解码，不宣称节省 CDP 传输或更低延迟。

参数错误或 page_id 不匹配抛 ValidationError；尚未启动、Session 不 ready、Provider 已关闭时抛 CapabilityUnavailableError；采集中身份失效抛 TargetLostError，CDP 错误保持原有类型；图像异常、几何不一致或不支持的 visual viewport 抛 CaptureError（BrowserError/ProviderError 子类）；总超时抛 CDPTimeoutError，取消原样传播。并发采集在同一个 Provider 内串行；推荐一个 Session 注册一个 Capture Provider，不对其他 CDP 客户端的并发操作承诺互斥。

本阶段仅 PNG，不提供 JPEG 参数。移动端捏合缩放/visual viewport 偏移明确拒绝；01.3 输入沿用相同限制和 CSS 内容视口契约，没有修改 Protocol 2。

### 用户截图验证

使用已经启动的 Edge 调试实例，先更新依赖，再执行独立示例或 pytest：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe examples/capture_browser.py --endpoint http://127.0.0.1:9222 --output .\capture-artifacts --samples 3
# 或使用同一验收流程的 pytest 入口：
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:BCA_CAPTURE_OUTPUT = "$PWD\capture-artifacts"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_capture.py -v -s
```

仅创建、修改和关闭脚本自己的两个 Target，不启动浏览器，不修改已有页面。测试使用横纵滚动条、有色标记、滚动网格和 Canvas，检查 DPR 1/1.5/2、640×480/720×540/800×600、双向滚动、裁剪实际颜色、Canvas 变化、导航后采集与关闭后的拒绝。通过 DOM 测量独立定位右下角紫色色块，校验内容尺寸、实际 PNG 尺寸及贴边小数区域的颜色和 pixel_to_css。背景测试会激活另一个自建标签页并记录 visibilityState；只有该记录为 hidden 才能认定测到了隐藏页面，不外推为任意后台 WebGL 新鲜度。

输出 `capture-report.json`、完整/区域/贴边 PNG、foreground-canvas.png，以及后台成功时的 background-canvas.png。每组采集前打印并保存有限数值型 visual/layout metrics、DOM/surface 尺寸、DPR、滚动和实际截图参数。完整 PNG 在像素断言前保存。测试首先激活自建页面；Canvas 前台更新等待绘制提交；最后单独探测后台，超时记录为限制，不盲目重试。Provider 不自动激活页面。耗时以 perf_counter 测量整个 await capture，单位 ms，默认每组完整和区域各 3 次，包含测量/传输/解码/裁剪，不含保存文件及额外贴边校验；报告原始样本和中位数。实际数据见最终交付报告。

桌面 Ctrl+/- 缩放尚需额外人工验证：在独立测试页设为 125%/80%，通过 browser_session 示例枚举并绑定该页，使用上面的 Provider 示例保存 Frame 和 PNG，核对已知 CSS 色块位置与 pixel_to_css，分别记录 metrics.zoom、DPR 和图片宽高。核心自动测试覆盖 zoom 数据转换，但不等价于真实浏览器缩放已验证。WebGL 与截图期间真实导航/关闭竞争仍待专项实测，生命周期竞争当前由模拟测试覆盖。

## 用户执行的真实浏览器验收

以下为可选的手动复现步骤；代理已独立完成当前 01.4 实测。使用独立配置目录，测试只创建、导航和关闭它自己创建的两个标签页，不关闭浏览器或其他已有标签页。请选择未占用的调试端口，勿将既有个人浏览器当成测试实例。

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

若复现失败，可查看 pytest 输出及 `/json/version`，尤其是测试页面就绪情况。早期代理环境曾出现 GPU 子进程退出；当前隔离实例使用已记录的测试启动参数完成四阶段验收，不能把早期未通过状态视为当前结果。环境限制及参数见 01.4 交接报告。

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
| Session.refresh_target | `async refresh_target() -> BrowserTarget`：browser-level `Target.getTargetInfo` 强制读取当前绑定目标，校验身份后更新缓存，不改变 generation 或 attachment |
| Session 只读属性 | `connection: CDPConnection`（借用的 browser-level 连接）、`state: SessionState`、`connected/is_ready: bool`、`bound_target: BrowserTarget|None`、`page_id/session_id/previous_target_id: str|None`、`generation: int`、`last_error: BrowserError|None` |

`BrowserTarget` 为冻结、关键字 dataclass：`target_id/title/url/type: str`；`BrowserTarget.from_cdp(info: JsonObject) -> BrowserTarget` 验证 CDP TargetInfo。`CDPEvent` 为冻结、关键字 dataclass：`method: str, params: JsonObject, session_id: str|None=None`；事件载荷按只读使用。

`bound_target` 是同步缓存快照，访问不发生网络 I/O；变化事件会尽快更新它，但不保证事件携带最终页面标题。需要当前元数据时显式调用 `refresh_target()`。`bind()` 仍只负责绑定，不额外刷新或等待页面加载；首次读取可在绑定后主动刷新，合法的临时标题不会使绑定失败。刷新返回的是查询时的 TargetInfo，不保证页面已经加载完成。

```python
await session.bind(target_id)
initial = await session.refresh_target()
navigation = await session.send("Page.navigate", {"url": destination})
if "errorText" in navigation:
    raise RuntimeError(f"Navigation failed: {navigation['errorText']}")
# 如需最终标题，先由调用方有界等待页面加载；Page.navigate 返回不表示加载完成。
current = await session.refresh_target()
print(current.title, current.url)
```

刷新捕获 connection、targetId、sessionId、generation，在提交前核验绑定仍有效；unbind、切换、同目标重新绑定或关闭都不能被旧结果覆盖。并发刷新串行执行，生命周期操作不等待刷新锁。同一绑定内若查询期间收到元数据事件，丢弃该次查询结果并重新读取；整个调用（含锁等待和重查）共用 `request_timeout`，持续变化最终抛 `CDPTimeoutError`。提交后到达的新事件仍可更新缓存，因此刷新不是持续一致性订阅或 DOM 版本屏障。

无绑定/身份过期抛 `TargetLostError`，已关闭对象抛 `LifecycleError`；非法 TargetInfo、目标 ID/type 不符抛 `CDPMessageError`；CDP 命令失败（包括没有销毁事件时查询已消失目标）保留 `CDPCommandError`。不根据错误字符串推断目标销毁，不在失败时写入缓存。连接异常和取消按原体系传播；查询只读，取消/超时移除 pending，不因刷新失败主动拆除合法绑定。

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

BCA-01.2 已实现上述截图编码、Frame 元数据和捕获时序；01.3 已实现标准 Action → CDP 映射、ActionResult、超时后的输入状态与释放，见下文。这些不由原始 CDP send 保证。Protocol 2 未调整，应用中的 Provider 注册/启动仍由后续 Core 编排。

实现核对了已安装 websockets 15.0.1 的 connect/redirect API；参考协议入口为 [CDP Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/) 与 [websockets asyncio client](https://websockets.readthedocs.io/en/15.0.1/reference/asyncio/client.html)。本环境网页工具未能获取在线文档；当前证据以安装源码、模拟测试和记录的真实 CDP 结果为准。

## BCA-01.3 输入 API

`from bca.core.browser import BrowserInputProvider`，构造签名为 `BrowserInputProvider(session: BrowserSession, *, timeout: float = 10.0)`。实现 `InputProvider.execute(action: Action) -> ActionResult`。一个 Session 使用一个 Input Provider；Registry 类型查询与注册规则不变。Provider 只借用会话，不连接、不选择目标、不激活页面，也不关闭 Session。

`start()` 要求已经显式绑定页面，就绪时重复调用无害。`close()` 立即阻止新输入，串行等待当前调用结束并释放本 Provider 记录的按键，支持重复调用；关闭后不能再次 start。close 使用共享、取消屏蔽的清理任务，调用者被取消后可再次 await close。`available` 是 started、未关闭、Session ready 且输入状态没有不确定性的本地快照。

| ActionType | CDP 命令 | 语义 |
| --- | --- | --- |
| MOUSE_MOVE | Input.dispatchMouseEvent / mouseMoved | 保留当前 buttons/modifiers，clickCount=0 |
| MOUSE_CLICK | mousePressed → mouseReleased | 相同坐标和按钮，clickCount=1，无人工 sleep |
| MOUSE_DOWN | mousePressed | 保持按钮状态直到 UP 或清理 |
| MOUSE_UP | mouseReleased | 要求按钮已由此 Provider 按下，发送释放后的 buttons |
| KEY_DOWN | Input.dispatchKeyEvent / keyDown 或 rawKeyDown | 有可输入 text 时 keyDown，否则 rawKeyDown；重复按下为 autoRepeat |
| KEY_UP | Input.dispatchKeyEvent / keyUp | 要求该 code 已由此 Provider 按下；不携带输入文本 |
| TEXT_INPUT | Input.insertText | 尊重页面焦点，支持 Unicode；空串不发送输入 |

鼠标支持 left/right/middle，buttons 位分别为 1/2/4，可组合按住。重复 DOWN、对已按住按钮 CLICK、无匹配 DOWN 的 UP 均抛 ValidationError。每个鼠标 Action 前重新测量当前内容视口；使用 visual/layout 同原点矩形交集，与 Capture 共享 `geometry.py`。允许小数坐标，拒绝 `x >= width` 或 `y >= height`；不添加 scroll，不乘除 DPR。release 清理使用最后发送的位置，不因后续 resize 越界而放弃必要释放。

逻辑键支持 ASCII 字母、数字、空格（`" "`/`Space`）、Enter、Tab、Escape、Backspace、Delete、四个 Arrow、Home、End、PageUp、PageDown、Shift、Control/Ctrl、Alt、Meta。使用明确的 US 键位映射；Shift+字母大写、Shift+数字映射 US 标点。其他字符使用 TEXT_INPUT。不承诺任意键盘布局、IME、系统快捷键或物理左右键区分。modifier 位为 Alt=1、Control=2、Meta=4、Shift=8；Ctrl/Alt/Meta 组合抑制 text，但仍发送 DOM 键盘事件。按键释放使用按下时记录的 key/code；修饰位反映当前状态。

### 调用与坐标闭环

```python
from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider
from bca.core.protocol import Action, ActionType, MouseButton

# session 已由调用方连接并绑定 target_id；px/py 是识别到的截图像素位置。
capture = BrowserCaptureProvider(session)
inputs = BrowserInputProvider(session)
await capture.start()
await inputs.start()
try:
    frame = await capture.capture(target_id)
    x, y = frame.pixel_to_css(px, py)
    result = await inputs.execute(
        Action(
            page_id=frame.page_id, type=ActionType.MOUSE_CLICK, x=x, y=y, button=MouseButton.LEFT
        )
    )
finally:
    await inputs.close()  # 必须先于 Session 解绑/关闭，以便释放按住的输入。
    await capture.close()
```

Frame 没有 generation。输入保证单次调用的 connection/page/session/generation 身份和执行前的当前几何有效；不把旧 Frame 的 page_id 当成内容新鲜度保证。导航不改变 session/generation；DOM、布局和焦点可能在测量后变化。Runtime 必须自行关联观察上下文，在 resize、导航或换绑后重新观察；本层不保证截图与点击之间的 DOM 原子性。

### 错误、超时和取消

调用前参数/目标不匹配及运行时坐标/按键状态非法抛 ValidationError；尚未 start、已关闭、Session 不 ready 或状态不确定抛 CapabilityUnavailableError；关闭后 start 抛 LifecycleError。已接受动作遭遇换绑、断连或关闭时抛 TargetLostError。可预期 CDP 命令失败、几何错误和总超时返回 FAILED/ErrorDetail，稳定 code 分别沿用 browser.command、browser.geometry、browser.timeout 等；未知编程异常原样抛出。asyncio.CancelledError 始终传播，不返回伪造 CANCELLED 或 SUCCEEDED。

每次 execute 的 timeout 覆盖锁等待、几何测量和全部输入步骤。正常输入无重试。失败/取消后在执行锁内执行最多 **额外 1 秒** 的 best-effort 释放，检查原 connection/page/session/generation；身份失效时不向新绑定发送释放。清理释放本 Provider 的所有已记录按住输入，先普通键、再修饰键、再鼠标按钮。它可能触发 DOM keyup/mouseup/click，是新的副作用，不能撤销已输入文本或已完成动作。尚在锁外等待的调用失败或取消，不清理其他调用的状态。

`last_error: ErrorDetail | None` 和 `input_state_uncertain: bool` 是只读诊断属性；ErrorDetail.details 包含 stage、completed_steps（已确认输入命令数）、input_attempted、release_confirmed、outcome_uncertain、input_state_uncertain、held_button_count、held_key_count。release_confirmed=true 也可表示无需释放；它不是回滚确认。响应丢失时即使释放响应成功，仍保守保留状态不确定并停止后续输入，因为迟到命令效果无法证明。旧绑定带有按住状态时换绑也拒绝继续。last_error 保留最近一次失败/取消/清理诊断，不记录文本或具体按键序列。

不确定状态没有自动 reset：由上层停止动作队列、检查副作用并恢复已知浏览器状态（例如关闭自建测试目标、创建干净目标），然后创建新 Provider。仅在同一未知状态页面上重建 Python 对象不能证明浏览器已释放输入。单纯锁等待超时且无输入发送不会使 Provider 失效；FAILED 的 retryable 一律为 false，不给 Runtime 自动重放许可。

### 输入真实验收

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9338" # 已启动的隔离实例
$env:BCA_INPUT_OUTPUT = "$PWD\input-artifacts"
.\.venv\Scripts\python.exe examples/input_browser.py --endpoint $env:BCA_CDP_ENDPOINT --output $env:BCA_INPUT_OUTPUT
# 或 opt-in pytest，未配置 endpoint 时跳过真实测试：
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_input.py -v --basetemp=.test-artifacts/pytest
```

示例仅操作自建两个页面，最后关闭它们和自己的会话连接；不负责启动/关闭用户提供的浏览器。受控页面禁用中键自动滚屏和右键菜单，保留 DOM 输入事件及 textarea 默认编辑行为。报告只保存该测试页的文本和事件，不收集用户网页。实际截图识别红色区域像素，经过 Frame.pixel_to_css 后点击并检查 DOM target/坐标，覆盖 DPR 1/1.5/2、全图/区域、滚动条和非零滚动。还验证三按钮拖动、组合键、Unicode、导航、换绑、resize 越界及 close 释放。输入不使用 DOM 脚本代替 CDP。

`input-artifacts/input-report.json` 保存浏览器版本、ActionResult、DOM 事件、六张 PNG 的元数据、坐标误差、各类样本数/中位数/原始耗时，以及 pending/reader/connection 清理结果。临时 profile、pytest 和额外回归证据集中于被忽略的 `.test-artifacts/`；最终 input-artifacts 保留供审查。完整本轮质量结果及边界见 [交接报告](BCA-01.3_HANDOFF.md)。
