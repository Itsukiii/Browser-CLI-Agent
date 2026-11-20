# BCA-03.2 / 真实浏览器集成与实施交接

2026-11-20。本阶段按 A 源码与基线、B 真机闭环、C 故障与清理、D 测量与回归顺序完成。**实施完成，提交架构主会话审查；本报告不代替主会话 Accepted。** 包版本 0.2.0，Protocol 2 不变。

## 工作区来源与交付文件

分支 main，HEAD 为 `550cdfa0b042e4cee95f0d7f53e88a7d84d62c43`。启动时已包含完整未提交的 03.1 源码、测试、示例和文档。本轮直接继续开发，没有 checkout/reset，没有 commit/push。用户 `docs/md/BCA_PROJECT_CONTEXT.md` 修改保留。

03.2 新增：

- `examples/plugin_integration.py`：真实 CLI、资源所有权、PNG→插件→Host→Input→新 PNG/DOM 验证、测量与 JSON；支持 endpoint/output/samples/duration，不依赖固定盘符。
- `examples/plugins/pixel_fixture/{plugin.toml,__init__.py,plugin.py}`：实际相对导入的可信测试插件，使用 Pillow 识别受控红蓝色块。
- `tests/core/plugins/real_helpers.py`；test_real_integration.py 3 项、test_real_faults.py 9 项、test_real_lifecycle.py 12 项、test_deployment.py 2 项。共新增 26 项，其中 24 真机、2 本地部署边界。
- 本文、`BCA-03_MAIN_SYNC.md`、`BCA-03.2_PERFORMANCE.json`。

同步 README、ARCHITECTURE、PLUGIN_SPEC、INTERFACES、RUNTIME、DEVELOPMENT_PLAN；plugin_browser.py 只更新入口说明。03.1 Core 插件实现保持原样，Browser/Runtime/Provider/Protocol/SDK 源码无 diff。原四项插件类与 HEAD 原定义 AST 一致，证据和源码 SHA256 见 `.test-artifacts/03.2/compatibility.json`。

工作区含 tracked 修改及 untracked 文件，普通 diff --stat 不包含全部新增源码。建议先提交完整 03.1 核心和基础测试，再提交 03.2 真实集成、测试与交接；PROJECT_CONTEXT 与原需求单独审核。最终清单为 `.test-artifacts/03.2/git-status.txt`。

## A：源码审计与基线

新增内容前实际运行：插件专项 **58 passed，0.56s**；无 CDP 全量 **495 passed、12 skipped，10.38s**，与 03.1 交接相符。

| 审计对象 | 源码证据、测试与结论 |
| --- | --- |
| contracts/models/errors、SDK 和根导出 | 原契约内部迁移，无 codec 扩展；AST 对照及旧 example 通过 |
| catalog.read_descriptor/discover/get | 静态 TOML、字段/协议、重复 ID 全拒选、resolve 边界；原测试和实际部署验证通过 |
| loader.load/_create、validation | 路径摘要隔离包、相对导入、失败命名空间回滚、成功缓存、每次调用工厂、签名/metadata 校验；原单测与外部目录子进程通过 |
| lookup、capture_adapter.capture | 只读 override、类型/readiness 一致、仅 policy.capture(raw)、嵌套拒绝；mock 单次提交与真实矩阵通过 |
| manager._invoke/_ensure_cleanup/stop/close | 锁串行、一次取消、共享终止、主异常与 cleanup 分离；原重叠 stop/close、取消等待者及新真机生命周期测试通过 |
| host._execute/_close | 保存原 ref、命令串行、先停 Controller、等待命令/启动清理、关闭不 resume；生成挂起、排队、双关闭、捕获/输入关闭通过 |
| cleanup failed 的可观测性 | 示例保留 Manager 句柄；真机证明插件任务可能仍在，产品清理与测试 owner 补救分别记录 |
| 新 Target/Provider 后的引用 | text_timeout 后退役旧组合，创建一致的新策略/Input/View/Manager/Host，旧批次未重放 |
| 文档与源码一致性 | 同步阶段状态与实际入口，保留历史报告，不修改上游接口迁就测试 |

未发现必须修改稳定上游接口的产品缺陷。新示例与测试实施中修复的问题：

1. Composition 在 adapter.start 前查询 Capture readiness 被正确拒绝；改为启动后验证对象身份。
2. lifecycle 夹具在 stop 故意失败后，close 又调用同一失败 stop，形成额外失败；改为独立释放资源。早期 stop CancelledError 跳过 helper 的 Exception 分支，改为 BaseException 分类收尾；遗留自建页已清理，记录在 pre-final-cleanup.json。
3. rebind 重置 CDP Performance 域，初轮 after metrics 为空；在新 attachment 重新 enable 并断言非空，重跑正式 final-1、final-2、final-3。旧 measure-1、measure-2、measure-3 保留，不把空数据视为有效统计。

