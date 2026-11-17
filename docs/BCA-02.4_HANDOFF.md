# BCA-02.4 最终集成交接

日期：2026-11-17。完成顺序为 A 原样基线与真实测量 → B 审计及两组定向修改 → C 同条件测量、故障注入、最终回归。当前停在 **02.4 交付审查**；未进入 03/05/06，未 commit/push。

## 本轮交付

- `examples/runtime_integration.py`：真实 PNG 定位红/蓝色块，经 Frame.pixel_to_css 得到输入坐标，Controller 提交真实点击，再截图识别颜色改变。DOM 仅用于独立断言；State、Frame、观察版本、批次/动作 ID、绑定及事件逐项关联。
- `tests/core/runtime/test_real_integration.py`、`cdp_fault_proxy.py`：完整闭环与六种真实 Edge 传输故障测试；中继只丢弃已经从 Edge 收到的特定响应，不伪造执行成功。
- `test_audit_regressions.py`：不必要对象持有、自回调死锁与输入回调生命周期保护。
- Runtime 核心仅修改 browser_freshness、action_pipeline、controller；详情见 [审计报告](BCA-02.4_CODE_AUDIT.md)。签名、Protocol 2、0.2.0 包版本、外部资源所有权不变。
- [BCA-02_MAIN_SYNC.md](BCA-02_MAIN_SYNC.md)：整合 02.1～02.4 的正式跨模块契约；[性能 JSON](BCA-02.4_PERFORMANCE.json) 保存前后汇总、计数、资源与清理结果。README/RUNTIME/INTERFACES/ARCHITECTURE/DEVELOPMENT_PLAN 同步当前状态。

## 环境与可重复命令

Windows、Python 3.14.7、pytest 9.2.0、Edge 157.0.4341.60。专用 Edge PID 10516，回环端口 **9341**，profile `.test-artifacts/edge-runtime-final`。启动使用 no-first-run/no-default-browser-check/no-sandbox/disable-gpu/in-process-gpu；这些为隔离测试实例配置，不改变用户系统设置。测试通过 Emulation.setDeviceMetricsOverride 设置 DPR 1/1.5/2、640×480 CSS；resize 场景改为 700×500。未连接 9222 或真实业务账户。

