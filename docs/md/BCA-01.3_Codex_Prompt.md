# BCA-01.3 / Input & Actions — Codex 开发任务

> 项目：Browser CLI Agent (BCA)  
> 阶段：BCA-01.3 / Browser Input & Actions  
> 工作目录：当前 BCA 仓库根目录（用户环境为 `D:\Project\BCA`）  
> 基线：`browser-cli-agent 0.2.0`、`PROTOCOL_VERSION=2`  
> 前置成果：BCA-01.1（Connection/Target/Session）、BCA-01.2（Capture & Coordinates）均已验收  
> 日期：2026-11-13

## 1. 工作方式与权威资料

在修改代码之前，先读取并核对以下本地仓库资料：

1. `BCA_PROJECT_CONTEXT.md`、`BCA-01_Browser.md`（如存在于项目共享资料）；
2. `docs/INTERFACES.md`、`docs/BROWSER.md`、`docs/ARCHITECTURE.md`；
3. `docs/BCA-01.2_DELIVERY.md`、`docs/BCA-01.2_HANDOFF.md`、BCA-01.1 相关交接；
4. `src/bca/core/protocol/models.py`、`src/bca/core/providers/base.py`、`src/bca/core/providers/registry.py`；
5. `src/bca/core/browser/session.py`、`capture.py`、`connection.py`、`errors.py`、`__init__.py` 及现有测试。

**以实际工作区最新源码为最终依据。** 已知 GitHub 远端可能滞后于本地 01.2 交付；保留本地已验收的修复。先确认 API/目录，再编码。遇到局部实现选择时自行作出简洁可靠的工程决策并在交接中记录；涉及公共 Protocol 2 变更时，先提出兼容性方案而不是直接修改共享契约。

## 2. 本阶段目标

实现可供 BCA Runtime/Plugin 调用的浏览器输入适配器：以**已显式绑定的 BrowserSession** 为唯一目标，将 Protocol 2 `Action` 映射为 CDP 输入命令，返回合法 `ActionResult`。支持鼠标移动、点击、按下/释放、键盘按下/释放和文本输入，并保证坐标、顺序、生命周期、失败语义可预测。

本阶段须完成可运行代码、单元/模拟测试、隔离的真实 Edge 集成验证、文档及最终交接。尊重用户此前授权的 Codex 独立真实浏览器测试方式：优先自建隔离 Edge/CDP 实例和专属 profile/端口；完整清理自己创建的页面与浏览器实例，不干扰用户的 9222 实例。测试不能运行时准确报告待验证项。

## 3. 固定公共接口

遵循已有 `InputProvider` 抽象：

```python
class InputProvider(Provider):
    capability = "input"

    async def execute(self, action: Action) -> ActionResult: ...
```

`Provider` 的 `available`、`start()`、`close()` 生命周期与已交付 `BrowserCaptureProvider` 的所有权模式保持一致：Session 由上层管理；Input Provider 只借用 Session，不擅自连接、选择目标或关闭 Session。ProviderRegistry 注册行为保持不变。

Protocol 2 动作模型：

| ActionType | 必填字段 | 行为 |
| --- | --- | --- |
| `MOUSE_MOVE` | `page_id, x, y` | 移动指针至 CSS viewport 坐标 |
| `MOUSE_CLICK` | `page_id, x, y, button` | 一次按下并释放 |
| `MOUSE_DOWN` | `page_id, x, y, button` | 显式按下 |
| `MOUSE_UP` | `page_id, x, y, button` | 显式释放 |
| `KEY_DOWN` | `page_id, key` | 逻辑按键按下 |
| `KEY_UP` | `page_id, key` | 逻辑按键释放 |
| `TEXT_INPUT` | `page_id, text` | 插入文本，空串成功且无浏览器输入 |

枚举 `CoordinateSpace.VIEWPORT_CSS`；鼠标按键 `MouseButton.LEFT/MIDDLE/RIGHT`；结果 `ActionResult(action_id, status, started_at, finished_at, error)`，状态 `SUCCEEDED/FAILED/CANCELLED`。模型 `frozen=True, kw_only=True`。`action_id` 必须原样回填；使用 UTC-aware `datetime`，完成时间不得早于开始时间；单调时钟计量超时/延迟。`ErrorDetail` 中记录稳定 code、可读 message、适当 retryable/details（JSON 类型）；不得塞入异常对象。

## 4. 实现要求

### 4.1 适配器与生命周期