没有将失败改为 skip/xfail。

## B：环境、隔离与真实闭环

用户明确授权创建独立 Edge。Windows、Python **3.14.7**、pytest 9.2.0、Edge **157.0.4341.60**；端点 `http://127.0.0.1:9341`，profile `.test-artifacts/03.2/edge-profile`。

初始 PID 13960 未带 no-sandbox 时 Runtime.evaluate 超时；关闭自有实例后按历史验收参数重启，PID 27076：

```text
--remote-debugging-port=9341 --remote-debugging-address=127.0.0.1
--user-data-dir=<repo>/.test-artifacts/03.2/edge-profile
--no-first-run --no-default-browser-check --no-sandbox
--disable-gpu --in-process-gpu about:blank
```

没有 headless 参数；隐藏启动窗口，测试将自建页面 bringToFront。未连接用户 9222。每项测试先记录已有 Target ID，只操作自己登记的目标，等待其实际关闭后检查预存集合保留。

B 首批 **3 passed，2.97s**。插件从真实 PNG 识别红蓝色块位置和颜色；DOM hits 只作外部 oracle。Frame.pixel_to_css 生成 CSS 坐标，输入后新截图验证状态。暂停屏障下，新提交使 Store.version 和插件 sequence 各增一；契约仍视其为两个独立计数。

| 场景 | 断言与结果 |
| --- | --- |
| Catalog→Manifest→工厂→Manager→Host | pixel-fixture 0.2.0，请求 capture/input；原 example 另有真实点击测试 |
| DPR 1/1.5/2 × 全图/区域 | PNG 实际尺寸与 capture extent/DPR 一致，CSS 点在 marker 内，真实点击命中 |
| 状态及动作关联 | source_frame_id、前后版本、原引用、Command/Action/request ID、Batch/Action ID 对应；每轮保存六张 PNG |
| 动作后确认 | SUCCEEDED 后新的 PNG 颜色翻转，DOM hits 恰好加一，不以输入确认冒充业务完成 |
| scroll、resize、navigate、reload | 原状态命令 STALE，无输入结果、DOM 次数不变；新观察后新命令成功。reload 为同 URL 新 timeOrigin |
| unbind/rebind | 原命令 STALE，新观察后新命令 SUCCEEDED |
| 旧版本批次 | 保存批次后由 Runtime 提交新观察，旧批次继续使用原引用，STALE 且无输入 |
| Target 关闭 | Host 返回 BLOCKED；与 handle 并发也不发送 Input，不复用旧身份 |
| 不同 cwd | 从 D:/Project 以绝对路径执行脚本，完整矩阵通过，报告在 foreign-cwd |

保持 href/timeOrigin/几何不变的局部 DOM 更新或 document.write，以及检查后发生的页面变化，不属于 BrowserFreshness 的事务保证，本报告没有将其列为已验证拒绝场景。

## C：真实故障、恢复与清理

复用 `tests/core/runtime/cdp_fault_proxy.py`。Edge 真正处理并回复命令后，中继才按 method/kind 丢弃响应或断开连接，不以模拟 Provider 异常代替真实故障。默认报告不记录输入文本、截图 bytes、完整 CDP payload 或未经清理的异常消息。

| 真机场景 | 触发点及实际判定 |
| --- | --- |
| text_timeout | insertText 已产生 DOM 副作用，响应丢失；只发一次，FAILED/BLOCKED、uncertain=true |
| press_cancel | press 响应丢失后取消，DOM down=1，发送释放；调用抛 CancelledError，Runtime cancelled=1、BLOCKED |
| release_timeout | press/release 响应均丢，等待释放超时，保留诊断，FAILED/BLOCKED，不声称撤销 |
| key_disconnect | keyDown 已处理后断开中继，独立 owner 观测 keys=1；FAILED/BLOCKED、uncertain，不向新目标释放 |
| capture_timeout | 截图响应丢失，观察 failed、Manager last_error、Store.version=0；恢复传输后新观察 version=1 |
| capture_close | 截图响应截留期间双 close，Store 保持0，组件正确终止 |
| fingerprint_disconnect | 指纹测量响应截留后断连，FAILED/BLOCKED，Input 发送数0 |
| input_close | press 已处理时双 close，等待释放和取消，Runtime cancelled=1，最终 STOPPED |
| target_during_handle | 生成动作后挂起，owner 销毁目标再继续，BLOCKED、无 Input |
| initialize/start/stop/close × 失败/取消 | 主错误与 cleanup 错误分开归档，已分配后台任务按预期清理 |
| 外部取消 initialize/start | 重复取消 start 并发 close，仍等待 finally 栅栏，不二次取消清理 |
| 生成、排队、双关闭等待者 | 取消一个等待者不影响另一个，活动命令取消，排队命令 LifecycleError，不 resume |
| close 失败且未释放任务 | cleanup_status=failed，实际残留一个插件任务；fixture owner 补救后0，不把正常返回当清理成功 |

