# LITE-01 定向补证（恢复断点）

2026-11-23。G2 已取得真实 Edge 代理证据；G1 最终完整复测待隔离 Edge 9341 恢复。**本目录当前不能作为 G1/G2 全部最终通过的声明。**

## 复现

在 Windows 交互桌面打开原隔离 Edge。测试会置前自建窗口发送真实 Ctrl+0/±，运行期间避免切换焦点；只匹配测试页标题及 Chromium 窗口类，前台 HWND 不符时拒绝发送键盘事件。测试结束恢复 100% 并关闭自建 Target，保留既有 Target。

```powershell
$env:BCA_CDP_ENDPOINT = 'http://127.0.0.1:9341'
$env:BCA_LITE_ADDENDUM_OUTPUT = 'docs/evidence/LITE-01-addendum'
.venv/Scripts/python.exe -m pytest tests/lite -q -W error --basetemp=.test-artifacts/addendum-final-rerun
```

重新运行前将现有输出归档到独立目录；JSON/PNG 使用固定名字，会被新运行覆盖。须保存控制台日志，并仅在 JSON 和清理断言全部通过后更新报告。

## 证据索引

- `fault-drop.json`、`fault-disconnect.json`、`fault-close.json`：实际 Edge 响应经过代理后被丢弃/触发断连/延迟释放。记录请求 ID、代理事件、DOM oracle、输入结果、重试阻断和最终清理。前两项各只有一次 mousePressed；第三项没有输入。
- `zoom.json`：最后一次取得端点但未能取得前台焦点的失败现场，status=running 且 groups 为空，不是通过证据。六张 PNG 来自此前成功运行，不能和此 JSON 拼接为最终通过结果。
- `run-01`～`run-13`：开发失败原始日志，涉及窗口焦点/标题匹配、真实滚动精度误差，以及关闭 Target ACK 后列表尚未更新的竞态。后者改为有界等待 Target 消失。`zoom-failed-precision.json` 保留两种滚动测量原值。
- `run-14.txt`：4 passed；该轮完整 zoom JSON 在后续失败时被覆盖，需要重跑恢复完整可审查证据。
- `run-15-focus.txt`：完整 lite 28 passed / 1 failed，焦点拒绝；`zoom-failed-focus.json` 保存失败现场。
- `run-16-endpoint-unavailable.txt` / 当前 `lite-live.txt`：中断恢复时端点不可用，24 passed / 5 failed，不是实现通过结果。
- `offline.txt`：786 passed / 50 skipped；`browser-regression.txt`：113 passed。旧架构回归不作新验收证据。
- `mypy.txt`、`ruff.txt`、`format.txt`、`build.txt`：本轮静态/构建结果。

run-02 中误记录的非测试前台窗口标题已替换为 `[REDACTED unrelated foreground window title]`；其余失败内容保留。文本统一 UTF-8/LF。仅提交自建 fixture 截图，不提交浏览器 profile 或私人页面。
