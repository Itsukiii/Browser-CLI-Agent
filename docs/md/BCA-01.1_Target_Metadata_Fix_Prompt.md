# BCA-01.1 — Target 元数据一致性修复

## 背景与实测结论

项目：Browser CLI Agent（BCA），根目录 `bca/`，版本 `browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2`。

真实 Edge 157 浏览器的两轮诊断文件为 `navigation-debug.json` 和 `navigation-debug-2.json`。第二轮明确确认：

- `data:` URL 和本地 HTTP 测试的 `Page.navigate` 均返回正常结果（无 `errorText`）。
- `Runtime.evaluate` 读取的 `document.title` 与 `location.href` 在导航后正确。
- `Target.getTargetInfo` 查询结果也返回最终标题 `BCA-01.1-Navigated` 及正确 URL。
- `BrowserSession.bound_target.title` 在长时间等待后仍保留 CDP 事件中较早的临时 URL 标题。
- 记录的 `Target.targetInfoChanged` 事件均为 browser-level（sessionId=null），且最后一次事件携带的仍是临时标题；未观测到包含最终页面标题的后续事件。
- Target ID、CDP sessionId、generation 在正常导航中保持稳定；关闭连接时 pending_count=0、reader_running=false。

**修复目标：保证调用方在明确请求刷新后能够取得权威且与当前绑定身份一致的 Target 元数据。** 现有事件仍用于快速缓存更新。

## 工作要求

先核对仓库当前 `docs/INTERFACES.md`、`docs/BROWSER.md`、`src/bca/core/browser/`、`tests/core/browser/` 和 `PROTOCOL_VERSION=2`。以真实代码为准，保持 BCA-00 公共契约兼容。此次集中修复 BrowserSession 的元数据刷新路径和相关真实浏览器验收，不修改其他子系统的接口。

### 1. BrowserSession 主动刷新接口

在 `src/bca/core/browser/session.py` 为已绑定的页面提供：

```python
async def refresh_target(self) -> BrowserTarget: ...
```

- 使用 browser-level `Target.getTargetInfo`，传入当前 `targetId`。
- 严格校验返回的 `targetInfo` 类型、targetId、type 与现有 BrowserTarget 结构。
- 在发起请求前记录当前 CDPConnection 对象、targetId、sessionId、generation；收到响应后在更新 `_target` 前核验这些身份仍然一致且会话仍 ready，防止旧请求覆盖新绑定。
- 采用现有 BrowserError / TargetLostError / CDP 异常体系处理失效、超时、无效响应和目标关闭；传播 asyncio.CancelledError。
- 保持 `bound_target` 同步属性表示缓存快照；`refresh_target` 是显式异步强制读取，不将属性访问变成网络 I/O。
- 同一次正常导航不得改变 generation、page_id 或 sessionId；刷新只更新 Target 描述信息。
- 维护现有 `Target.targetInfoChanged` 事件路径，允许其低延迟更新缓存。
- 评估并避免刷新与新事件的竞态覆盖：旧的查询结果不得覆盖刷新期间已失效或已切换的会话。对同一会话内事件和查询的时序给出合理策略并写入测试。

### 2. 绑定初始元数据

在绑定成功后提供可靠的初始元数据获取路径。可以在 bind 完成时主动刷新，或者设计明确的首次 refresh 调用策略；选择需说明对启动时延、异常和原有生命周期契约的影响。不要因页面初始 title 仍为临时值就将合法绑定判定为失败。

### 3. 修改真实浏览器集成测试

调整 `tests/core/browser/test_real_browser.py`：

- 保存并检查 `Page.navigate` 的正常结果与 `errorText`。
- 导航后以 `Runtime.evaluate` / `Target.getTargetInfo` 验证页面实际加载和目标描述，再通过 `session.refresh_target()` 校验缓存同步。
- 保留且严格验证导航前后 Target ID、sessionId、generation 一致。
- 保留目标关闭后 session 失效、pending 清零、Reader 和 WebSocket 释放的断言。
- 对页面实际加载采用有界等待，区分加载失败与缓存未刷新。勿简单增大等待时间以掩盖旧逻辑缺陷。
- 继续仅创建、操作和关闭测试自身的 Target。

### 4. 回归测试

新增或调整模拟 CDP 单元测试，至少覆盖：

- BrowserSession 初始元数据为临时标题，显式刷新后变为最终标题。
- `Target.targetInfoChanged` 未携带最终标题时，主动查询仍可更新缓存。
- 正常导航的元数据刷新保持目标和 CDP Session 身份不变。
- `refresh_target()` 在请求期间遇到 unbind、切换 Target、断线、close 或 generation 变化时，不写入旧结果。
- 请求失败、目标消失、非法 TargetInfo、超时及取消时的异常和资源清理。
- 事件与刷新交错时不发生旧 Session 元数据覆盖。

运行项目内 pytest、mypy strict、Ruff 检查和格式检查。保留现有通过的测试。

### 5. 文档与交接

更新 `docs/BROWSER.md` 对 `bound_target` 快照语义和 `refresh_target()` 使用方法的说明；补充“导航后获取当前元数据”的最小示例。

完成后产出 `BCA-01.1_METADATA_FIX_HANDOFF.md`，包含修改文件、API 与竞态设计、测试命令及实际结果、真实浏览器验证状态、公共协议影响，以及是否满足 BCA-01.1 最终验收。

如果当前 Codex 环境无法连接用户本机的 9222 调试端口，请仅报告未执行的真实浏览器验收，不标记通过。用户将自行执行：

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9222"
.\.venv\Scripts\python.exe -m pytest tests/core/browser/test_real_browser.py -v -s
```

当前阶段完成修复与验收后停止，等待 BCA-01 子会话审查，然后再开展 BCA-01.2。