C 修正夹具后首轮 **18 passed，7.94s**；部署/生命周期补充 **14 passed，3.04s**，有重叠，不累加作新增数。最终真实插件定向 **24 passed、59 deselected，14.61s**。

### 显式恢复与所有权

text_timeout 真实故障使旧 Controller BLOCKED。等待输入收尾，关闭旧 Host、adapter、Input；old_policy.create_recovery_target 创建不同 ID，重新绑定并准备页面；新建 Store、Bus、策略、Input、View、Manager、Controller、Host。

新 View 和 Controller 使用同一新 Input，新可信观察后提交新命令，PNG 为蓝色、hits=1、输入框为空。旧 Controller 永久 STOPPED，旧批次重放数0。这是全组合重建，不假称调用旧 Controller.recover；原 Runtime recover 真机测试也随全量通过。

Host 负责 Controller/Manager，adapter 借用原始资源，Application 负责 Input、Capture、Session、Store/Bus、自有 Target。正常顺序：Host.close → adapter.close → Input.close → Capture.close → 自有目标关闭 → Session.close → Store/Bus.close。

每个 helper 验证 Manager CLOSED、Controller STOPPED、排队数0、pending CDP0、reader=false、connected=false、自有目标残留0、预存目标集合保留。代理退出后 run() 比较 asyncio.all_tasks 与入口集合，要求无新增未完成任务。故意清理失败案例记录 failed 和真实残留，再独立补救，不隐藏插件自身责任。

### 实际部署边界

在系统临时目录复制 example，增加相对 implementation 导入。仓库外绝对根、子进程不同 cwd、模块缓存下新实例、重复 ID、缺失文件及非法工厂诊断通过。

真实目录符号链接创建返回 **WinError 1314**，JSON 标记 not_verified。权限分支测试通过不等于真实 symlink 防逃逸已验收。03.1 确定性 resolve 边界测试保留。

## D：质量检查与复现

表中 python 指当前 venv 的 `.venv/Scripts/python.exe`。真机运行前设置 `$env:BCA_CDP_ENDPOINT='http://127.0.0.1:9341'`；本地回归前移除该环境变量。

| 实际命令 | 结果 |
| --- | --- |
| `python -m pytest tests/core/plugins tests/plugin_sdk/test_example.py -v -W error --basetemp=.test-artifacts/pytest-03.2-plugins` | 84 passed，14.12s |
| `python -m pytest tests/core/plugins -m browser_integration -v -W error --basetemp=.test-artifacts/pytest-03.2-final-edge` | 24 passed、59 deselected，14.61s |
| `python -m pytest -q -W error --basetemp=.test-artifacts/pytest-03.2-full-edge` | **533 passed、0 skipped，47.58s** |
| 移除 CDP 环境变量后 `python -m pytest -q -W error --basetemp=.test-artifacts/pytest-03.2-full-local` | **497 passed、36 skipped，13.03s** |
| `python -m mypy` | Success: no issues found in 66 source files |
| `python -m ruff check .` | All checks passed |
| `python -m ruff format --check .` | 162 files already formatted |
| `python -m build` | 成功构建 browser_cli_agent-0.2.0.tar.gz 和 browser_cli_agent-0.2.0-py3-none-any.whl |
| `python examples/plugin_runtime.py` | simulated、candidates=1、succeeded、version=1，生成 request/action ID |

全量之后仅补充 Performance 重绑定采样和等价类型收窄，没有改 Core 行为；随后定向真机、mypy、Ruff 再复核。日志在 `.test-artifacts/03.2/{plugins,final-edge,full-edge,full-local,build,quality}.log`。

533 = 原03.1的507项总测试 + 新增26。497项非真机包含单元、模拟CDP和部署测试，不能全部称 mock；36项真机 = 原Browser4 + 原Runtime8 + 新Plugin24。无CDP的36个skip均来自显式真机门槛。

当前只验证 Python 3.14.7；py launcher 无法执行，未取得3.12/3.13实机证据。未新增依赖、安装解释器或修改系统环境。

```powershell
.\.venv\Scripts\python.exe examples/plugin_integration.py --endpoint http://127.0.0.1:9341 --output .test-artifacts/03.2/reproduce --samples 3 --duration 3
```

以上仅连接明确授权的隔离实例。示例只操作并关闭自建目标，不关闭外部浏览器；本轮专用实例最后由 owner 单独关闭。

## 性能与资源统计

正式 final-1、final-2、final-3 使用相同 Edge 参数，640×480 CSS，DPR 1/1.5/2 × 全图/区域 × 每例3次，共 **54次矩阵点击**。每轮另有5次新鲜度更新后点击，共23次成功输入。持续观察配置3秒，含停止屏障实际为3.087/3.153/3.053秒，观察15/16/15次，持续段点击0次。