- 在 `src/bca/core/browser/` 实现 `BrowserInputProvider(session: BrowserSession, *, timeout: float = ...)`，符合 `InputProvider` ABC；导出公共入口，保持命名与已交付 Capture Provider 一致。
- `available` 反映 Provider 已 start 且当前 BrowserSession 已绑定有效页面的本地快照；`start()` 幂等；`close()` 幂等、完成必要输入清理且后续不可再次启动；关闭 Provider 不影响借用的 BrowserSession。
- 使用独立的异步执行锁串行化同一 Provider 的 `execute()`；锁等待时间纳入单次调用的总超时预算。采用一个 Provider 对应一个 Session 的典型模型。
- 捕获一次动作的 connection 对象、`page_id`、`session_id`、`generation`；开始、获得执行锁后、每个 CDP 输入步骤之前和必要时之后验证身份。旧绑定的输入不得发往新绑定。注意检查 `session.send()` 内置 generation guard，但多步骤动作仍需在步骤之间再次检查。

### 4.2 鼠标坐标、视口及按钮状态

- Action 的 `x/y` 直接表示**当前可见内容视口左上角为原点的 CSS 像素**，不是截图像素、文档绝对坐标或设备像素。
- CDP `Input.dispatchMouseEvent` 使用相同 CSS viewport 空间。输入前获取并验证当前页面的可用内容尺寸；`0 <= x < width`、`0 <= y < height`。采用与 BCA-01.2 最终交付一致的视口边界约定（例如滚动条、visual/layout 尺寸差异及桌面缩放），确保对 `Frame.pixel_to_css()` 输出的点可正确落位。必要时提取**小范围共享的只读几何测量辅助函数**，避免 Capture/Input 两套规则漂移；保留 01.2 行为和全部测试。
- 鼠标事件采用 `mouseMoved`、`mousePressed`、`mouseReleased`；按钮映射 left/middle/right，clickCount 与按钮按下状态规范设置；支持双轴小数坐标。将按钮状态维护在 Provider 内，支持按下后移动、再释放的连续动作；调用 CDP 时传递符合实际当前状态的 `buttons` 位掩码。普通 click 由 down/up 组成。
- 输入动作之间不得人为添加影响延迟的固定 sleep。对于 `MOUSE_CLICK` 多步骤，确保先发送按下、再发送释放；中间错误/取消、Session 失效时不要把遗留按键悄悄施加于新 Target。设计有界的 best-effort 释放策略，限定原 connection/session/generation；无法安全释放时显式记录输入状态不确定性。对单独 `MOUSE_DOWN` 的保持状态与 `MOUSE_UP` 的验证形成一致的契约。

### 4.3 键盘和文本

- `Input.dispatchKeyEvent` 实现 `KEY_DOWN` / `KEY_UP`；覆盖常见可控逻辑键：普通英文字母、数字、空格、Enter、Tab、Escape、Backspace、Delete、箭头、Shift/Ctrl/Alt/Meta 等常用按键。为 `key`、`code`、`windowsVirtualKeyCode`、`text`/修饰键位等建立可测试的映射；采用明确、可维护的键位表/转换规则。对无法可靠映射的名称作清晰参数错误处理。
- 保持修饰键按下/释放状态；跨动作串行的 `Shift` + 字母、`Ctrl` + 键等组合应按 CDP 预期生效。按键事件应足以驱动测试页面真实 DOM 键盘监听器及普通输入框行为。必须明确且测试有副作用的按键释放与取消语义。
- `TEXT_INPUT` 使用适合 Unicode/中文/日文字符的 CDP 输入方式（如 `Input.insertText`）；尊重页面焦点；空字符串按协议作为成功空操作。避免将多字节文本逐字符错误映射成物理键事件。

### 4.4 结果与错误语义

- 对有效且已接收的 Action，在 CDP 执行成功时返回 `ActionStatus.SUCCEEDED`；可预期 CDP 命令执行失败时返回 `ActionStatus.FAILED` 和 `ErrorDetail`，保留失败阶段/已完成步骤/可能遗留输入状态信息。
- 参数校验错误使用 `ValidationError`；Provider 不可用使用 `CapabilityUnavailableError`；非法生命周期使用 `LifecycleError`；Session/Target 变化使用现有 `TargetLostError` 或等价项目既有异常。遵守 `docs/INTERFACES.md` 的边界约定，明确哪些场景返回 FAILED、哪些抛异常。
- 超时要覆盖锁等待与复合动作各阶段；使用项目既有 CDP timeout/error 分类与调用约定。超时后不重放输入；对已经生效但响应丢失的动作明确“结果不确定”语义。
- `asyncio.CancelledError` 按 Protocol 2 原样传播，不能吞掉或伪造 SUCCEEDED；必要的 best-effort 清理要有界且不能在取消后向其他 Target 发送输入。
- 避免日志输出用户输入的原始 `text`、敏感按键序列及网页内容；日志可包含 action_id、动作类型、目标 ID、耗时、结果和错误分类。

