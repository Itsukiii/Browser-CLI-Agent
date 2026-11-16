# BCA-01.2 / Capture & Coordinates — Codex 开发任务

> 项目：Browser CLI Agent（BCA）  
> 阶段：BCA-01.2  
> 日期：2026-11-12  
> 基线：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 前置阶段：BCA-01.1 已由用户在 Windows / Python 3.14.7 / Edge 157 / CDP 1.3 上完成真实浏览器集成测试（`1 passed in 0.40s`）；完整回归 `152 passed in 6.60s`，mypy strict、Ruff lint / format 均通过。

## 1. 首先核对仓库

在当前仓库中先阅读：

- `BCA_PROJECT_CONTEXT.md`（若在项目共享来源中）和 `BCA-01_Browser.md`；
- `docs/INTERFACES.md`、`docs/BROWSER.md`、`docs/ARCHITECTURE.md`；
- `src/bca/core/protocol/models.py`、`src/bca/core/protocol/__init__.py`；
- `src/bca/core/providers/base.py`、`src/bca/core/providers/registry.py`；
- `src/bca/core/browser/{connection,session,targets,models,errors}.py`；
- `tests/core/browser/` 现有测试，包括 BCA-01.1 的真实浏览器测试。

以仓库实际代码和已冻结的 Protocol 2 为准，复用 BCA-01.1 的 `BrowserSession`、`CDPConnection`、错误模型及生命周期管理。特别核对 `BrowserSession.refresh_target()` 的实际接口与状态行为。

## 2. 本阶段目标与范围

实现 CDP 截图能力和完整的截图—CSS viewport 坐标元数据，提供符合既有 `CaptureProvider` 抽象的浏览器采集实现，以便后续 Runtime 通过 `capture(page_id)` 按需采集。

需要交付：

1. 针对当前显式绑定的 Target 调用 `Page.captureScreenshot`，支持完整可见视口截图，默认 PNG；如实现 JPEG，须提供质量参数校验与测试。
2. 构造 Protocol 2 `Frame`，包含正确的实际像素 `width/height`、不可变编码 `data: bytes`、`ImageFormat`、`Viewport`、`page_id`、`session_id`、UTC `captured_at` 与唯一 `frame_id`。
3. 正确采集并规范化截图时的 CSS viewport 尺寸、`device_scale_factor`、`scroll_x/y` 和 `capture_x/y`、`capture_width/height`。坐标语义必须与 `Frame.pixel_to_css()` 一致。
4. 支持按 **CSS viewport 坐标** 指定矩形进行区域采集，保证返回 Frame 中的裁剪来源位置与图片实际像素对应。可采用浏览器内部的具体方法（例如 `capture_region(...)`）；既有公共抽象 `CaptureProvider.capture(page_id)` 的签名保持一致。
5. 对 CDP 截图失败、无有效页面、页面在截图期间切换/关闭、响应数据异常、超时与协程取消进行清晰处理。
6. 给出可手动执行的真实 Edge 截图示例及可复现的集成测试；记录完整截图、区域截图耗时的实际测量方式和结果（若无法在代理环境运行真实浏览器，明确标注用户待测）。

## 3. 已确认公共契约（严格遵守）

- `CaptureProvider.capture(page_id: str) -> Frame`，异步；Provider 具有 `available`、`async start()`、`async close()`，能力名 `capture`。
- `Frame(*, width: int, height: int, data: bytes, format: ImageFormat, viewport: Viewport, page_id: str, frame_id: str=..., captured_at: datetime=..., session_id: str|None=None)`；模型为冻结的关键字 dataclass。
- `Viewport(*, width: float, height: float, capture_width: float, capture_height: float, device_scale_factor: float=1.0, scroll_x: float=0.0, scroll_y: float=0.0, capture_x: float=0.0, capture_y: float=0.0)`，所有空间字段单位为 **CSS 像素**；截图矩形须在 viewport 内。
- `Frame.width/height` 是实际图像像素，`Frame.data` 为 PNG 或 JPEG 编码的 `bytes`；图像数据不可变共享，Protocol 2 只做文件签名校验，Browser 层需要确保数据和尺寸真实一致。
- 坐标公式：`css_x = capture_x + x * capture_width / frame.width`，`css_y = capture_y + y * capture_height / frame.height`；`device_scale_factor` 仅作诊断元信息，映射时不再乘/除 DPR。`scroll_x/y` 不加入视口输入坐标。
- `page_id` 为绑定目标的 Target ID，`session_id` 为当前 CDP attach 的 Session ID。截图期间必须防止跨 Target / session / generation 的失效结果返回。
- 时间戳须带 UTC 时区；统计耗时使用单调时钟。

## 4. 推荐设计

### 4.1 模块组织

在 `src/bca/core/browser/` 实现专门的截图/视口测量逻辑（名称可按仓库风格确定），并提供实现 `CaptureProvider` 的浏览器具体类。BrowserSession 是浏览器连接及绑定的所有者，Capture Provider 借用 Session，管理自身启动/关闭状态，不关闭外部拥有的浏览器连接。

根据现有 ProviderRegistry 实际语义注册和查询该实现；在文档中说明创建、start、capture、close 的调用路径。

### 4.2 截图与视口语义

