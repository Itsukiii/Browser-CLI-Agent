# LITE-01 基础控制器集成交接

2026-11-23。状态：**基础桥接已实现并通过本轮 native/Edge 验证，提交架构审查；不代表完整阶段正式 Accepted**。桌面浏览器菜单缩放与更完整故障矩阵仍有缺口，见末节。未进入 LITE-02～06。

## 基线与提交

- 开始：`lite@72d8709`（LITE-00 审计）；原实验基线 `88ba80e`。实现及测试证据提交：`22b4c71`（feat(lite): harden Maa CDP lifecycle and verify native Edge bridge）。本交接文档独立归档，可用 `git log --oneline -- docs/lite/LITE-01_HANDOFF.md` 定位文档提交。
- Windows 11 build 26200、Python 3.14.7 x64、Edge 158.0.4370.33/CDP 1.3；MaaFW Python/native 均 v5.16.1；NumPy 2.5.5，Pillow 12.3.0，OpenCV headless 4.14.0.94（只为历史回归安装）。
- Maa 锁为 `==5.16.1`。上游无公开 native close，因此本阶段固定版本显式调用 Destroy，升级必须重新核对 binding。
- 用户启动隔离 Edge，端点 `http://127.0.0.1:9341`；只创建、操作和关闭测试 Target，保留所有既有 Target。没有自动关闭用户浏览器。
- 用户未跟踪主交接书保留原样，不纳入实现提交。旧 Core/Runtime/Plugin/Vision 源码均未修改。

## 源码与接口

| 文件/API | 实际行为 |
| --- | --- |
| `src/bca/lite/bridge.py` / CDPBridge | 在 owner loop 构造并固定 connection/page/session/generation；一个实例不能跟随 rebind，重绑后须重新建桥 |
| `screencap()->NDArray[uint8]` | worker 同步入口；owner loop 串行采集，BGR 连续数组；在 capture 前后/解码后复核，时间预算包括 capture 耗时 |
| `click(x:int,y:int)->bool` | callback 坐标为原始 Frame 像素；只调用 Frame.pixel_to_css 一次；消费一次观察，不重试 |
| `observation->ObservationRef\|None` | owner-loop 读取；冻结且按对象身份比较，包含 Frame、geometry、monotonic observed_at。不是业务回合签名 |
| `require_authorization=True` + `await authorize(ref)` | 应用命令模式：只接受本桥当前同一个 ref；复制/旧 ref 拒绝；新截图、点击尝试和停止使授权失效 |
| `invalidate()` | 任意线程可用的非阻塞停止信号；停止新入口，不承诺在途动作已撤销 |
| `await aclose()` | owner-loop 等待真实 coroutine finally，包括 timeout 后的取消清理；调用方仍须等 native worker |
| `run_native(bridge, callable)` | 创建并持有 worker Task；调用者重复取消时撤销 bridge 入口、等待 worker 后再传播 CancelledError；不强杀 native |
| `last_error` / `input_outcome` | 安全类别/桥接消息；结果为 not_attempted/rejected/confirmed/unknown。unknown 后阻塞实例，confirmed 仅表示输入确认 |
| `maa_controller.py` / MaaCDPController | worker 构造，`raw_size=True` 默认；features=0 直接 Click；不支持的输入返回 False |
| `MaaCDPController.close()` | worker 中在 jobs 结束后幂等 Destroy，再清空 handle 防止析构双释放；不得继续使用已关闭对象 |
| `examples/lite_maa_cdp_smoke.py` | 指定 Target 的原生截图/可选点击，使用 run_native 和显式清理；Pillow 12 无废弃 mode 参数 |
| `tests/lite/test_cdp_bridge.py` | 模拟时序/身份/授权/失败回归 |
| `tests/lite/test_maa_native.py` | 实际 DLL callbacks、缩放/BGR、Resource/Tasker、取消和生产 InputProvider 的模拟 CDP 丢响应 |
| `tests/lite/test_real_bridge.py` | 实际 Edge 坐标矩阵与失效场景，独立 DOM oracle |

Maa 的 untyped 边界用局部 `type: ignore[import-untyped]` 和继承处 `ignore[misc]` 标明，不全局关闭 mypy，不将 Any 伪装成已验证上游类型。

