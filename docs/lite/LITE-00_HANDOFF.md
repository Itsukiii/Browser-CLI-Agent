# LITE-00 基线审计（2026-11-23）

状态：审计交付；正式 Accepted 由架构主会话决定。起点为 `lite@88ba80e68897ef8e40834d03696cb26d7a5d8504`，origin 指向 Itsukiii/Browser-CLI-Agent。起始工作树仅有用户提供的未跟踪 `docs/md/BCA-LITE_MASTER_HANDOFF.md`。未修改 main，也未拉取/声称远端当前 HEAD 已刷新。阶段提交可用 `git log --oneline -- docs/lite/LITE-00_HANDOFF.md` 定位。

## 阅读与复用决策

完整阅读主交接书；核对 BCA-00_HANDOFF、BCA-01～04_MAIN_SYNC、BROWSER、RUNTIME、PLUGIN_SPEC、ASSETS、VISION、实验 BCA-LITE-01 和历史 PROJECT_CONTEXT。追踪 Browser session/capture/input/geometry、Protocol Frame、Runtime browser_freshness、Plugin host/manager、Vision matching/decode，以及 lite bridge/controller、smoke 和测试。旧 PROJECT_CONTEXT 仍停在 BCA-03，README 主体包含旧 CLI 路线；以主交接书的 lite 路线为准，正式验收时再同步首页。

| 源码 | 决策 |
| --- | --- |
| core/browser、Frame.pixel_to_css | 直接复用；Session/Provider 在同一 owner loop，显式目标、身份和输入不确定性保留 |
| core/runtime/browser_freshness、action_pipeline | 借鉴来源、串行化、取消等待；不将旧调度器接到 Maa 上 |
| core/plugins/host、manager | 借鉴拥有权和停止入口；lite 不承诺旧 Plugin API 兼容 |
| plugin_sdk/assets、vision | 保留历史回归；lite 识别交给 Maa，RMSE 分数和阈值不可迁移 |
| src/bca/lite | 实验实现，需要 LITE-01 修正；此前五个 fake 测试不是 native/Edge 验收 |

## 环境与复现

Windows 11 build 26200，CPython 3.14.7 x64；系统 python 为不可用 Store alias，实际解释器为 `C:/Users/wutong/AppData/Local/Python/pythoncore-3.14-64/python.exe`。本项目独立 `.venv`，不借用 ../BCA 的环境。Maa Python/native 都为 v5.16.1；NumPy 2.5.5、Pillow 12.3.0、OpenCV headless 4.14.0.94；Edge 实装及端点都为 158.0.4370.33/CDP 1.3。所有 wheel 安装成功，`pip check` 无冲突。

```powershell
& 'C:/Users/wutong/AppData/Local/Python/pythoncore-3.14-64/python.exe' -m venv .venv
.venv/Scripts/python.exe -m pip install -e '.[lite,dev,vision]'
.venv/Scripts/python.exe -m pytest -q -W error --basetemp=.test-artifacts/lite-00-baseline
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```

仅 `[lite,dev]` 可以导入 maa、bca.lite、MaaCDPController，但全量旧 Vision 测试有 8 个 cv2 收集错误；全量回归要加 `[vision]`，不将其强加给 lite 运行依赖。首次默认 pytest 临时目录被沙箱拒绝，日志保留，改用项目内 basetemp 并授权重跑。曾误将 PowerShell 未展开的 `test*` 传给 pytest，未执行测试，不计验证。初始 mypy 补齐 cv2 后仍有 Maa 缺少 py.typed 的两个错误；Ruff 初始 7 个问题，3 文件格式不符。原始输出位于 `docs/evidence/LITE-00/`；后续修正结果属于 LITE-01，不覆盖初始失败。

有效离线基线：**765 passed、45 skipped，36.24s**，见 `baseline.txt`。其中 lite 原有 5 个 fake 测试通过；45 个浏览器测试没有通过环境变量启用。此结果是本次重跑，但仍只证明旧组件回归和实验 fake 测试，不是新 native/Edge 验收。

依赖改动：将 maafw 范围锁为 `==5.16.1`，避免生命周期私有绑定兼容层在补丁升级后未经验证。新增模型/缓存忽略目录；既有 `.venv/`、`.edge-capture*/`、`.test-artifacts/`、`.env` 已覆盖开发资源。截图、模型和 profile 不提交。

## 已核实 API（安装源码优先）

