# BCA-01.2 / Capture & Coordinates 交接

最终状态（2026-11-13）：代理已亲自完成真实 Edge 验收及全量 205 passed；截图已改为原生 surface 加本地裁剪，最新设计、根因、证据和限制以 [BCA-01.2_DELIVERY.md](BCA-01.2_DELIVERY.md) 为准。以下为历史交付记录。

后续更新：首次真实 Edge 验证暴露了 layout/visual 尺寸相等的错误前提，已完成兼容性修复及增强测试。当前几何语义和检查结果以 [BCA-01.2_VIEWPORT_FIX_HANDOFF.md](BCA-01.2_VIEWPORT_FIX_HANDOFF.md) 为准；下文保留首次交付记录。

## 状态

01.2 实现及本地自动检查已完成，真实 Edge 截图测试按用户要求交由用户执行，尚不能宣布真实截图验收通过。01.1 修复后测试通过来自用户报告及本轮任务文档，未由代理重跑。未开展 01.3。

## 变更清单

| 文件 | 内容 |
| --- | --- |
| `src/bca/core/browser/capture.py` | PNG Capture Provider、视口测量、图像校验、区域裁剪、生命周期及错误处理 |
| `src/bca/core/browser/__init__.py` | 导出 BrowserCaptureProvider / CaptureError |
| `pyproject.toml` | 新增 Pillow>=12,<13；本机安装并验证 12.3.0 |
| `tests/core/browser/test_capture.py` | 34 项模拟测试：图像、几何、裁剪内容、身份、并发、异常、取消及 Registry |
| `examples/capture_browser.py` | 创建自有测试页面、保存 PNG/Frame 元数据、色块/Canvas 校验及耗时报告 |
| `tests/core/browser/test_real_capture.py` | opt-in 真实验证入口，复用示例验收流程 |
| `docs/BROWSER.md`、`README.md`、`docs/ARCHITECTURE.md` | API、依赖、使用与验证说明 |
| `docs/BCA-01.1_METADATA_FIX_HANDOFF.md` | 补充用户已通过 01.1 实测的后续状态 |
| 本文件 | 01.2 交接与边界 |

工作区原有 01.1 修改保留，没有回退。Protocol 2、CaptureProvider 抽象、ProviderRegistry、BrowserSession 及其 refresh_target 公共行为均未在本轮修改。版本保持 0.2.0。

## 实际 API 与生命周期

`BrowserCaptureProvider(session, *, timeout=10.0)` 实现能力名 `capture`：

- `available`，`async start()`，`async close()`。
- `async capture(page_id: str) -> Frame`：完整可见内容视口 PNG。
- `async capture_region(page_id: str, *, x: float, y: float, width: float, height: float) -> Frame`：CSS viewport 区域截图。

Session 由调用方 connect/bind，Provider 只借用，不自动选择目标。Registry.register 不负责启动；start 后可以按 CaptureProvider/具体类或能力名查询。Provider close 幂等且终止该 Provider 的后续使用，不断开 Session；start 在已关闭后抛 LifecycleError。未启动、未绑定、Session 断开/关闭时 available=false。Capture 捕获入口身份，等待锁后及每阶段复核，禁止跨 Target/session/generation 返回。并发请求在同一个 Provider 内串行，取消不会伪造 Frame，也不清除其他调用者的绑定。

异常映射：参数及 page_id 错误用 ValidationError；未就绪用 CapabilityUnavailableError；在途身份失效用 TargetLostError；截图数据和几何错误用 CaptureError（BrowserError/ProviderError）；CDP 命令/连接错误保持现有类型；总超时用 CDPTimeoutError；CancelledError 原样传播。不记录图像字节。

## 几何与图像策略

测量 cssVisualViewport/cssLayoutViewport，并由 Runtime.evaluate 取得 DPR、scrollX/Y、location.href、performance.timeOrigin。当前限定桌面 visual scale=1、offset=0、layout/visual 内容尺寸一致；zoom 字段缺失即拒绝，避免缩放猜测。可见内容不含滚动条。

