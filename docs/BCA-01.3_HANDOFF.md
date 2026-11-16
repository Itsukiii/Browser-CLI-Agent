# BCA-01.3 输入与动作交接

2026-11-16 完成开发及本轮隔离真实 Edge 验证，停在 **01.3 交付与审查**。未进入 01.4。包版本仍为 0.2.0、PROTOCOL_VERSION=2；公共 Action、ActionResult、Provider ABC 和 Registry 均未更改。

## 实现与 API

- `src/bca/core/browser/input.py`：导出 BrowserInputProvider(session, *, timeout=10.0)，提供 start/close/available、execute(Action) -> ActionResult，以及 last_error、input_state_uncertain 只读诊断。
- `keys.py`：明确的逻辑键/US code/VK/text 映射；修饰键位、Shift 大写/数字标点、重复按键和 keyUp 状态。
- `geometry.py`：从 Capture 小范围提取原有只读视口测量；Input 和 Capture 共享内容矩形交集、滚动/缩放检查。Capture 对几何错误仍包装为原 CaptureError，截图裁剪逻辑及协议未变。
- `__init__.py`：公开 BrowserInputProvider；`tests/core/browser/test_input.py` 59 项模拟测试、`test_real_input.py` opt-in 真实入口；`examples/input_browser.py` 可独立运行并产生证据。
- README、BROWSER、ARCHITECTURE 已同步当前状态；`.gitignore` 新增 `.test-artifacts/`，本轮临时文件集中存放。