| 采集边界 | n | median ms | p95 ms | max ms |
| --- | ---: | ---: | ---: | ---: |
| Host.start 到首次状态提交 | 3 | 203.85 | 204.85 | 204.85 |
| 观察 begin 到 Plugin/Adapter/Capture/校验及 publish | 54 | 59.37 | 86.51 | 91.84 |
| execute_text 到 BatchResult | 54 | 6.34 | 18.90 | 22.70 |
| 命令发起到下一份像素状态提交屏障完成 | 54 | 67.16 | 96.09 | 99.82 |
| Runtime queue wait | 54 | 0.065 | 0.143 | 0.204 |
| Runtime execution，含授权检查和输入 | 54 | 5.70 | 18.20 | 21.35 |

p95 使用 nearest-rank；三个启动样本的p95等于max，不构成充分尾分布证据。观察耗时为 Runtime last_observe 与 last_publish 之和，不含通知。命令至状态包含 resume/pause、识别与调度，不含之后DOM oracle及磁盘写入，不能称纯Input→commit。未独立拆分parse/handle；执行段含新鲜度校验，不是裸CDP。

启用tracemalloc并累积JSON样本，有测量开销；主机其他负载未冻结。与BCA-02边界不同，不直接比较，不宣称总体性能提升或稳定10Hz。

每轮accepted29、completed23、STALE5、BLOCKED1、FAILED0、CANCELLED0，最后销毁目标产生BLOCKED。skipped ticks为20/22/20，串行点击队列采样峰值0，不代表容量压力验证。

Python tracemalloc起始/结束/峰值bytes：

- 240476 / 1458928 / 1743036。
- 240595 / 1474390 / 1742994。
- 240638 / 1459449 / 1744201。

上述包含报告、帧和缓存，不是进程RSS，也不能单独判定泄漏。Edge SystemInfo.getProcessInfo 保存进程CPU累计值，Renderer JS heap末值为897140/899596/897140 bytes。rebind后重新启用Performance，TaskDuration仅覆盖新attachment，不能作为整轮CPU。native/Edge RSS和数小时压力未验证。

三轮结束均为Plugin CLOSED且cleanup succeeded、Controller/Action STOPPED、pending0、reader=false、connected=false、自有Target0、预存目标保留、新增未完成任务0。最终专用Edge PID27076和端口9341监听均为0，见browser-cleanup.json。

## 产物与正式审查判定

- [跨模块说明](BCA-03_MAIN_SYNC.md)：实际API、装配、所有权及后续模块要求。
- [性能JSON](BCA-03.2_PERFORMANCE.json)：统计与逐轮资源数据。
- `.test-artifacts/03.2/plugin-integration-report.json`：版本、质量、24项真实场景、三轮测量、部署与最终清理。
- `.test-artifacts/03.2/final-{1,2,3}/`：原始时长、关联ID、PNG及逐轮报告。
- `.test-artifacts/pytest-03.2-full-edge/test_*/report.json`：场景证据；最后定向复核位于pytest-03.2-final-edge。
- foreign-cwd为异cwd真实运行；pre-final-cleanup记录早期夹具补救；compatibility保存契约AST和源码哈希。

| 正式审查条件 | 结论 |
| --- | --- |
| 源码契约 | 已审计并回归，无稳定上游接口变更 |
| 真机链路 | 已验证PNG、PageState、可信引用、Host批次、Input、新PNG/DOM |
| 来源与新鲜度 | DPR、全图/区域、滚动、resize、导航/reload、重绑、关闭、旧版本通过；同指纹局部变化不属保证 |
| 未知结果 | 真实丢响应、断连、取消保守阻断，不重放；新目标新组合恢复通过 |
| 生命周期 | 正常、异常、取消、并发关闭通过；预期清理失败有真实残留和独立补救证据 |
| 可靠性与性能 | 有样本、统计与边界，仅短时受控页，不承诺长期或RSS指标 |
| 质量 | 专项、全量真机、本地、mypy、Ruff、构建及示例通过 |
| 交接 | Markdown与JSON对应实际证据，供主会话复核 |

可提交正式审查，Accepted由主会话确认。剩余证据缺口：真实Windows symlink权限环境、Python3.12/3.13、长期压力/native RSS、生产页面、硬件状态恢复。没有本轮必须改变稳定协议才能完成的协调项。同目标恢复证明、DOM-only授权、热换插件/Provider、进程沙箱、跨层合并测量若需实现，应另行设计。

编码修复说明：旧文件中文已被写成字面量问号，不能靠切换查看器编码恢复。现已重新生成UTF-8中文内容；本次只修复两份交接文档，不重新执行或改变上述历史测试结果。