```powershell
$env:BCA_CDP_ENDPOINT='http://127.0.0.1:9341'
.\.venv\Scripts\python.exe examples/runtime_integration.py --endpoint $env:BCA_CDP_ENDPOINT --output .test-artifacts/02.4-before --samples 5 --duration 10
# 冻结原样报告后，审计并修改，再以相同参数运行：
.\.venv\Scripts\python.exe examples/runtime_integration.py --endpoint $env:BCA_CDP_ENDPOINT --output .test-artifacts/02.4-after --samples 5 --duration 10
.\.venv\Scripts\python.exe -m pytest tests/core/runtime -v -W error --basetemp=.test-artifacts/pytest-02.4-runtime
.\.venv\Scripts\python.exe -m pytest -W error -q --basetemp=.test-artifacts/pytest-02.4-full
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

不要在交付后的源码上覆盖 before 目录冒充原样结果；重做原样实验需要交付保存的源码 ZIP 或用户自己的基线副本。示例只创建、操作、关闭自己拥有的 Target，不关闭接入的整个浏览器；本次专用实例由测试执行者在全部验收结束后关闭。

## 实际执行结果

| 项目 | 本轮实际结果 |
| --- | --- |
| 修改前原样全量 | 435 passed，17.17s；不是引用 02.3 历史结果 |
| 审计复现 | 4 failed / 2 passed：两项对象持有，两项 submit/recover 自锁；证据冻结后才修改 |
| 第一组修改专项 | 17 passed / 4 deselected |
| 第二组修改专项 | 45 passed |
| 最终 Runtime（启用测试 CDP） | **165 passed，7.75s** |
| 最终全量（启用测试 CDP） | **450 passed，28.89s，无 skipped** |
| 最新真实闭环/故障资源补充专项 | **7 passed，6.44s**，包含新增未完成任务数检查 |
| 无 CDP 的 Runtime | **157 passed / 8 skipped，0.78s**，未隐藏真实测试跳过 |
| mypy strict | 51 source files，无问题 |
| Ruff check / format | 通过；最终文档加入后再检查 |
| build | 0.2.0 wheel/sdist 成功 |
| runtime_basics.py | version=1，两个订阅者收到同一 Event |
| runtime_observation.py | latest_version=4，通知版本 [1,2,3,4]，4 次完成、0 失败 |
| runtime_actions.py | succeeded / stale，version=2，accepted=2 |
| runtime_browser.py | 原有真实新鲜度/新目标恢复测试随全量运行通过 |

本轮新增 15 项：8 项审计模拟回归、1 项真实完整链路、6 项真实传输故障注入。全量 12 项 opt-in = 原 Browser 4 + 02.3 Runtime smoke 1 + 本轮 7；Runtime 单独有 8 项。Python 3.12/3.13 未实机验证：当前可用安装为 3.14，py launcher 无法执行；没有安装额外解释器或修改系统环境。

## 集成与故障证据矩阵

| 场景 | 证据类别 | 结果与入口 |
| --- | --- | --- |
| Capture→像素识别→State/Event→Action→DOM 效果→新截图状态 | real-browser | 每轮 30 次正常点击，DPR 1/1.5/2 × 全图/区域 × 5；report.records 保存帧/版本/动作/批次/页面关联，区域适配器明确借用 BrowserCaptureProvider.capture_region |
| 滚动、resize、导航、同目标重绑 | real-browser | 旧批次 STALE 且没有输入结果；重新观察后的新批次成功，不重放旧动作 |
| 目标销毁、重复 stop、原有标签保留 | real-browser | 阻断后停止，自有目标残留 0，原有 Target 保留 |
| 截图进行中取消 | fault-injection + real-browser | 真实截图返回响应被中继截留；Controller.stop 取消并等待，Store 未提交，pending 最终 0 |
| 鼠标 press 已执行后取消 | fault-injection + real-browser | 丢弃真实 press 响应后取消；DOM mousedown 恰好 1，发送释放，uncertain=true、动作通道 BLOCKED |
| 文本输入响应丢失 | fault-injection + real-browser | DOM 实际收到 probe，Input.insertText 仅发 1 次；超时失败、uncertain=true，不自动重试 |
| 鼠标释放响应丢失 | fault-injection + real-browser | press 和 release 的真实响应均被丢弃，释放等待有界，保留 unknown，未冒充撤销或确认恢复 |
| 持键 keyDown 响应丢失 | fault-injection + real-browser | DOM keydown 恰好 1，发送 keyUp 清理，输入阻断 |
| 真实传输断开 | fault-injection + real-browser | 中继关闭上下游 WebSocket，绑定失效，输入被拒绝，reader/连接最终关闭 |
| 新目标恢复与同目标重建拒绝 | real-browser + simulated | 原有 02.3 真实 smoke 本轮复跑；来源证明回归保留，不以 retire Provider 测试代替响应丢失证据 |
| 32/33 FIFO、容量/排队/执行/结果取消、首错、停止竞争 | simulated | 原动作管线竞争测试全保留；真实串行基准不声称覆盖队列压力 |
| begin/observe/validate/publish/notify 失败和取消、部分启动、慢 Bus | simulated + real-browser | 原精确屏障回归保留；真实 slow subscriber 导致一次通知超时，已提交状态不回滚 |

故障中继首次接入因使用 ws URL 而被既有 HTTP discovery 安全边界拒绝；修正的是测试中继的本机 /json/version 接口，未放宽 Browser 端点限制。清理断言同时改为等待 Target.closeTarget 的异步销毁完成，避免把“关闭已接纳”误认作“已消失”。此过程最终均通过，早期失败日志不作为验收成果。

## 同条件性能对照

单位 ms；值为 median / p95，分位数取 nearest-rank。所有原始时长和最大值保存在 before/after 的 report.json，正式汇总含 n/median/p95/max。每次都启用 tracemalloc 和同一测量边界，两个样本未并行压测；主机其他负载/GC/渲染波动没有被控制。持续观察按固定时长运行，所以样本数随吞吐不同。

| 指标 | before n→after n | before median/p95 | after median/p95 |
| --- | --- | --- | --- |
| 全图 Capture | 85→76 | 68.056 / 114.002 | 71.537 / 143.848 |
| 区域 Capture | 26→26 | 55.840 / 81.272 | 51.933 / 80.391 |
| 全图非 CDP 剩余时间 | 85→76 | 17.574 / 50.854 | 16.967 / 74.498 |
| 区域非 CDP 剩余时间 | 26→26 | 3.340 / 4.630 | 2.993 / 6.857 |
| observe（capture + 像素识别） | 111→102 | 79.938 / 154.957 | 78.689 / 191.195 |
| StateStore.publish | 111→102 | 0.016 / 0.027 | 0.019 / 0.051 |
| EventBus.emit（含故意慢订阅者） | 150→141 | 0.019 / 0.036 | 0.021 / 0.061 |
| 动作新鲜度校验 | 38→38 | 1.422 / 2.597 | 1.376 / 5.146 |
| InputProvider.execute | 34→34 | 3.057 / 13.196 | 3.242 / 12.460 |
| 动作排队等待 | 30→30 | 0.069 / 0.119 | 0.067 / 0.133 |
| submit 至新状态（含 resume/观察完成屏障） | 30→30 | 66.780 / 109.218 | 62.008 / 90.357 |
| 10 秒持续段的观察间隔 | 62→53 | 194.952 / 208.285 | 196.540 / 305.246 |

未把 CDP screenshot 往返称作纯浏览器截图执行时间；非 CDP 剩余时间包含 PNG CRC/解码/裁剪/重编码及 Python/测量开销，无法进一步无侵入拆出纯解码。本轮不修改底层 Capture 来人为创造分段数据。DOM 断言和截图落盘不计入端到端计时；识别与 Runtime 校验计入。

每轮观察 **9 个** page CDP 请求：Runtime begin/validate 各 2，Capture 前后几何 4 + screenshot 1。每次点击 **6 个**：Runtime freshness 2，Input 几何 2，press/release 2。前后相同，未删除不同阶段的安全检查。完整分类计数见性能 JSON；Target/Browser setup 请求明确不计入 page 请求计数。

全程观察峰值 1；before/after Scheduler started=111/102、skipped_ticks=45/52、coalesced_requests=57/57。立即请求在本基准多数与 resume 后到期 tick 合并，immediate_runs 均为 0，不能据此声称测得纯立即请求调度延迟；独立示例实际验证 immediate_runs=1。100ms 配置不保证这台机器上截图识别达到 10Hz。

端到端样本变快，但观察尾延迟和持续吞吐变差，**不宣称总体性能优化**。确定的收益是对象所有权精简和自锁修复。

## 资源与清理

| 采样 | before | after |
| --- | --- | --- |
| 资源样本/实际采样跨度 | 130 / 13.877s | 128 / 13.780s |
| Python 分配 首/尾/峰值（bytes） | 2144546 / 2666003 / 2826601 | 2145284 / 2471718 / 2829212 |
| 全事件循环任务数范围 | 7～8 | 7～8 |
| 采样 pending 峰值 / queue 峰值 | 1 / 0 | 1 / 0 |
| 结束 pending / reader / connected | 0 / false / false | 0 / false / false |
| 自有目标残留 / 新增未完成任务 | 0 / 0 | 0 / 0 |
| 原有 Target 保留 / 关闭异常 | true / [] | true / [] |

tracemalloc 包含累计 JSON 样本/事件/帧记录，不覆盖 Pillow 原生内存和 Edge 进程；前后持续观察样本数不同，不能将尾内存差直接归因于重构，也不能从十秒样本推断长期无泄漏。弱引用专项可单独证明 Frame 和退役 Provider 已不再被策略额外持有。真实传输故障专项也逐项记录 pending/reader/connected、新增未完成任务=0；失去响应的输入保持 uncertain=true 是正确终态。

`.test-artifacts/02.4-before/` 和 `02.4-after/` 各有 report.json 与六张 DPR/区域截图；before 另有源码 ZIP/哈希及原样 pytest 日志。故障 JSON 位于 `.test-artifacts/pytest-02.4-faults/test_real_transport_faults_*/`；最终质量日志为 `02.4-runtime.log`、`02.4-full.log`、`02.4-no-browser.log`、`02.4-build.log`。全部产物在原有忽略目录，无根目录临时 profile 增生。

最终清理时专用浏览器仅剩启动的 about:blank，所有测试目标已消失；通过 Browser.close 关闭实例，复核 PID 10516 和 9341 监听均已消失。记录保存在 `.test-artifacts/02.4-browser-cleanup.json`。最终 Ruff 为 133 files already formatted。

## 工作区与剩余边界

HEAD 仍是 Browser 历史 `19df477547c26a4131d96191a8bb8bdb8362a4ea`，02.1～02.4 均保留本地修改，未 commit/push。用户 PROJECT_CONTEXT 的原修改、browser-artifacts-manual 和旧阶段证据不覆盖。`git diff --check` 仅报告该用户文件第 6、7 行原有 Markdown 尾空格；排除该文件后通过。常规 diff --stat 不含 untracked Runtime，不能作为本轮完整规模。

剩余限制：Python 3.12/3.13 实机矩阵、数小时压力及进程/native RSS、硬件/系统级按键状态恢复、真实生产页面行为、同指纹 DOM 局部变化和检查到送达之间 TOCTOU 未被消除。响应丢失/释放响应丢失为确定作用点的真实传输故障注入，不等同覆盖所有 OS 或网络故障。仅支持新目标显式恢复；DOM-only 动作授权与同目标恢复仍需架构设计。下一阶段接入遵循 MAIN_SYNC，不以已交付测试替代具体业务插件验收。