- 优先使用 `Page.getLayoutMetrics` 提供的 CSS 视口信息，并结合必要的 `Runtime.evaluate` 获取浏览器当前实际 `devicePixelRatio`、滚动偏移与视口相关细节。明确 layout viewport 与 visual viewport 的差异，并基于 Protocol 2 的 **可见 viewport CSS 坐标** 定义一致实现。
- 对 `Page.captureScreenshot` 的 `captureBeyondViewport`、`fromSurface`、`clip`、scale 等参数选型给出明确理由。对裁剪区域与 CDP 文档坐标之间需要的变换在适配层完成，保证 Frame 暴露的仍是 viewport CSS 空间。
- 注意浏览器缩放、DPR、滚动、截图实际像素数可能不一致；不得用固定 DPR 乘法代替解码后的宽高，也不得在 `pixel_to_css` 里重复缩放。
- 截图需按实际编码解码 Base64，检查图像完整性、格式与宽高。选择轻量且可说明的图像尺寸识别/完整性校验策略；如需要新增依赖，请说明成本并更新 `pyproject.toml`。
- `capture_region` 的矩形应验证正尺寸、非负坐标、与当前视口边界；对小数裁剪边界、像素四舍五入及结果覆盖范围建立明确、可测试的规则。`Viewport.capture_*` 描述实际截图覆盖的 CSS 区域，而非未兑现的请求值。
- 采集前后记录 Session 身份与 generation；只有身份保持一致才返回 Frame。对于页面关闭/切换和协程取消，保持既有连接层请求清理语义。
- 保持截图请求按需发生，避免在 Capture Provider 内引入自行循环的调度；截图频率由后续 Runtime 决定。

### 4.3 异常与生命周期

保持 Provider 抽象已定义的错误语义：`page_id` 非法或参数不合法按既有 ValidationError；Provider 未就绪按 CapabilityUnavailableError；采集失败按 ProviderError 或现有明确的 Browser 错误映射规则。`asyncio.CancelledError` 正常传播，不能伪造成功 Frame。保留调试所需的内部原因链，不打印图像字节。

调用者传入的 `page_id` 必须与当前绑定 Target 匹配。Provider 重复 `start`、重复 `close`、在 Session 已关闭/断开后的行为应有测试。

## 5. 测试与验收

### 5.1 自动化测试

至少覆盖：

- 合法完整 PNG 截图生成 Frame，真实像素尺寸、PNG 签名与 session/page 标识匹配；
- 指定区域截图，裁剪偏移、截图范围和 `Frame.pixel_to_css()` 映射准确；
- DPR=1、DPR≠1、非等比实际像素尺寸、非零滚动、非零裁剪偏移；
- viewport 发生变化，以及浏览器缩放相关的几何数据一致性；
- 截图响应缺字段、非法 Base64、错误编码、无效图像、尺寸不符、CDP command error 和超时；
- target 无绑定、page_id 不匹配、采集中 target 失效、重绑、断线、关闭；
- 并发请求、取消、Provider 生命周期和无泄漏清理；
- 与 ProviderRegistry 的注册及查询集成。

### 5.2 真实浏览器验证

新增 opt-in 的真实 Edge/CDP 测试或扩充现有浏览器集成测试，限定操作到测试自己创建的页面/Target。建议使用内置测试 HTML（有色网格、可观测坐标标记、滚动区域）验证：

- 真实完整视口截图可打开、尺寸准确；
- 真实 CSS 区域裁剪截图对应正确视觉位置，`pixel_to_css` 映射正确；
- 改变 viewport 大小、浏览器缩放或设备比例时的映射；对于环境无法控制的维度，记录未测项并给出可重复步骤；
- 后台标签页或 Canvas/WebGL 场景的可用性/新鲜度进行有限、明确的验证；
- 导航/关闭期间截图错误及资源清理；
- 测量截图耗时，报告样本数、单位及测量口径。

实时浏览器测试在用户机运行时使用现有 `BCA_CDP_ENDPOINT=http://127.0.0.1:9222` 机制；不要修改或关闭用户已有标签。

### 5.3 统一质量检查

```powershell
.\.venv\Scripts\python.exe -m pytest -W error
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

将模拟通过与真实浏览器通过分开报告。保持 BCA-01.1 已有测试继续通过。

## 6. 文档与交接

- 更新 `docs/BROWSER.md`，写明 Capture Provider 的公开类、构造方式、截图 API、坐标定义、异常及示例调用。
- 如新增依赖，更新工程配置和必要开发文档。
- 生成 `BCA-01.2_HANDOFF.md`：实际变更文件、API、截图与视口处理策略、坐标公式/裁剪规则、测试结果（模拟与真实分列）、性能测量、剩余限制和用户手动验证命令。
- 如发现 Protocol 2 现有字段不能表达真实截图几何，请先在交接中提交兼容性问题和最小变更提案，协调公共协议后再实施共享协议变更。

## 7. 实施顺序

1. 校验仓库接口，写出简短实现设计和风险点。
2. 实现 CDP 截图与视口几何测量。
3. 完成 Capture Provider 适配、全帧和区域 API。
4. 增加自动化测试及真实浏览器集成测试。
5. 跑质量检查，更新文档、示例和 `BCA-01.2_HANDOFF.md`。

当前阶段只处理 BCA-01.2 的截图与坐标能力；接下来 BCA-01.3 将沿用 Frame 元数据完成输入动作坐标处理。
