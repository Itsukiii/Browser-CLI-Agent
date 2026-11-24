# LITE-01 正式架构验收 · 2026-11-24

**决定：Accepted。** 基于 GitHub `lite` 最新源码和 Codex 提交的原始日志/JSON 进行静态与证据复核；架构主会话未在用户 Windows 机器重新执行测试。

## 检查范围

- 先前实现：`22b4c71`，包含 `CDPBridge`、`ObservationRef`、`MaaCDPController`、native 生命周期以及 DPR/ROI/raw 真实 Edge 测试。
- 最终 G1/G2：补测代码与几何精度修复 `8832601`；设计提交 `450523c`；原始证据 `3f01545`；交接归档 `358249c`（以 `lite` 当前提交图为准）。
- 关键测试：`tests/lite/test_real_addendum.py`、`tests/core/browser/test_capture.py`。
- 原始证据：`docs/evidence/LITE-01-addendum/final-2026-11-24/`，原有 LITE-01 证据与 `docs/lite/LITE-01_HANDOFF.md`。

## G1：真实 Edge 桌面缩放 — 通过

Windows 真实 Ctrl+0/± 控制 80%、100%、125%，每组 raw/non-raw，共六组；验证了实际 Runtime DPR 相对基线变化、visualViewport.scale=1、原生 callback raw 坐标映射及 DOM 命中。最大 DOM CSS 位置误差 0.993598px（≤1px）；重复点击、缩放后旧授权点击被拒绝。曾遇到浮点 scrollY 119.999992 与 120 的差异，`geometry.py` 只在重复滚动测量使用 1e-4 px 容差，并有 0.001 px 反例拒绝回归。

## G2：Edge 传输故障 — 通过

代理先实际接收 Edge mousePressed 成功响应，再丢 ACK 或主动断连。两场景 DOM 各观察到恰好一次 mousedown；代理只向 Edge 转发一次 mousePressed；上层 `input_outcome=unknown` 且后续截图/输入阻断，不重试。关闭竞争场景持有真实 Page.captureScreenshot 响应，取消后等待 native callback 排空，outcome=not_attempted、无点击。三种场景资源关闭后 pending=0、reader=false、connected=false、proxy socket=0、原有目标保留、新建目标清理完成。

## 执行证据

- 完整 lite 集合：`29 passed / 0 skipped / 19.45s`（2026-11-24），**不是** 29 个浏览器测试场景。
- 先前离线回归：`784 passed / 46 skipped`；定向补测工作时另有 `786 passed / 50 skipped` 与 Browser `113 passed`，系不同运行轮次，不累加。
- 原生 MaaFW Python/native 固定 v5.16.1，Windows 11 / CPython 3.14.7 / Edge 158。mypy、Ruff、wheel/sdist 已在源码补测轮次验证。

## Accepted 的能力边界

认可 CDP Target 安全绑定、同步 native callback 与异步 Browser 互通、BGR 截图、Maa raw/non-raw 坐标转换、单步观察授权、输入不确定性、native 取消/资源拥有权。尚未验证 OCR、可视业务回合稳定性、长时 RSS、完整 CLI 与雀魂实战；这些分别属于 LITE-02～06。

**下游约束：** 对手动命令启用 `require_authorization=True`；一次精确 ObservationRef 仅授权一步点击；原生 Job 成功不表示页面已完成业务动作；发生 unknown 时停止实例，不能替换 token 重试旧动作。`maafw==5.16.1` 下的私有 Destroy 封装升级必须重新核验。

## 决议

**LITE-01 正式 Accepted，LITE-02 设计评审可通过并启动 02.1 实现。** 本次归档只更新 `lite` 的文档/进度，不改产品源码，不合并 `main`。