### 坐标与范围

调用 `Controller.post_click(x,y)` 必须使用该 Controller **返回截图**的像素；Maa 以 raw/target 两轴比例 round 成原图整数，再调用 bridge；bridge 通过 Frame 的 capture 范围和偏移换算 CSS。DPR/scroll 不额外应用。截图区域由借用的 CaptureProvider 决定，真实测试用 BrowserCaptureProvider 子类委托 capture_region，未增加另一套区域变换。

默认 raw 使 smoke 坐标清晰；non-raw 在 native/Edge 中实测。截图 resize 参数只在任务启动前设置，不能在截图与对应动作之间变更。生产调用方必须独占同一 Session/Provider 和 controller job 序列；直接绕过桥接派发输入不在契约内。

### 有限多动作协议（给 LITE-02/04）

本阶段提供精确单步观察授权，**没有放开同帧第二次点击**。Quiz 命令应在应用层保存 `(command_id, semantic_revision, ordered_steps=[select,confirm], deadline)`，最多两步，逐条执行：

1. 以 `require_authorization=True` 建桥；停止其他观察/命令交错，获得 Maa 截图及对应 `bridge.observation`。
2. 视觉层确认原命令的业务回合签名和当前按钮，`await bridge.authorize(ref)`，仅提交该步对应的 native Click。
3. 首步成功后重新截图/识别，核验仍为同一回合且选择状态正确；以**新 ref**授权确认。不把新回合引用套给原命令。
4. 任一步 stale、unknown、取消、超时就终止剩余步骤；提交后再观察分数/回合确认业务结果。

ref 只证明采集来源/几何/时间，不能证明 DOM 在最后一次检查后未变。语义签名、命令队列、两步流程执行器和结算属于后续阶段；未作为本次已经完成的 Quiz 行为。

## 原生 API 核验

除 LITE-00 的安装源码审计，本轮真实执行了 `Resource.post_bundle` 加载最小 DirectHit/DoNothing pipeline；`Tasker.bind`、`inited`、`post_task`、`post_recognition("DirectHit",JDirectHit(),image)`、`post_action("DoNothing",JDoNothing())` 和 `post_stop`。传 dict 给直接 recognition 参数确实触发 TypeError。此测试不涉及模板/OCR，不冒充 LITE-02 视觉验收。

## 测试与复现

环境安装使用 `.[lite,dev,vision]`。在根目录执行：

```powershell
.venv/Scripts/python.exe -m pytest -q -W error --basetemp=.test-artifacts/lite-01-final
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m build

$env:BCA_CDP_ENDPOINT = 'http://127.0.0.1:9341'
$env:BCA_LITE_OUTPUT = '.test-artifacts/lite-real'
.venv/Scripts/python.exe -m pytest tests/lite -q -W error --basetemp=.test-artifacts/lite-01-live-final
Remove-Item Env:BCA_CDP_ENDPOINT
```

| 本轮执行 | 结果/证据（`docs/evidence/LITE-01/`） |
| --- | --- |
| 全量离线 | **784 passed、46 skipped，35.02s**；offline.txt。45 个旧浏览器用例及1个新 Edge 用例未在此命令启用 |
| lite 离线 | **24 passed、1 skipped，1.57s**；lite-offline.txt；包含真实 DLL + 模拟后端 |
| lite 含真实 Edge | **25 passed、0 skipped，6.46s**；lite-live.txt |
| mypy | 92 个源码文件通过，mypy.txt |
| Ruff/format | 完整仓库通过，223 文件格式一致 |
| wheel/sdist | 构建成功，build.txt |
| 独立 wheel 基础安装 | Browser 导入成功；无 Maa/NumPy，install-wheel-base.txt |
| 独立 wheel + lite | 导入 bca.lite/controller 成功，native v5.16.1；install-wheel-lite.txt |

