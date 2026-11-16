# BCA-01.1 — 导航及 Target 元数据同步二次取证

## 背景

项目基线 `browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2`。已通过真实 Edge 157 的 `examples/navigation_debug.py --mode both` 得到 `navigation-debug.json`：

- `data:` 和本地 HTTP 两种模式，初始页面 `Runtime.evaluate` 的 `document.title` 均为 `BCA-01.1-A`，`Target.getTargetInfo` 也返回 `BCA-01.1-A`。
- `BrowserSession.bound_target.title` 仍保留早期临时标题（data URL 字符串或 `127.0.0.1:<port>/start`）。
- 已记录 `Target.targetInfoChanged` 为 browser-level（顶层 `sessionId=null`），只看到早期临时标题事件，没有看到最终标题事件。
- 两种模式均在初始缓存标题等待阶段超时，`samples=[]`，没有实际进入 `Page.navigate`，因此原导航失败根因尚未确认。
- 两种模式的资源清理正常。

## 本轮目标

在保留原始证据的同时，让诊断继续完成真正的页面导航，准确区分浏览器文档状态、CDP TargetInfo、Session 缓存及事件送达状态。

## 任务

1. 阅读 `docs/BCA-01.1_NAVIGATION_DEBUG.md`、`examples/navigation_debug.py`、`src/bca/core/browser/{session,connection,targets}.py`、`tests/core/browser/test_real_browser.py` 和现有测试。
2. 只调整诊断流程：初始状态若 `Runtime.evaluate(document.title/location.href)` 与 `Target.getTargetInfo` 均达到预期，而缓存标题未同步，则**记录 `initial_cache_stale`，继续导航**，不再由该条件阻断取证。若浏览器文档或 TargetInfo 本身不符合预期，记录明确错误及证据，并合理终止该用例。
3. 在两种模式中实际调用 `Page.navigate`，完整保存 CDP 返回对象（特别是 `errorText`）或异常。记录导航后多次样本：`Runtime.evaluate` 的 `title/href/readyState`、`Target.getTargetInfo`、Session `bound_target/page_id/session_id/generation/is_ready`、匹配 Target 的 `Target.targetInfoChanged` 事件（包括顶层 sessionId 与相对时刻）。
4. 单独区分以下结果：导航返回 errorText；文档未成功导航；文档和 TargetInfo 已更新但缓存过期；TargetInfo 没有更新；三者一致。不得将事件未被观察到直接等同于浏览器绝对没有发出事件。
5. 加入必要的模拟回归测试，尤其是“初始缓存过期但文档和 TargetInfo 正确，诊断继续导航”。保证诊断脚本只清理自己创建的 Target 与本地 HTTP 服务。
6. 本轮保持 `src/bca/core/` 运行库及 Protocol 2 公共 API 不变；先收集证据，再提出最小修复建议。保持现有测试与类型检查通过。

## 本机执行和交付

在用户已启动的 Edge 调试实例上运行：

```powershell
.\.venv\Scripts\python.exe examples/navigation_debug.py --endpoint http://127.0.0.1:9222 --mode both --output .\navigation-debug-2.json
```

完成后向用户索取 `navigation-debug-2.json`，并输出一份简明诊断增量报告，解释哪些现象已得到证明、哪些仍待确认。不要把模拟测试通过表述为真实浏览器验收通过。
