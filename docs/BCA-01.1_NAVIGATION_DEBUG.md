# BCA-01.1 导航超时分析与取证

## 二次取证增量（2026-11-12）

已读取用户提供的 `navigation-debug.json`（记录时刻 `2026-11-12T11:59:08.029393+00:00`，Edge `157.0.4341.46` / CDP `1.3`）。原始文件保持不变。以下是该次真实运行的证据，不是模拟结果：

| 观测项 | data 模式 | HTTP 模式 |
| --- | --- | --- |
| 文档 title / readyState | `BCA-01.1-A` / `complete` | `BCA-01.1-A` / `complete` |
| 文档 href、TargetInfo.url、缓存 url | 均为原始编码后的 data 起始 URL | 均为 `http://127.0.0.1:52878/start` |
| TargetInfo.title | `BCA-01.1-A` | `BCA-01.1-A` |
| Session 缓存 title | `data:text/html,<title>BCA-01.1-A</title><p>BCA-01.1-A</p>` | `127.0.0.1:52878/start` |
| 最后一次导航前采样时刻 | 约 10.132 秒 | 约 10.169 秒 |
| 观察到的变化事件 | 2 条 browser-level，标题为空或临时标题 | 2 条 browser-level，标题为空或临时标题 |
| 导航返回 / 导航后样本 | 未调用 / 空列表 | 未调用 / 空列表 |

两种模式均记录关闭 Target 成功，连接断开、pending=0、Reader 已停止。临时标题事件的 `cache_at_callback` 与事件标题相同，说明至少这些 browser-level 事件已经到达并更新了缓存。没有观察到最终标题事件，不能由此证明浏览器绝对没有发出，也不能把当前证据归为 session-level 订阅不匹配。

本次已确认的是**导航前缓存与文档、查询结果不一致，以及旧诊断流程被这个条件阻断**。原先真实集成测试的导航失败原因、实际 `Page.navigate` 返回值和导航后行为仍待确认；HTTP 同样出现初始缓存过期，因此目前无依据把现象仅归因于 data URL。

诊断流程已调整：

- 初始文档 title/href 与 TargetInfo 的 targetId/title/url 均符合预期，就继续导航；缓存 title/url 不一致记录为 `initial_cache_stale=true`，不写回缓存。
- `initial_samples` 保留初始探测序列，`before` 保留最后一次导航前观测。文档或 TargetInfo 超时未就绪时，以 `initial_status` 区分 `initial_document_not_ready` 和 `initial_target_not_ready`，保留原始探测响应/异常后终止该用例。
- 导航返回对象或异常仍完整保存。导航后至少采样两次（间隔约 0.2 秒），若尚未达成终止条件则继续到等待期限；极短 `--wait` 也会完成第二次采样。保留文档、TargetInfo、缓存、身份及事件时序的原有独立分类。
- 初始缓存过期标志独立于导航后 `classification`：即使之后为 `ok`，初始问题的证据仍在。默认输出改为 `navigation-debug-2.json`，避免默认覆盖首轮报告。
- 只改动诊断示例、模拟测试和本报告；`src/bca/core/`、Protocol 2 公共 API 和原真实集成测试保持不变。

请在已开启的 Edge 调试实例上执行：

```powershell
.\.venv\Scripts\python.exe examples/navigation_debug.py --endpoint http://127.0.0.1:9222 --mode both --output .\navigation-debug-2.json
```

请回传 `navigation-debug-2.json`。脚本退出码 1 仍会保存报告。第二轮数据回来后，若文档和 TargetInfo 持续正确而缓存过期，最小修复方向是评估显式元数据刷新并保留绑定身份检查；若观察到最终标题事件但缓存未更新，则应修复对应分发/处理路径。当前不提前引入轮询或扩大订阅作用域，也不放宽完整验收断言。

新增 8 个回归用例覆盖两种 URL 模式下的“初始缓存过期仍导航”，随后成功、缺少更新事件、导航返回错误三种分支，以及初始文档/TargetInfo 错误时禁止导航并保存证据。诊断测试共 15 项通过。全量 `pytest -W error` 为 **132 passed、1 skipped**（真实浏览器缺少端点）；mypy 29 个源码文件通过，Ruff 检查及格式检查通过。已核对运行库及原真实测试无 diff。真实第二轮浏览器测试由用户执行，尚未验证。

## 首轮分析记录（保留历史）

当前结论：已确认原集成测试忽略了 `Page.navigate` 返回值，导致导航失败和缓存未更新都可能表现为同一个标题等待超时；尚未取得本次真实浏览器的四路证据，不能据此认定运行库缺陷或 `data:` URL 限制。

## 已确认的代码路径

- `tests/core/browser/test_real_browser.py` 调用 `Page.navigate` 后直接等待 `bound_target.title`，没有保存或检查返回的 `errorText`。
- `connection.py` 区分 CDP 顶层 `error` 和正常 `result`。`Page.navigate` 的导航失败信息可以位于 `result.errorText`，因此命令返回不等于页面跳转成功；`frameId` 也不足以证明成功。这符合 [CDP 官方协议定义](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)。
- `session.py` 的 `_watch` 已订阅 browser-level `Target.targetInfoChanged`；`_event` 已按 Target ID 更新 `_target`。不能将本次超时归因于缺少处理函数。
- `connection.py` 的 `_dispatch` 按事件顶层 sessionId 分发，默认订阅只接收 browser-level 事件。如果实际只收到 session-level 事件，内部订阅不会收到；是否发生须以真实事件为准。
- `TargetManager` 查询结果不会自动写回 Session 缓存。因此读取 `Target.getTargetInfo` 可以用于独立对照，不会掩盖事件更新问题。