七类动作映射：MOUSE_MOVE→mouseMoved；MOUSE_CLICK→mousePressed/mouseReleased；MOUSE_DOWN/UP→对应单事件；KEY_DOWN/UP→dispatchKeyEvent（keyDown/rawKeyDown/keyUp）；TEXT_INPUT→insertText，空串成功且无输入命令。完整签名、支持的键名、状态表及示例见 [BROWSER.md](BROWSER.md#bca-013-输入-api)。

## 执行与失败契约

Provider 借用已显式绑定的 Session，一个 Provider 对应一个 Session，执行锁串行化动作；总 timeout 包括排队。每个输入步骤核对 connection/page_id/session_id/generation；换绑后旧操作及其释放不会发送到新目标。正常调用不强制聚焦、不插入 sleep、不重放输入。按钮和修饰键跨动作保持；无匹配 DOWN 的 UP、重复鼠标 DOWN/CLICK 明确拒绝。KEY_DOWN 可 autoRepeat。

坐标直接使用 CSS viewport。每个鼠标 Action 重新读取可见内容范围并拒绝越界；Frame 像素先经 pixel_to_css，输入端不再乘 DPR 或加 scroll。导航保持绑定；Frame 无 generation，调用方负责旧截图、DOM、布局和焦点的新鲜度。测量与实际输入不是原子事务。

参数错误抛 ValidationError；不可用抛 CapabilityUnavailableError；非法 start 抛 LifecycleError；执行中绑定失效抛 TargetLostError。已接受动作的 CDP/几何/超时预期失败返回 FAILED 与 JSON ErrorDetail。取消原样传播，未知编程错误也不吞掉；last_error 保存清理诊断。时间为 UTC-aware，完成时间钳制以防墙上时钟回拨。

失败/取消后，执行锁内最多额外 1 秒 best-effort 释放已记录的普通键、修饰键和鼠标按钮，只允许原身份。等待锁的调用不能释放另一调用的状态。释放可能触发 click/keyup 等副作用，不能视为回滚。显式被 CDP 拒绝的首次 DOWN 不产生多余 UP；响应丢失则保守记录 outcome/input_state_uncertain，即使释放被确认也不自动恢复。状态不确定时停止后续动作，上层恢复已知浏览器状态并重建 Provider；禁止盲目重试。应在导航/解绑/关闭 Session 前结束按住序列并 close Provider。

## 本轮实际质量检查

Windows、Python 3.14.7、websockets 15.0.1、Pillow 12.3.0、**Edge 157.0.4341.60 / CDP 1.3**。本轮没有沿用上次 01.2 的测试结论代替执行。

| 检查 | 实际结果 |
| --- | --- |
| pip install -e ".[dev]" | 成功 |
| Input 模拟测试 | 59 passed / 1.81s |
| 原有 Capture 专项 | 52 passed / 0.93s |
| 全量 pytest -W error，含三个真实入口 | **265 passed / 17.61s，0 skipped** |
| mypy strict | 35 source files，无错误 |
| Ruff check / format --check | 通过，86 files already formatted |
| git diff --check | 通过（Git 的 CRLF 提示不属于空白错误） |
| python -m build | wheel 与 sdist 构建成功 |

模拟测试覆盖七类动作、三按钮和多按钮 mask、键表/组合键/重复按键、Unicode/空文本、非法参数及持有状态、生命周期和 Registry、UTC 回拨、串行/等待取消/锁超时、CDP 拒绝/超时/缺失响应、未知异常、清理超时与 close 取消屏蔽、换绑/重绑/解绑/目标销毁/断线/关闭、click 步骤间失效，以及旧等待者不能释放新绑定的按住状态。

全量运行命令：

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9338"
$env:BCA_INPUT_OUTPUT = "$PWD\input-artifacts"
$env:BCA_CAPTURE_OUTPUT = "$PWD\.test-artifacts\capture-01.3"
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest
```

## 真实浏览器证据

最终报告：[input-report.json](../input-artifacts/input-report.json)。六张截图位于同目录，例如 [DPR 2 全图](../input-artifacts/dpr2-full.png) 与 [DPR 1.5 区域](../input-artifacts/dpr1.5-region.png)。报告保存 ActionResult、DOM 事件、Frame 元数据、误差和完整计时样本。

- 640×480 / DPR 1、720×540 / DPR 1.5、800×600 / DPR 2；每组 scrollX=80、scrollY=120，内容有横纵滚动条。
- 全图和小数区域图共六次从 PNG 找红色像素中心，再经 pixel_to_css 发送 click；DOM target 全为 mark，坐标误差绝对值最大 **0.75 CSS px**。DOM MouseEvent 上报整数 clientX/Y，发送小数保留于报告，未放宽到多个 CSS 像素。
- left/middle/right 的 down、带 buttons 的 move、up 和 click 均经 DOM 记录验证；实际 textarea 验证 a、Shift+B、数字、空格、Ctrl+A 全选、中文/日文/emoji、Enter、Backspace、ArrowLeft/Delete；Alt/Meta 组合、Escape、Tab 事件通过。
- 导航后保持 session/generation 并成功点击；换绑拒绝旧 page_id；每次 resize 检查越界拒绝；close 触发 Shift keyUp 且 Session 仍 ready；目标关闭后拒绝启动输入。
- 全量回归同时重新执行 01.1 连接和 01.2 截图真实测试。输入报告清理指标：pending_count=0、reader_running=false、connected=false。

本次独立浏览器端口为 9338，profile 为 `.test-artifacts/edge-input`，force-device-scale-factor=1.5；无头模式未启用。采用此前在代理环境可运行的 `--no-sandbox --disable-gpu --in-process-gpu`，仅作用于隔离测试实例，未修改系统设置或用户浏览器。脚本仅创建/导航/关闭自建页面；最终通过 Browser.close 关闭本轮实例，并确认进程退出。关闭前枚举只剩启动时的 about:blank，测试页面均已关闭。不操作用户 9222 实例。本轮未删除既有历史目录。

删除本轮 profile 的命令被自动审批拒绝：需要沙箱审批，但当前环境禁止该类审批。因此 profile 保留在已被 Git 忽略的 `.test-artifacts/edge-input`；这不影响测试结果或运行资源关闭。

实测发现中键默认浏览器自动滚屏会消费下一次 mousePressed，因此测试页对中键 mousedown preventDefault，并禁用 contextmenu，以独立检查页面 DOM 输入。Provider 保留网页默认行为；该调整不是在实现中吞事件。真实 DOM/文本结果使用 CDP Input 产生，没有脚本代写 textarea。

## 耗时

下表来源于本轮全量测试保存的最终报告。perf_counter 包围完整 await execute，包含锁等待、鼠标几何测量及 CDP 往返，不含额外 DOM 查询和磁盘写入。不同类别样本构成不同，不作通用性能保证。TEXT_INPUT 的 4 个样本包含 1 个空串空操作。

| 类别 | 样本数 | 中位数 ms |
| --- | ---: | ---: |
| mouse_click | 12 | 3.222 |
| mouse_move | 6 | 11.707 |
| mouse_down | 3 | 2.236 |
| mouse_up | 3 | 2.349 |
| key_down | 19 | 0.853 |
| key_up | 18 | 0.575 |
| text_input | 4 | 1.000 |

## 01.4 / 02 接入提示和边界

1. 上层负责 connect → bind → Provider.start → Registry.register；按序 await 每个 Action，首个 FAILED/异常/取消后停止序列，检查 last_error，不重放输入。
2. 先 Input.close 再 Session.unbind/close；有意长按必须有配对释放。不要在多个 Provider 或其他 CDP 客户端之间共享按键所有权。
3. 页面观察、焦点等待、导航完成和 Frame 新鲜度由上层编排；只匹配 page_id 不能证明旧截图仍有效。
4. 本阶段验证 Windows Edge 的前台受控页面、DPR 与模拟 viewport resize。未专项验证后台输入、OS 全局快捷键、其他键盘布局、IME、WebGL 业务交互、人工 Ctrl+/- 页面缩放及 Python 3.12/3.13 实机矩阵。捏合缩放/非零 visual offset 仍明确拒绝。释放失败竞争主要由模拟端验证。
5. 无需公共协议变更，也没有等待用户决定的实现分支；保守的不确定状态策略、最多额外 1 秒释放预算及 US 逻辑键范围为本阶段记录的工程选择。后续需扩展时在 01.4/02 评审，不在本轮越界开发。