### 4.5 与 Capture 的坐标闭环

- 明确调用路径：`Frame` 截图像素 `(px,py)` → `frame.pixel_to_css(px,py)` → `Action(x=css_x,y=css_y,page_id=frame.page_id, ...)` → CDP `Input.dispatchMouseEvent`。
- 用真实受控测试页面核对至少完整截图、局部裁剪截图、DPR 1/1.5/2、有滚动条和非零滚动位置下的实际点击落点。浏览器 resize/Target 切换后重新验证实时视口，拒绝越界输入。`Frame` 本身不携带 generation；当输入来源依赖某张旧截图时，由调用方或有明确上下文的封装负责新鲜度检查，不通过猜测旧 frame_id 推断；本阶段至少确保 Provider 单动作的身份和当前几何有效性。

## 5. 代码与测试交付

建议主要落位（可按实际仓库适当调整）：

- `src/bca/core/browser/input.py`：Provider、状态管理、CDP 输入映射和错误处理。
- `src/bca/core/browser/__init__.py`：导出 BrowserInputProvider 及必要异常。
- `tests/core/browser/test_input.py`：独立模拟端的行为/竞态/失败测试。
- `tests/core/browser/test_real_input.py`：可选择执行的真实浏览器验收入口。
- `examples/input_browser.py`：建立受控测试页面、按动作序列运行并记录输入事件、落点与耗时。
- `docs/BROWSER.md`、必要的 README：公开 API、生命周期与验证方法。
- `docs/BCA-01.3_HANDOFF.md`：最终阶段交接。

模拟测试至少覆盖：七种 ActionType、三种鼠标按钮、move/down/up/click 有序事件、按钮状态、键盘与组合键、Unicode 文本与空文本、无效坐标/键名/目标、Provider 生命周期、请求超时/异常、锁内串行、并发等待取消、会话换代/解绑/关闭/目标销毁/断连、部分发送/超时后释放策略、ActionResult 与 ErrorDetail 合法性、Registry 类型化获取。

真实 Edge 集成测试使用**仅为测试创建的页面**，页面内事件监听器或简单 DOM 控件记录实际接收的坐标、按钮、键盘序列、输入框值。验证至少：

1. 鼠标点击、移动、按下/释放与 DOM 实际事件对应；
2. 左/中/右键，按键和组合键，Unicode 文本进入已聚焦输入框；
3. 完整与区域截图坐标闭环，多 DPR、滚动和浏览器尺寸切换；
4. 导航与关闭后目标身份保护；Provider/Session 资源清理，`pending_count=0`、reader 已停止；
5. 记录每类输入的实际执行耗时，提供样本数和中位数，标注测量边界。

使用 `BCA_CDP_ENDPOINT` 环境变量的 opt-in 集成测试模式；可由 Codex 自行创建独立的真实 Edge 测试实例，使用隔离端口和 profile，测试后清理。产出 `input-artifacts/input-report.json` 等机器可读数据，记录浏览器版本、动作结果、实际 DOM 观测、坐标误差、耗时和清理状态。报告中区分模拟与真实验证、通过与未测事项。

质量门槛：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -W error
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

注意：BCA-01.2 最终交接基线为 **205 passed / 0 skipped**（在配置了真实 Edge 的代理环境中）；本轮具体测试数量会变化，以真实日志为准。不要直接声称继承了上次的实测结果。

## 6. 完成标准与交接

完成后 `docs/BCA-01.3_HANDOFF.md` 需包含：

- 实现文件、导出 API、七种 Action 的 CDP 命令映射与坐标/键盘状态语义；
- Provider 所有权、执行顺序、失败/取消/超时/部分输入和 Target 换代的处理；
- 实际运行的单测、真实浏览器、mypy/Ruff/build 结果；
- `input-report.json` 路径、主要 DOM 事件/坐标验证及耗时中位数；
- 对 BCA-01.4 集成和 BCA-02 Runtime 的调用提示；
- 遇到的具体兼容性问题、处理方式及尚待用户确认的工程决定。

本轮结束停在 **BCA-01.3 交付与审查**，等待本子会话验收，再进入 BCA-01.4。