用户报告中连接、创建/枚举两个 Target、attach 和首次 Runtime.evaluate 已成功，故本次问题位于后续导航阶段，与此前代理环境的初始标题等待超时不能混为一谈。

## 本次变更

新增 `examples/navigation_debug.py`，独立采集导航返回值、文档状态、TargetInfo、Session 缓存和事件作用域。新增 `tests/core/browser/test_navigation_debug.py`，通过模拟 CDP 连接验证诊断分支与资源清理。本次未修改 `src/`、Protocol 2、Provider 抽象及原集成测试的验收断言。

脚本分别运行原测试的 `data:` URL 和临时本机 HTTP 页面，两种模式使用各自新建的 Target。HTTP 服务仅监听 `127.0.0.1`，不依赖外部网络；结束时关闭自身创建的 Target、连接和临时服务。脚本不启动浏览器，也不关闭已有标签页。

## 用户执行

保留已开启远程调试的本机测试浏览器，在项目根目录 PowerShell 执行；如果调试端口不同，请替换 9222：

```powershell
.\.venv\Scripts\python.exe examples/navigation_debug.py --endpoint http://127.0.0.1:9222 --mode both --output .\navigation-debug.json
```

浏览器启动方法见 [BROWSER.md](BROWSER.md)。如只复现原导航，使用 `--mode data`。默认每阶段等待 10 秒，单次探测还受请求超时约束，整体运行可能超过 20 秒。存在异常证据时脚本退出码为 1，但仍保存 JSON；这是诊断结果，不代表报告未生成。

请回传 `navigation-debug.json`。每个 `cases[]` 中可直接对照：

| 证据 | JSON 字段 |
| --- | --- |
| 浏览器/CDP 版本 | `browser_version` |
| 导航原始返回或请求异常 | `navigation.response` / `navigation.exception` |
| 导航前文档 title/href/readyState | `before.runtime.response.result.value` |
| 导航前 TargetInfo / 缓存 | `before.target_info.response.targetInfo` / `before.cache` |
| 导航后文档和 TargetInfo | `samples[].runtime.response.result.value` / `samples[].target_info.response.targetInfo` |
| 导航后缓存和身份 | `samples[].cache`（含 page_id/session_id/generation/is_ready） |
| Target 变化事件 | `events[].target_info`，`top_level_session_id` 为 null 表示 browser-level |
| 事件与采样时序 | `events[].elapsed` / `samples[].elapsed` / `navigation_started_at` |
| 清理结果 | `cleanup_target` / `cleanup_connection` |

探测按顺序执行，不是原子快照；同时记录查询前后的缓存。分类只使用导航开始至最后一次采样之间的匹配事件，避免把清理阶段迟到事件误判为此前缓存未更新。短暂执行上下文错误会保留在样本中，等待期内继续采集。事件最多保留 200 条，超出数量记录于 `dropped_events`。

## 如何定位

| 观测结果 | 当前可支持的判断 |
| --- | --- |
| `navigation.response.errorText` 存在 | 导航返回失败；先检查具体错误，不能直接修改缓存逻辑 |
| 文档 title/href 未到目标 | 未确认页面跳转；进一步查看返回值、上下文错误和 URL |
| 文档已变化，TargetInfo 未变化 | 元数据层未反映跳转，暂不能归因于 Session |
| 文档、TargetInfo 已变化，缓存未变，只有 session-level 匹配事件 | 事件作用域与内部订阅存在差异，需据真实报文确定最小修复 |
| 文档、TargetInfo 已变化，缓存未变，已有 browser-level 匹配事件 | 优先检查内部事件处理、目标匹配与缓存覆盖路径 |
| 文档、TargetInfo 已变化，缓存未变，无匹配事件 | 需继续区分浏览器事件未发出和接收/分发丢失，脚本本身不能证明服务端未发送 |
| 三处均变化且身份不变 | 本轮导航检查通过，仍须完成原完整集成验收 |

若 data 模式失败而 HTTP 模式通过，只能先确认该环境中两种测试页面行为不同；结合具体返回值后再决定是否替换验收用页面，不能凭此泛化为所有 Edge 的 data URL 限制。最终验收仍应检查 Target ID/sessionId/generation 不变、元数据更新，以及目标关闭后的失效与资源清理。

## 验证状态

本次环境没有设置 `BCA_CDP_ENDPOINT`，遵循用户接管浏览器测试的安排，未连接或启动真实浏览器。真实导航前后的 href/title/TargetInfo/缓存数值均待上述脚本采集；没有把模拟结果当作真实结果，也没有宣布 BCA-01.1 验收通过。

本地检查结果：

- `python -m pytest -W error`：124 passed，1 skipped（真实浏览器测试缺少端点）。
- `python -m mypy`：29 个源码文件通过。
- `python -m ruff check .`：通过。
- `python -m ruff format --check .`：65 个文件通过。

新增的 7 项测试覆盖导航成功、返回 errorText、未实际跳转、Target 元数据滞后、事件缺失、session-level 事件，以及临时 HTTP 页面的响应和关闭；同时核验诊断目标清理、原有目标保留和迟到事件的时间边界。
