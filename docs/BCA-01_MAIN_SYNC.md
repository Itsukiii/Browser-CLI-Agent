# BCA-01 Browser 正式跨模块交接

2026-11-16，来源：本地源码与 BCA-01.4 本轮实际测试。**Browser 子系统已开发、集成验证完成，待本子会话最终审查及架构主会话归档**。未开展 BCA-02。包 `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`，Windows 优先；Python 3.12+，本轮实际 Python 3.14.7。

## 可直接依赖的入口

| 入口 | 职责与实际约束 |
| --- | --- |
| `bca.core.browser.BrowserSession` | `connect/list_targets/bind/refresh_target/unbind/send/close` 均 async；显式绑定唯一 page；暴露 connection、page_id、session_id、generation、bound_target、is_ready、state、last_error |
| `BrowserCaptureProvider(session, *, timeout=10.0)` | start/close、capture(page_id)；Browser 扩展 capture_region(page_id, *, x,y,width,height)；当前实际仅 PNG |
| `BrowserInputProvider(session, *, timeout=10.0)` | start/close、execute(Action)；available、last_error、input_state_uncertain；七类动作及保守失败恢复 |
| `CDPConnection`、`TargetManager` | 低层本机 CDP 及目标查询/绑定；普通消费者优先使用 Session，不直接缓存其 sessionId |
| `BrowserTarget`、`CDPEvent`、`SessionState` | 冻结目标/事件模型及状态枚举；详细字段见 BROWSER.md |
| `bca.core.providers` | CaptureProvider、InputProvider、ProviderRegistry、ProviderLookup；类型化查找，不隐式启动或释放 |
| `bca.core.protocol` | Frame、Viewport、Action、ActionResult、ErrorDetail、枚举及显式 codec；没有新协议字段 |

异常统一由 bca.core.browser 导出：BrowserError、CaptureError、EndpointError、CDPConnectionError、CDPDisconnectedError、CDPMessageError、CDPCommandError、CDPTimeoutError、TargetNotFoundError、TargetBindingError、TargetLostError。ValidationError、CapabilityUnavailableError、LifecycleError 位于 bca.core.errors。内部 geometry/keys 是实现细节，不是承诺稳定的新入口。完整签名与键名表见 [BROWSER.md](BROWSER.md)。

## 最小可运行闭环

先启动专用本机 CDP 实例，再执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe examples/browser_end_to_end.py --endpoint http://127.0.0.1:9339 --output browser-artifacts --samples 3
```

该脚本完整演示 connect → list_targets → 创建并显式 bind 自己的 Target → Provider.start → Registry.register → 类型化查询 → capture → 从 PNG 找标记像素 → Frame.pixel_to_css → execute → DOM 核验 → 按所有权清理。无需用户提供目标坐标，也不在已有网页上自动选点点击。目标由示例创建并记录，原有页面只枚举 ID。

正常业务代码也直接组合 Session、两个 Provider 和 Registry，无须新 Browser 门面或状态机。`registry.get(CaptureProvider)` 返回协议截图能力，`registry.get(InputProvider)` 返回协议输入能力；mypy 对抽象类型 token 可用局部 `# type: ignore[type-abstract]`。区域采集不属于 CaptureProvider ABC，应显式查找 BrowserCaptureProvider。

## 所有权、并发与恢复

