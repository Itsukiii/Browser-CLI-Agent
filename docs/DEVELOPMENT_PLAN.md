# BCA-00～07 开发与验收计划

公共基线：包 0.2.0 / Protocol 2，标准库类型契约。编号和职责以 `docs/md/BCA_PROJECT_CONTEXT.md` 为依据。

| 阶段 | 主要依赖 | 接入约定与验收点 |
| --- | --- | --- |
| BCA-00 Protocol | 总纲与原始、增量需求 | 六模型、Provider/Plugin 契约、显式 codec、无运行时依赖、单测/类型/安装验收；本轮结论见 HANDOFF |
| BCA-01 Browser | BCA-00 | 01.1～01.4 已开发并完成本轮验收测试，待阶段审查；实际采集仅 PNG；连接、绑定、Capture/Input、坐标闭环、取消与资源清理见 BCA-01_MAIN_SYNC.md |
| BCA-02 Runtime | BCA-00，按需 BCA-01 | Scheduler、Event Bus、State Store；实现 Sink 背压；observe 返回后单次发布；同页动作串行、首错停止；验证单调计时、状态序号、取消及关闭顺序 |
| BCA-03 Plugin System | BCA-00、BCA-02 端口 | 发现/加载、能力检查、ProviderLookup 和 Context 注入；初始化失败清理、stop/start/close；明确基线版本兼容及插件实例会话 |
| BCA-04 Vision & Assets | BCA-00 | 按需引入 OpenCV/NumPy；按需解码 Frame；JSON Manifest/INI Profile；模板与稳定语义 ID；验证图像完整性、非等比转换、资源缓存和样本回归 |
| BCA-05 CLI | BCA-00、BCA-02/03 | TOML 加载、异步输入与刷新、Command 路由和插件格式化；错误分层、关联日志；验证输入不阻塞观察、退出和诊断流程 |
| BCA-06 Majsoul | BCA-01/03/04/05 | 视觉识别与资产在插件侧；PageState schema 独立；截图点转 CSS 后映射 Action；真实样本识别、未知状态与动作边界回归 |
| BCA-07 Integration | 所有相关模块 | 真实浏览器与 CLI 全链路；重连、过期帧/动作、队列背压、取消、输入释放；单调时钟延迟、CPU/内存、长时稳定性；Python 3.12+ 运行矩阵 |

Browser、Runtime、SDK 可依照契约分别开发；集成前先通过 fake Provider/Plugin 测试，再验证真实后端。BCA-00 的模拟链路不代表后续模块已实现。

后续需协调的具体决策：浏览器连接与权限、插件发现和版本协商、事件队列容量/丢弃策略、动作超时/焦点/截图新鲜度、资源格式细节、跨进程图像和插件隔离。当前标准状态路径为拉取；若引入推送模式，须先在 BCA-02/03 定义互斥调度策略，防止双重发布。

## BCA-01 交付状态（2026-11-16）

- 01.1：本机 CDP、页面发现、显式绑定及元数据刷新。
- 01.2：PNG 完整/区域采集、内容视口测量及像素坐标转换。
- 01.3：七类 Action、ActionResult、按住状态与有界释放、不确定输入处理。
- 01.4：示例及跨模块验收，本轮 285 passed / 0 skipped，含四个真实 Edge 入口；正式交接为 [BCA-01_MAIN_SYNC.md](BCA-01_MAIN_SYNC.md)。

当前无已确认的阻塞性集成缺陷。下一步由本子会话审查 BCA-01，主会话归档正式交接；本轮不实现 Runtime。BCA-02 需负责旧帧上下文、动作队列、首错停止、取消任务后等待结束、输入先关闭和显式恢复。`BrowserSession.generation` 表示绑定身份，不表示 DOM 版本；单凭 page_id 或 generation 不能保证截图内容新鲜。