真实矩阵：DPR 1/1.5/2、surface 960×540/720×540/800×600、scroll (80,120)、全图/区域、raw/non-raw，共12组，每组3次，**36次新点击**。每组保存一张受控 fixture PNG；report.json 记录 Frame 元数据、返回图像尺寸、native callback 原始坐标/线程、CSS 预期和 DOM 目标/坐标。原生回调线程均与 asyncio owner 不同；每组额外重复点击被拒绝。最终 DOM 与预期 CSS 最大误差 **0.667 CSS px**，小于1像素。此处仅提交自建测试页截图作为可复核证据，用户页面/profile/模型仍不入库；这是对 LITE-00 排除截图规则的受控 fixture 例外。PowerShell 初始 UTF-16 日志统一转成 UTF-8/LF，保留原失败内容。

真实故障：Resize、pinch scale=2（明确拒绝不支持的几何）、导航、unbind/rebind、Target 销毁后 native click 失败。结束 pending=0、reader=false、connected=false，自建目标残留=[]、原有目标保留=true。

模拟/原生故障：同 loop 在回调在途时立即拒绝；invalidate 不等同步锁；geometry await 期间 generation/stop/age 变化；超时后真实 finally 仍在清理时 aclose 等待；未确认输入永久阻塞；重复取消等待 worker；native 截图在途取消无后续输入；真实 BrowserInputProvider 连接模拟 CDP 时丢 mousePressed ack，输入不确定且仅一次 mousePressed，没有重发。确认失败也保守标记 unknown，暂不提供较细“已确认未执行”的恢复许可。

首轮 Edge 用例的中心断言失败已保留 browser-first.txt：测试用向下取整选缩放图中心，偏差恰好2 CSS px。改用最近整数中心并按一个返回图像像素的量化界限检查；native比例换算和 DOM误差≤1的断言保持。故障注入开发时曾忘记清空默认 set 的输入 gate，导致并未丢响应；修正注入后才计为通过。

旧回归数量只是兼容性证据，不是新桥接功能验收。没有复用旧报告的360次点击。

## 性能与清理边界

36样本混合矩阵（非基准比较）：native post_screencap→wait/get（包含 CDP测量/截图/解码/Maa resize）median **93.16ms**、p95 **143.00ms**；post_click→wait（包含来源校验和 CDP输入）median **3.59ms**、p95 **6.27ms**。p95 使用排序 ceil(n×.95)-1；原始数组 report.json，汇总 summary.json。不含视觉推理、CLI、业务结算和 PNG 保存；不能推导完整产品1Hz或长期性能。

硬件型号读取被系统权限拒绝，未为该非阻塞信息扩大权限；这些时延只描述本机本轮，不用于跨机器性能承诺。未测 CPU/RSS/长时间泄漏。解码线程取消后有界 CPU工作可自行结束，不继续 CDP/输入。

关闭顺序：停止入口 → 取消时 invalidate → 等待 native worker（其中 finally Destroy controller）→ await bridge.aclose → Input.close → Capture.close → 关闭自建 Target → Session.close。普通完成也显式 close/aclose；不依赖 gc。原生 Job.wait 没有超时参数，若 native 本身永久卡死无法强杀线程；本次受控测试没有出现该问题，未声称进程级隔离。

## 仍待审查与未覆盖

- Edge 菜单/Ctrl+± 的真实桌面 zoom 尚未验证；DPR emulation、CSS图像缩放和 pinch 拒绝不能替代该证据。暂不宣称桌面 zoom 全矩阵已通过。
- 实际 Edge 传输层 ack 丢失、socket断连与正常关闭竞争尚未做故障代理注入；目前 ack 丢失为新 native DLL + 模拟 CDP + 生产 Provider 测试，目标销毁/换绑是真实 Edge。
- 同页 DOM/Canvas 更新不会改变几何指纹；语义修订和最终结算必须由 LITE-02/04 完成，不允许据本桥宣称旧题点击绝不发生。
- 显式授权只限定观察，不限定按钮坐标/业务步骤；可信应用层应把有限步骤和视觉结果绑定，不能让任意调用者重授权旧业务意图。
- Python 3.12/3.13、其他系统、真实 WebGL、长期运行未测；尚无正式 CLI。
- 建议架构主会话先审核公共观察授权及固定版本 Destroy 边界，再决定上述补测要求及 LITE-02 的启动。保留现有 README/PROJECT_CONTEXT 的正式验收状态，本轮未自行标 Accepted。