1. 上层拥有 BrowserSession，Session 拥有 CDPConnection；Provider 只借用 Session。Registry 不拥有资源。连接与绑定由上层显式完成；start 前 Session 必须 ready。
2. 一个 Session 对应一个 Input Provider、一个 Capture Provider。两个 Provider 独立串行，跨 Provider 没有全局锁。需要观察/动作互斥的业务顺序由 Runtime 决定；不得从“先发起协程”推断并发动作顺序。
3. 退出时先停止调度，取消并 **await 正在进行的操作**，再 Input.close → Capture.close → Session.unbind/close。Capture.close 使在途结果失效，但不替调用方等待其任务；解码线程中的有界 CPU 工作会自行结束。Input.close 会等待执行锁并做必要释放，Session 最后关闭连接。
4. start/close 在约定阶段幂等，显式 close 后实例不可重新 start。发生连接失效可由上层明确 session.connect，再枚举和 bind；不自动重连、不自动选页、不自动重放动作。输入未知状态需先恢复已知浏览器状态，再创建新 Provider。
5. 解绑、重新 attach、换绑、销毁、断连会使旧身份失效。单动作/采集捕获 connection、page_id、session_id、generation，并在提交前/输入步骤间检查。旧操作不会把后续输入或清理发往新 Target。
6. 普通导航不改变绑定 generation 或 sessionId。bound_target 是缓存；要主动刷新元数据用 await refresh_target，但刷新也不是页面加载完成或 DOM 稳定保证。

## Protocol 2 与坐标

Frame 是冻结 dataclass，data 为自有不可变 PNG bytes，消费者可跨 await 持有；不复用可变缓冲。Frame.width/height 是实际图片像素。Viewport.width/height 是 CSS 内容视口，capture_* 表示最终栅格覆盖范围，区域向外取整、内容最右下边界可能少覆盖不足一个源像素。

唯一标准映射：`css = frame.pixel_to_css(px, py)`，再传给 Action(x=css_x,y=css_y,page_id=frame.page_id)。两轴独立换算，输入端不再乘除 DPR、不加 scroll。DPR 仅诊断；scroll 是文档偏移。内容视口是同原点的 visual/layout 交集，已经处理滚动条和小数尺寸差异。移动捏合缩放和非零 visual offset 明确拒绝。

Action/ActionResult 维持原七类动作。MOUSE_CLICK 是 down/up 两条 CDP 消息；独立 DOWN/UP 保持状态，释放要求有匹配按下；键名和 US 映射范围见 BROWSER。Unicode 使用 insertText，空串成功且不发送输入。ActionResult 原样回填 action_id，UTC-aware 起止时间，完成时间钳制防墙上时钟回拨；延迟用单调时钟。

## 失败与不确定输入

| 场景 | 调用方应处理 |
| --- | --- |
| 非法参数/坐标/目标/键名 | ValidationError，不应盲目重试 |
| 未启动/已关闭/未绑定/输入状态未知 | CapabilityUnavailableError；关闭后 start 为 LifecycleError |
| Capture 的采集/几何/PNG/CDP 失败 | 抛 BrowserError 子类，无空帧；总超时 CDPTimeoutError |
| 接受后的 Input CDP 拒绝/几何失败/总超时 | FAILED + ErrorDetail；首错停止后续动作 |
| 执行中换绑/断线/失效 | TargetLostError；Input.last_error 可含阶段及清理诊断 |
| asyncio.CancelledError | 原样传播；已发送动作可能已有副作用，上层可记录 CANCELLED |
| 未预期编程错误 | 原样抛出；不能把它当作成功或普通业务失败 |

执行 timeout 包含锁等待、测量和所有输入步骤。输入失败/取消后最多 **额外 1 秒** best-effort 释放，限定原身份。释放会触发 DOM keyup/mouseup/click 等，不能回滚。缺失响应时，命令可能已经执行；即使随后释放被确认，仍保守标记 input_state_uncertain 并拒绝后续输入。ErrorDetail 的 retryable=false，不授权自动重放。只重建 Python 对象不意味着浏览器实际输入状态已恢复。

ErrorDetail.details 记录 stage、completed_steps、input_attempted、release_confirmed、outcome_uncertain、input_state_uncertain、held_button_count、held_key_count；不含原始输入文本/敏感键序列。last_error 是最近失败诊断，不是每次调用都会清空的状态。

## 新鲜度与上层责任

