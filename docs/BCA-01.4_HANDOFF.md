# BCA-01.4 集成验收与交接

2026-11-16 完成开发与本轮测试，停在 **01.4 交付与审查**。请将 [BCA-01_MAIN_SYNC.md](BCA-01_MAIN_SYNC.md) 交架构主会话归档；BCA-01 是否正式验收由本子会话确认。本轮未进入 BCA-02。

## 变更范围

- `examples/browser_end_to_end.py`：现有 Session/Capture/Input/Registry 的薄组合；枚举既有页面 ID、显式绑定自建 Target；截图字节找红色像素，经 pixel_to_css 点击，以 DOM 命中和计数独立核验；异常和重复取消也等待按顺序清理，保存机器可读报告。
- `tests/core/browser/test_end_to_end.py`：19 项跨模块测试；`test_real_end_to_end.py`：1 个 opt-in 入口，直接调用同一完整流程。
- 正式跨模块交接 MAIN_SYNC、本报告、README、BROWSER、ARCHITECTURE、DEVELOPMENT_PLAN；修正文档历史未验收状态和开发计划乱码。
- `bca_input_playground.py`：仅六处长行的等价换行，消除本轮仓库级 Ruff 门槛阻塞；未运行该脚本、未修改其行为、未访问其 9222。

未新增 src 下的组合门面、状态机或全局锁；集成测试未揭示需要改动核心实现的缺口。既有 Protocol 2、Provider ABC、注册行为、Capture/Input 的独立锁及失败语义保持。新增 Observation 只属于示例上下文，不是 Frame 协议扩展。

## 验收覆盖

模拟/局部集成检查：同 Session 的 Registry 类型查询、幂等生命周期、截图→Action 参数闭环、Provider 关闭后借用 Session 仍可用；导航/scroll/resize/换绑及同 targetId 新 generation 拒绝旧观察；capture/input 同时在途及两个排队请求遇到 switch/rebind/unbind/destroy/disconnect/close；独立锁允许输入在截图等待时完成；采集失败不使输入失效、输入拒绝不使截图失效；点击取消后释放；HTTP 发现失败、页面启动失败、Capture 已启动而 Input 启动失败、重复取消期间的有序清理及仅关闭自建目标。其余底层错误路径复用既有 01.1～01.3 回归，没有重复扩张单元测试。

真实流程为 **DPR 1/1.5/2 × 完整/区域 × 3 样本 = 18 次**。目标像素直接从 PNG 解码结果确定，不查询 DOM 位置。每次核验实际图片尺寸与 CSS 覆盖比例、DPR 浮点误差、滚动条、scroll=(80,120)、DOM target=mark、计数增长及坐标误差；最大误差 0.75 CSS px，区分发送小数与 DOM MouseEvent 的整数取整。

观察时记录 connection/page/session/generation 和几何/文档上下文，输入前重新比较。可检测已发生的变化，不保证检查和输入之间 DOM 不变。动作首个失败即退出，不重放；清理释放可能触发新 DOM 事件，不声称业务回滚。

## 本轮实际质量结果

| 项目 | 本轮结果 |
| --- | --- |
| pip install -e ".[dev]" | 成功；日志 .test-artifacts/install-01.4.log |
| pytest -W error 全量 | **285 passed / 20.19s / 0 skipped** |
| 真实入口 | 01.1、01.2、01.3、01.4 四项全部执行 |
| mypy strict | 36 source files，无错误 |
| Ruff lint / format | 通过，93 files already formatted |
| python -m build | wheel/sdist 成功，日志 .test-artifacts/build-01.4.log |
| Protocol/版本 | 保持 browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2 |

全量命令：

```powershell
$env:BCA_CDP_ENDPOINT = "http://127.0.0.1:9339"
$env:BCA_BROWSER_OUTPUT = "$PWD\browser-artifacts"
$env:BCA_CAPTURE_OUTPUT = "$PWD\.test-artifacts\capture-01.4"
$env:BCA_INPUT_OUTPUT = "$PWD\.test-artifacts\input-01.4"
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest-01.4
```

Windows、Python 3.14.7、Edge 157.0.4341.60、CDP 1.3、websockets 15.0.1、Pillow 12.3.0。测试使用自建有窗口 Edge，独立端口 9339、profile `.test-artifacts/edge-integration`、force-device-scale-factor=1.5。代理环境沿用 --no-sandbox --disable-gpu --in-process-gpu，仅对本隔离实例生效；无系统改动，不接触用户 9222 或其页面。

## 证据及耗时

最终证据：[browser-integration-report.json](../browser-artifacts/browser-integration-report.json)、[DPR2 完整图](../browser-artifacts/dpr2-full.png)、[DPR1.5 区域图](../browser-artifacts/dpr1.5-region.png)。共六张 PNG 和 18 条含 Frame、generation、识别像素、CSS 坐标、ActionResult、DOM 观测及耗时的记录。01.2/01.3 本轮回归证据在 .test-artifacts 的对应目录，未覆盖历史交付报告。

| 测量范围 | 样本数 | 中位数 ms |
| --- | ---: | ---: |
| await observe（附加新鲜度检查 + Capture） | 18 | 62.606 |
| await click_observation（几何检查 + PNG 定位 + Input） | 18 | 7.933 |

perf_counter 测量，不含额外 DOM 验证或磁盘 I/O。样本包含不同 DPR 和区域，不代表通用性能保证，也不等同于裸 capture/execute 的 01.3 计时。完整原始样本保存在报告。

报告确认：Input/Capture 关闭后 Session 仍 ready；owned_targets_remaining=[]，preexisting_targets_preserved=true；最终 pending_count=0、reader_running=false、connected=false、errors=[]。本轮另行枚举确认测试实例只剩启动时的 about:blank，然后通过 Browser.close 关闭实例并核对进程退出。profile 保留在被忽略的 .test-artifacts/edge-integration，供后续隔离测试管理；未尝试删除历史目录。

## 已知边界与后续

当前无需要等待接口协调的工程分支，无已确认阻塞性集成缺陷。历史启动环境限制仍按上述隔离参数处理。原有手动体验脚本的 lint 长行属于格式问题，本轮仅等价换行。

本阶段未验证后台输入、任意键盘布局、IME、人工 Ctrl+/- 缩放、真实游戏/WebGL 业务、长时压力或 Python 3.12/3.13 实机矩阵。HTTP/WSS 远端调试、JPEG 输入参数、visual offset/捏合缩放不在当前能力范围。原有不确定输入需上层恢复已知状态；不能把本次受控 DOM 命中推导成所有业务页面上的原子性或永久稳定保证。

BCA-02 接入责任和 BCA-03/04/05/06 契约见 MAIN_SYNC。后续由相应任务推进，不在本轮实现调度器、插件加载器、视觉库或 CLI。
