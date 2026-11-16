# BCA-01.2 视口几何兼容性修复交接

最终状态（2026-11-13）：代理已接管并通过真实 Edge 验收，确认 DPR 浮点断言及测试页隐藏状态问题；最终截图不再发送 CDP clip。当前设计与 205 passed 结果见 [BCA-01.2_DELIVERY.md](BCA-01.2_DELIVERY.md)，以下保留上一轮分析记录。

## 已确认的问题与证据边界

用户提供的 `capture-artifacts/capture-report.json` 记录 Edge 157.0.4341.46 / CDP 1.3，在首次采集阶段失败，错误为 `layout and visual viewport disagree`，captures 为空；pending=0、Reader 停止、连接关闭。该报告没有原始 viewport 数值，不能断言此次差异具体是滚动条、设备模拟还是尺寸取整导致。原报告保持未改写。

确认的实现缺陷是把 cssVisualViewport 与 cssLayoutViewport 的宽高相等当作采集前提；旧模拟端还将同一个字典同时作为两类 viewport，未暴露此假设。根据 [CDP 协议定义](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)，两者分别描述视觉范围与布局范围，具有不同的尺寸、偏移及缩放字段，不能用对象尺寸相等替代坐标推导。

## 修复后的几何语义

本阶段仍只支持桌面 visual scale=1、offsetX/Y=0 的坐标契约。布局内容矩形和可见矩形拥有同一 CSS 原点，但边界可不同。完整截图定义为两者交集，即可见且属于布局内容的范围：

```text
Wcss = min(cssVisualViewport.clientWidth, cssLayoutViewport.clientWidth)
Hcss = min(cssVisualViewport.clientHeight, cssLayoutViewport.clientHeight)
clip = (visual.pageX * zoom, visual.pageY * zoom, Wcss * zoom, Hcss * zoom)
clip.scale = 1
```

滚动条或不可见的布局余量不计入内容截图；不截取更大的矩形后假称所有像素都对应内容。Frame.viewport.width/height 和完整 capture_width/height 为交集 CSS 尺寸，完整 capture_x/y=0；区域裁剪保持源 PNG 像素边界向外取整，再反算 capture_*。图片宽高来自 PNG 解码，不由 DPR 推算。

分别校验 visual/layout 宽高为有限正数、布局 pageX/Y 与 visual 原点相容，以及 Runtime.scrollX/Y 与 visual.pageX/Y 一致。LayoutViewport 的滚动字段是整数语义，允许与浮点 visual/runtime 滚动存在最多 1 CSS 像素的取整差异；clip 始终使用 visual 的精确滚动，不用容差值平移图片。大于该范围的原点差异仍拒绝。非零 visual offset 或捏合缩放仍明确拒绝，不将缺少支持的坐标空间混入 Protocol 2。

内部 Geometry 保留两组原始尺寸及 layout 滚动，即使交集未变，截图期间其中任一组变化也会被前后复核发现。保持 connection/Target/session/generation 保护、文档时间原点与 URL 检查、PNG 完整性校验、总超时和取消处理。公共 Frame、Viewport、pixel_to_css 和 Provider 抽象未改动。

## 修改文件与诊断

- `src/bca/core/browser/capture.py`：分别解析两类尺寸与滚动，建立交集，统一 clip 构造，保留原始几何供变化检测；debug 日志仅含有限几何元数据。
- `tests/core/browser/test_capture.py`：独立 layout 模拟数据，新增 15 项用例，涵盖 layout 较大/较小/两轴混合/小数差异，DPR 1/1.5/2 与 zoom 1/1.25/0.8；逐像素核对贴边裁剪与坐标、越界拒绝；非法尺寸、原点冲突、布局变化仍失败。原有 34 项继续通过。
- `examples/capture_browser.py`：采集前将白名单数值型 visual/layout metrics、DOM 尺寸、DPR、滚动及计划 clip 写入报告并打印。固定右下角的紫色色块位置由 DOM visualViewport/documentElement.clientWidth/Height 计算，独立于 Provider 内部几何。
- `tests/core/browser/test_real_capture.py`：沿用同一验收流程，要求三组 DPR 的几何记录和贴边截图产物。
- `docs/BROWSER.md` 与本文件：更新语义、验证步骤和限制；原 01.2 交接补充后续修复指向。

真实测试现在创建带横纵滚动条的页面，滚动至 (80,120)，分别测试 DPR 1/1.5/2。除了原中心色块与 Canvas，还核对 DOM 内容尺寸、PNG 实际尺寸（设备模拟条件下容许 2 像素的舍入差异）、右下角色块、35.25 CSS 像素贴边区域的颜色、边界与 pixel_to_css。完整 PNG 在断言前保存，便于失败定位；仅操作自身创建的 Target。

## 检查与真实验收状态

本地截图专项：49 passed。全量 `pytest -W error`：**200 passed，2 skipped**（两个 opt-in 真实浏览器测试未设置端点）。mypy strict 31 个源码文件通过；Ruff check 通过，format 77 个文件通过，git diff --check 通过。没有在代理环境启动或连接真实浏览器；用户所遇到的具体尺寸差异与修复后视觉结果仍需下列测试确认。不能把本地模拟通过当作真实 Edge 验收通过。

用户在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:BCA_CAPTURE_OUTPUT = "$PWD\capture-artifacts"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_capture.py -v -s
```

请回传完整 pytest 输出和新的 capture-report.json；如仍有像素断言失败，附相应 full/region/edge PNG。默认输出目录与上轮相同，会更新同名产物；需要保留旧结果可把 BCA_CAPTURE_OUTPUT 设置为 capture-artifacts-viewport-fix。实际耗时继续由 perf_counter 记录，未虚构真实性能数据。桌面手动 Ctrl+/- 缩放、WebGL 与捏合缩放的既有限制保持不变。