Frame 没有 generation。page_id、frame_id、captured_at 都不能单独证明当前页面仍与截图相同。调用方应在观察时记录 connection/session/generation 和业务文档/布局上下文，输入前验证必要条件，变化时重新观察而不是猜测坐标。

集成示例的 Observation 在截图前后及输入前比较绑定、文档 href/timeOrigin、几何、滚动、DPR，拒绝已检测到的导航/resize/换绑；它只是示范策略。检查后 DOM 仍可能改变，点击、网页状态更新以及 DOM 观测不是原子事务。业务页面需额外定义有效期、稳定条件、焦点和动作后验证。SUCCEEDED 表示命令确认，不等于业务目标永久达成。

## 给各模块的稳定交接

| 消费者 | 可依赖的接口与必须自行编排的内容 |
| --- | --- |
| BCA-02 Runtime | Session/Provider 生命周期、Registry 和 ActionResult；负责动作顺序、背压、首错停止、观察上下文、任务取消后等待、显式恢复与资源所有权 |
| BCA-03 Plugin System | ProviderLookup 注入，按声明检查能力；不让插件关闭借用 Session，不隐式建立另一个 Input 所有者；版本协商仍属后续 |
| BCA-04 Vision & Assets | 解码不可变 PNG bytes、按实际像素识别、用 Frame.pixel_to_css；不要再除 DPR 或加 scroll，不缓存过期视口推断输入位置 |
| BCA-05 CLI | 显式 endpoint/target 选择、错误类别和未知结果提示；不向日志输出输入文本，不把重试按钮等同于安全重放；配置加载由该阶段实现 |
| BCA-06 Majsoul | 插件维护业务状态、识别置信与动作前后条件；Browser 不解释游戏规则、不会保证游戏动画期间画面稳定 |

## 本轮验收证据

Windows / Python 3.14.7 / Edge **157.0.4341.60** / CDP 1.3；独立端口 9339，有窗口实例、force-device-scale-factor=1.5。代理只测试自建页，未操作用户 9222。沿用环境可用的 --no-sandbox --disable-gpu --in-process-gpu，仅用于隔离测试。

- 本轮全量 **285 passed / 20.19s / 0 skipped**，四阶段真实入口均执行；新增 19 项模拟/局部集成及 1 个真实集成入口。
- mypy strict 36 个源码文件通过，Ruff lint/format、editable 安装、wheel/sdist 通过；完整执行记录见 [01.4_HANDOFF](BCA-01.4_HANDOFF.md)。
- [browser-integration-report.json](../browser-artifacts/browser-integration-report.json) 保存 18 次 Frame→Action→DOM，六张 PNG 位于同目录。DPR 1/1.5/2、全图/区域、有滚动条及 scroll=(80,120)；全部命中 mark，DOM 计数逐次增加，最大误差 **0.75 CSS px**。
- observe/click_observation 各 18 样本，中位数分别 **62.606 ms / 7.933 ms**。前者含附加新鲜度测量和 capture；后者含当前几何检查、PNG 定位、Action 执行。均不含 DOM 验证及磁盘 I/O，不与裸 Provider 时延直接比较。
- Provider 关闭后 Session 仍 ready；自建页剩余 0，原有页全部保留；最终 pending=0、reader=false、connected=false，cleanup.errors=[]。

## 能力边界与后续建议

当前未发现阻塞交付的集成缺陷。只支持本机回环 CDP、PNG、受控逻辑键；不提供远端/WSS、JPEG 参数、任意键盘布局或 IME。非零 visual offset/捏合缩放拒绝。后台输入、真实人工 Ctrl+/- 缩放、跨浏览器/平台、Python 3.12/3.13 实机矩阵、长时压力、真实业务 WebGL 仍未专项验证；模拟竞争测试不等同于生产负载证明。

后续可优化测量/解码开销、完善 Runtime 观察上下文和业务确认，但不得为优化取消 generation guard 或自动重放未知输入。当前无公共 Protocol/Provider 变更提案，保持本基线接入即可。
