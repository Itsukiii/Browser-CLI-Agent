# BCA-01.1 — 真实浏览器导航超时定位与修复

## 背景

项目：`browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2`。在 Windows / Edge 157 / CDP 1.3 的真实浏览器验收中：

- CDP 连接、两个 Target 的创建与枚举、显式 attach、`Runtime.evaluate("document.title")` 均成功。
- `Page.navigate` 返回后，等待 `BrowserSession.bound_target.title == "BCA-01.1-Navigated"` 超过 10 秒。
- 测试：`tests/core/browser/test_real_browser.py::test_real_discovery_bind_navigation_close`。

请先阅读实际仓库 `src/bca/core/browser/{session,connection,targets}.py`、`tests/core/browser/test_real_browser.py` 及 `docs/BROWSER.md`。现有实现中 `BrowserSession._event` 已订阅 `Target.targetInfoChanged`，并在目标 ID 匹配时更新 `_target`，不能预设问题一定在该函数。

## 诊断步骤

1. 在真实浏览器集成测试的导航点记录 `Page.navigate` 返回值（包括 `errorText`、`frameId` 等），核对导航是否确实被接受。
2. 导航后分别检查：
   - 对当前 attached session 执行 `Runtime.evaluate`，读取 `document.title`、`location.href`；
   - 通过 browser-level `Target.getTargets` 或 `Target.getTargetInfo` 查询对应 `targetId` 的标题及 URL；
   - `BrowserSession.bound_target` 当前缓存的标题及 URL；
   - 是否确实收到对应 `Target.targetInfoChanged`，其事件位于 browser-level 还是 session-level。
3. 对比这四处证据，确定故障属于导航失败、Target 元数据未变化、事件分发/订阅丢失，还是 Session 缓存未刷新。
4. 排查 `data:` URL 在当前 Chromium/Edge 版本上作为导航目标的行为。如果测试用例的导航目标本身不稳定，改用可复现、无外部网络依赖的本机测试页面或其他经实际验证有效的导航方案。保持测试真实验证“导航后 Target ID/sessionId/generation 不变且元数据更新”，不能仅放宽断言。
5. 基于真实根因实现最小修改，并添加回归测试。保留 Protocol 2 现有模型与 Provider 抽象。

## 验收与报告

- 真实浏览器测试必须报告实际结果；如环境没有 CDP 端点，标记未验证，不把 skipped 当作通过。
- 运行 `python -m pytest -W error`、`python -m mypy`、`python -m ruff check .`、`python -m ruff format --check .`。
- 在报告中记录导航前后的实际 `location.href`、`document.title`、TargetInfo 和 Session 缓存结果，以及修改原因、变更文件和测试结果。
- 若无法在 Codex 环境复现，提交一个能由用户本机运行并输出以上诊断信息的测试补丁/脚本，给出精确 PowerShell 命令。不要宣称真实浏览器验收通过。