截图用 Page.captureScreenshot(format=png, fromSurface=true, captureBeyondViewport=false)，完整内容视口 clip 的文档 DIP 坐标为 `(scrollX*zoom, scrollY*zoom, width*zoom, height*zoom)`，scale=1。不会修改页面滚动或把全文展开。CSS 与 DIP 的选型依据 [CDP 协议定义](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json) 中 viewport/zoom 字段；surface 与 clip 的处理参考 [Chromium PageHandler](https://raw.githubusercontent.com/chromium/chromium/main/content/browser/devtools/protocol/page_handler.cc)。实际 Edge 缩放效果仍待用户测试，源码分析不等于实测。

采用 Pillow 而非自行编写 PNG 解码器：严格 Base64、PNG 签名/IHDR、结构/CRC、完整像素解码；宽高从编码图像实际读取。压缩体约 12 MB、解码 1600 万像素上限；已有 WebSocket 单消息 16 MiB 限制仍有效。Pillow Windows CPython 3.14 wheel 本次约 7.2 MB，不依赖外部图像进程；Protocol 层仍仅依赖标准库。只支持 PNG，JPEG 不在本轮实现范围。

区域采取“完整截图后本地裁剪”，避免把 CSS 小数区域直接交给浏览器产生不明确的边界舍入。左上边界向下取整，右下向上取整至源图像像素，限制在图像边界内；返回 capture_* 描述实际覆盖区域，向外最多扩展不到一个源像素。图像内容回归测试逐像素比对裁剪结果，不仅比较宽高。

坐标保持原公式：`capture_x + x * capture_width / Frame.width`，Y 同理。两个轴独立，允许 DPR≠1 和非等比真实像素；DPR 仅诊断，scroll 不加入 viewport 输入坐标。区域截图不保证节省网络或更快，因为仍捕获完整视口并解码再编码。

截图前后几何、文档 URL/timeOrigin 必须一致；变化即拒绝，不自动重试。captured_at 为截图响应到达后的 UTC 时间，非浏览器合成器精确曝光时刻；frame_id 由 Protocol 默认生成唯一 UUID。图像验证/裁剪在线程运行，协程取消后该有界 CPU 工作会自行完成释放资源，不会继续调用 CDP 或提交 Frame。没有自动采集循环。

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m pytest -W error
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

最终全量结果：**185 passed，2 skipped**（01.1 与 01.2 真实浏览器测试未配置端点，未执行）。截图专项 34 passed；mypy strict 31 个源码文件通过；Ruff lint 通过，format 75 个文件通过，git diff --check 通过。常规隔离构建已成功生成 wheel/sdist；首次尝试 --no-isolation 因本虚拟环境未安装 setuptools 失败，改用项目标准隔离构建后通过。

测试覆盖：完整 PNG 与唯一帧标识；DPR 1/1.5/2、zoom=1/1.25、非等比 203×71；非零滚动、浮点裁剪、像素内容与映射；视口变化拒绝及两次采集间 resize；非法 Base64、错误格式、截断/损坏图像；无绑定、错目标、unbind、切换、同目标重绑、销毁、断线、两类 close；超时、取消、等待者取消；Registry 与 Provider 生命周期。原 01.1 模拟测试保留并纳入全量检查。

## 用户真实浏览器测试与性能记录

用户已启动 Edge 调试实例后，在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:BCA_CAPTURE_OUTPUT = "$PWD\capture-artifacts"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_capture.py -v -s
# 同时回归 01.1 可运行：
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_browser.py tests/core/browser/test_real_capture.py -v -s
```

独立示例（相同验证流程）：

```powershell
.\.venv\Scripts\python.exe examples/capture_browser.py --endpoint http://127.0.0.1:9222 --output .\capture-artifacts --samples 3
```

只操作自己的两个 Target。输出完整/区域 PNG、background-canvas.png、capture-report.json；报告包括浏览器版本、Frame 元数据、visibilityState、关闭后的拒绝及清理状态。默认在 640×480/DPR1、800×600/DPR2 两种条件下完整与区域各测 3 次，perf_counter 统计整个 await capture，单位 ms，包含几何测量、CDP、解码/裁剪，不含磁盘保存；输出全部样本和中位数。本代理没有启动或连接真实浏览器，**实际耗时、真实色块位置和 Edge 截图验收均待用户执行**。

请回传 pytest 输出、capture-report.json，必要时附对应 PNG。报告失败也保留已有样本。后台场景仅当记录到 hidden 时可视为后台验证；Canvas 仅验证蓝色变绿色这一受控变化，不外推至游戏帧率。

## 限制与后续边界

- 当前不支持捏合缩放、非零 visual viewport 偏移。兼容性问题是 Protocol 2 未规定 visual 原点到布局视口输入坐标的转换；最小提案是后续统一使用布局视口坐标，或新增明确的 visual offset/scale 字段并协调协议版本。本轮不改公共字段，也不输出含糊坐标。
- 真正 Ctrl+/- 页面缩放、WebGL、导航/关闭与截图同时发生的真实竞争仍未实测。桌面缩放人工步骤见 BROWSER.md；生命周期竞争已有模拟回归。
- 前后测量不能证明 DOM/Canvas 原子冻结，亦无法检测期间变化后恢复的所有情况；不承诺截图时刻到未来输入时刻页面不变。
- 每个 Provider 独立串行，建议单 Session 单 Provider；其他 CDP 客户端或外部页面操作不受锁控制。
- 图像解码线程无法被强制取消；受数据/像素上限约束完成后释放，不宣称硬实时取消 CPU 工作。
- 没有输入映射执行、识别逻辑、周期调度或 CLI 产品流程；这些留待 01.3 及后续阶段。