对照 `.venv/Lib/site-packages/maa/{controller,resource,tasker,job,buffer}.py` 与 [v5.16.1 Python binding](https://github.com/MaaXYZ/MaaFramework/tree/v5.16.1/source/binding/Python/maa)、[ControllerAgent.cpp](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/source/MaaFramework/Controller/ControllerAgent.cpp)、[MaaDef.h](https://github.com/MaaXYZ/MaaFramework/blob/v5.16.1/include/MaaFramework/MaaDef.h)。下载参考副本在忽略目录 `.test-artifacts/upstream/`。

- `CustomController` 构造注册 C callbacks；`connected()` 为方法，覆盖父类 property 是上游有意设计。没有 ABCMeta，不能通过 `__abstractmethods__` 取验收证据（首次探针对此抛 AttributeError，后已纠正）。
- `get_features=0` 走直接 click；非零 UseMouseDownAndUpInsteadOfClick 才合成 touch。`preproc_touch_point` 以 raw/target 两轴比例并 round 转回原像素。
- `set_screenshot_use_raw_size(bool)` 可明确 raw 策略；`post_screencap().wait().get()` 返回 Maa 输出图像。BGR uint8 连续数组由 ImageBuffer 交给 native。
- 截图 C 边界捕获 Exception 并返回 False；Click C 边界直接 `int(self.click(...))`，不能让异常逃逸。
- Controller/Resource/Tasker 无公开 close，只有 `__del__` 调用 Destroy。LITE-01 需隔离一个固定版本、幂等显式释放层，保持 Python callbacks 存活直到 native destroy 完成。
- `Resource.post_bundle(path)->Job`；注册 custom recognition/action 有 Python holder。`Tasker.bind(resource,controller)->bool` 保留两者强引用；`post_task(entry,pipeline_override)` 接字典。
- `Tasker.post_recognition(reco_type,reco_param,image)` 与 `post_action(action_type,action_param,box,reco_detail)` 内部调用 dataclasses.asdict：参数必须是 pipeline dataclass，不能猜成任意 dict。
- `Job.wait()` 同步阻塞且无 timeout 参数；Tasker 有 post_stop，Controller 没有独立 post_stop。停止/销毁不得阻塞 CDP loop。
- [上游 #1271](https://github.com/MaaXYZ/MaaFramework/issues/1271) 本次读取仍 Open，PI Custom 支持不能作为可用前提。

## 风险排序与 LITE-01 修复方案

| 优先级 | 证据与影响 | 修复/验证 |
| --- | --- | --- |
| P0 | 同步锁覆盖 future.result；invalidate 与同 loop 回调先取锁，可能卡住 owner loop | owner loop 串行状态，停止标志不等待锁，竞争/取消回归 |
| P0 | 点击 await geometry 后未复查 identity/age；Bridge 没固定创建时绑定，重新截图可跟随外部 rebind | 固定 binding；输入前后复核身份与有效期 |
| P0 | future.cancel 不代表 coroutine finally 完成；to_thread 外部取消不终止 native 工作 | 跟踪 owner tasks，aclose 排空；shield worker 并等待；销毁最后发生 |
| P1 | 默认缩放与 smoke 的 raw 文案不符 | 默认显式 raw；原生 raw/non-raw 与 DPR/区域/滚动矩阵 |
| P1 | last_error 只有异常类；未知输入依靠 Provider available 间接阻塞 | 暴露拒绝/确认/未知结果，保守阻塞且不重试 |
| P1 | 最新截图自动替换来源，单帧授权无法安全表达 Quiz 两步 | 设计精确观察引用；每步重新观察/业务回合确认，不放开第二次旧帧点击 |
| P1 | href/timeOrigin/geometry 不检测局部 DOM 或 Canvas 回合变化 | 明确非事务边界；留给 LITE-02/04 语义签名和提交后验证 |

## 最小接口与拥有权

LITE-01 保留 CDPBridge.screencap/click、MaaCDPController；新增停止入口与 async 排空接口，原生等待放在单独工作线程。不增加通用 Runtime/插件 DSL。

| owner | 持有资源 | 清理顺序 |
| --- | --- | --- |
| Application | 入口、native worker、Tasker（将来） | 停止新任务；取消时先撤销桥接授权；等待 native worker/stop |
| Native worker | Controller callbacks/native handle | 工作结束后显式 destroy，不能在 owner loop 等待 |
| CDPBridge | 借用 Session/Providers、在途 owner tasks | invalidate 为停止信号；aclose 等待 coroutine finally |
| Application | Input、Capture、Session | bridge/native 已排空后 Input.close → Capture.close → Session.close |
| Application（测试） | 自建 Target | 只关闭自建 Target，不关闭用户 Edge |

LITE-00 无性能主张：未测 native 推理/业务吞吐/长期内存，median/p95 不适用。LITE-01 真机脚本将单独记录样本和线程/坐标，不借用旧 805 tests/360 clicks。
