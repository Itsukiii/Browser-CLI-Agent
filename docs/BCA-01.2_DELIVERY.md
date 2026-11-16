# BCA-01.2 最终交付与真实浏览器验收

2026-11-13：代理已接手浏览器测试并完成修复。Windows / Python 3.14.7 / Edge 157.0.4341.46 / CDP 1.3，**全量测试 205 passed，零跳过，11.20 秒**，包含 01.1 和 01.2 的真实浏览器测试。01.2 在本文限定范围内可交付，不再需要用户代跑基础验收。

## 根因与实际修复

1. **DPR 精确相等断言错误。** 用户报告及本次有窗口 Edge 均返回 DPR `1.0000000298023224`、`2.0000000596046448`。这些是预期比例的浮点误差，旧测试 `== 1/2` 导致空消息 AssertionError。现在测试以 `rel_tol=1e-6` 检查 DPR；Frame 保留原始数值，真实 PNG 尺寸、颜色和坐标断言仍严格执行。
2. **测试页意外处于后台。** 创建第二个 Target 后，第一个测试页成为 hidden。后台 surface 在设备模拟下可能不更新，截图会超时；不应以这种状态执行前台基础验收。现在先显式激活自建测试页，前台/后台分开验证。Provider 本身不擅自激活页面。
3. **绘制提交与超时后重试。** Canvas 脚本执行完成不等于浏览器已提交绘制。测试在前台等待两次 requestAnimationFrame 后验证颜色。后台探测放在最后，超时后不盲目继续对同一页面截图，直接清理；背景超时只会明确记为能力限制，不伪造成功图像。本次最终后台实际通过，visibilityState 前后均为 hidden。
4. **截图路径简化。** 改用不带 clip 的原生可见 surface，再本地去滚动条/裁剪区域。此前 clip 会涉及浏览器临时视口处理；但对照实验表明超时不只发生于 clip，关键条件是后台页面，不能声称 clip 是已确认的单独根因。无 clip 路径减少坐标转换和临时视口干预，已在真实图像上验证。

上一轮的 visual/layout 差异修复保留。本次有窗口 Edge 真实数据为 visual 宽 `624.6666870117188`、layout 宽 `624`，说明实际同时存在视口尺寸取整差异与 DPR 浮点误差。

## 最终几何语义

- Runtime 测量 `innerWidth/innerHeight` 作为完整 surface 的 CSS 范围；CDP 图片按实际 PNG 宽高映射到该范围。
- 内容范围仍为同原点的 visual/layout 矩形交集。截图参数为 PNG、fromSurface=true、captureBeyondViewport=false，**无 clip**；scroll 不再用于设置文档截图偏移，原生 surface 已对应当前滚动位置。
- 若内容边界落在像素中间，仅保留完整位于内容内的像素，右/下边界取 floor。这样不会把部分滚动条像素伪称为内容。
- 区域请求的左上向下、右下向上取整，限制在上述完整内容像素范围；Frame.viewport.width/height 为逻辑内容范围，capture_* 为实际像素覆盖的 CSS 范围。完整截图的 capture_width/height 可能比 width/height 少于一个源像素，属明确的边缘量化，不拉伸图像来掩盖。
- `pixel_to_css` 使用实际 capture_* 与返回 PNG 像素，DPR 不额外参与映射，scroll 不加到 viewport 输入坐标。
- 会话代际、前后几何/文档检查、PNG 验证、取消和总超时机制保持；Protocol 2 公共字段和 Provider 抽象不变。

## 实测范围及证据

| 实例 | 结果 |
| --- | --- |
| Headless Edge，默认设备缩放，独立 9334 端口 | 01.1 + 01.2：2 passed / 2.75s |
| Headless Edge，force-device-scale-factor=1.5，独立 9336 端口 | 01.2：1 passed / 2.62s |
| 有窗口 Edge，force-device-scale-factor=1.5，独立 9337 端口 | 01.1 + 01.2：2 passed / 4.13s |
| 有窗口实例上全量 pytest -W error | **205 passed / 11.20s，无 skipped** |

每轮真实 01.2 覆盖 DPR 1/1.5/2，三种窗口尺寸，横纵滚动，完整、浮点区域和右下角贴边采集，真实颜色/边界像素，Canvas 更新，导航后采集，目标关闭与资源清理。最终报告有 27 张基础截图记录，另含前后台 Canvas PNG；代理也查看了完整 PNG，确认标记位置与图像一致。

最终证据位于 [capture-report.json](../capture-artifacts-delivery/capture-report.json)。图像示例：[DPR2 完整截图](../capture-artifacts-delivery/800x600-dpr2-0-full.png)、[右下角区域](../capture-artifacts-delivery/800x600-dpr2-0-edge.png)、[后台 Canvas](../capture-artifacts-delivery/background-canvas.png)。原用户失败报告保留在 capture-artifacts，未改写。

最终清理指标：pending_count=0、reader_running=false、connected=false。所有测试只修改和关闭自建 Target；测试浏览器使用仓库内独立 profile，没有使用或关闭用户 9222 浏览器。

本环境普通 Chromium sandbox 子进程无法正常渲染，因此**仅对这些隔离测试实例**使用 --no-sandbox、--disable-gpu、--in-process-gpu；不改系统设置，不修改用户浏览器启动方式。该环境因素与项目的 DPR/测试页可见性问题分开记录。

## 实际耗时

来源为最终有窗口实例报告，每种条件完整/区域各 3 次；perf_counter 测量整个 await capture，包含几何采集、CDP、解码和本地裁剪，不含磁盘保存。以下为中位数，单位 ms，不作为通用性能保证。

| 视口 / DPR | 完整截图 | 区域截图 |
| --- | ---: | ---: |
| 640×480 / 1 | 59.11 | 44.65 |
| 720×540 / 1.5 | 57.15 | 34.73 |
| 800×600 / 2 | 145.90 | 138.03 |

## 回归与复现

新增原生 surface 含滚动条、DPR 误差、边缘量化及真实裁剪覆盖的回归；截图专项 52 项。mypy strict 31 个源码文件、Ruff lint/format（78 个文件）检查通过，wheel/sdist 重新构建成功。测试结束后通过 Browser.close 关闭了本次创建的 9333–9337 五个独立实例，未操作用户 9222 实例。最终质量检查和产物以本报告为准，前期 HANDOFF 中未实测状态属于历史记录。

已有调试实例上的复现命令：

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
$env:BCA_CAPTURE_OUTPUT = "$PWD\capture-artifacts-repeat"
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.pytest-repeat
```

本次代理实际使用端口 9337 及 `--basetemp=.pytest-delivery`，因为默认系统 pytest 临时目录在代理权限下不可读。使用仓库内临时目录解决，没有更改系统目录权限。

## 已知边界

仅 PNG；捏合缩放/非零 visual offset 明确拒绝；手动 Ctrl+/- 页面缩放和 WebGL 未单独实测。后台能力受浏览器及设备模拟影响：本次无设备模拟的后台 Canvas 通过，但不保证所有隐藏页面的新鲜度。截图超时不自动重试，页面状态可变时由调用方决定恢复。原生解码线程的 CPU 工作不能强杀，但有大小上限且不访问 CDP；不承诺 DOM/Canvas 原子冻结。未开展 01.3。
