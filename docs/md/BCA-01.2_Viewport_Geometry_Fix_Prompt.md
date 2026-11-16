# BCA-01.2 真实 Edge 视口几何兼容性修复

## 背景与可复现故障

BCA-01.2 本地回归为 185 passed、2 skipped；真实 Edge 157 / CDP 1.3 集成测试在第一次截图的几何测量阶段失败。

执行：

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:BCA_CAPTURE_OUTPUT = "$PWD\capture-artifacts"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_capture.py -v -s
```

异常：

```text
src/bca/core/browser/capture.py:180
CaptureError: layout and visual viewport disagree
```

`BrowserCaptureProvider._measure()` 从 `Page.getLayoutMetrics` 提取 `cssVisualViewport.clientWidth/clientHeight` 与 `cssLayoutViewport.clientWidth/clientHeight`，目前在二者宽高不完全相等时直接拒绝截图。真实桌面浏览器中两种视口尺寸可能有合法差异，因此此条件不应作为普遍有效的前提。

## 任务

修复 BCA-01.2 的视口几何处理，使真实桌面 Edge 在常见视口差异下能够采集 PNG 完整视口和区域截图，且返回 Protocol 2 `Frame` / `Viewport` 的坐标语义准确。

### 实施要求

1. 阅读 `src/bca/core/browser/capture.py`、`examples/capture_browser.py`、`tests/core/browser/test_capture.py`、`tests/core/browser/test_real_capture.py`、`docs/INTERFACES.md` 和 `docs/BROWSER.md`，明确当前截图截取的是哪一个坐标空间的哪个矩形。
2. 修正 `_measure()` 对 `cssVisualViewport` 与 `cssLayoutViewport` 尺寸强制相等的假设。分别处理它们的宽高、偏移、缩放、滚动信息；从 CDP 的实际截图行为和 Protocol 2 坐标约定推导正确的截取区域和 `Viewport` 字段，而不是简单移除校验。
3. 如果需要获取真实返回值，在失败处增加**有限、可读的几何诊断输出**，打印 relevant viewport metrics、DPR、zoom 和 screenshot clip（不输出图片二进制），用于精确识别尺寸差异；诊断不能代替修复。
4. 保持 `Frame.pixel_to_css()` 契约：图像像素映射到可见视口 CSS 坐标；DPR 仅作为元数据，不能额外乘除；文档 scroll 不应再次加进视口输入坐标。
5. 处理有滚动条、DPR=1/1.5/2、页面浏览器缩放、非零滚动，以及完整截图和浮点 CSS 区域裁剪；对无法建立可靠坐标映射的情形给出明确异常。
6. 保留截图的真实 PNG 尺寸、格式/像素校验、生命周期/会话代际检查、总超时/取消/连接失效处理。Protocol 2 的现有模型与 Provider 抽象保持兼容。
7. 增加有代表性的回归用例，覆盖 visual/layout 不等但合法的情况、裁剪边界、内容像素和 `pixel_to_css` 映射；原有模拟测试必须继续通过。
8. 更新真实浏览器集成测试和 `docs/BROWSER.md`，使测试在真实环境中验证尺寸与截图像素位置，而非仅凭不抛异常判定成功。

### 验收

先运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -W error
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

真实浏览器由用户运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:BCA_CAPTURE_OUTPUT = "$PWD\capture-artifacts"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_capture.py -v -s
```

请生成 `docs/BCA-01.2_VIEWPORT_FIX_HANDOFF.md`，记载发现的真实根因或仍存在的条件性判断、修复代码、几何语义、回归结果，以及用户真实测试的执行方法。真实测试未在代理环境执行时需如实标注。
