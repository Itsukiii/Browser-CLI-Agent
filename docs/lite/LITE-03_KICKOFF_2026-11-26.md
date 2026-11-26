# LITE-03 · Interactive CLI Codex 开发启动交接

**启动许可：** LITE-02 于 2026-11-26 正式 Accepted。此文件是开发任务书，**不是 LITE-03 已实现/验收证明**。

## 0. 基线与先读

- `git switch lite && git pull --ff-only origin lite && git status --short`；确认最新 docs(lite) acceptance 已同步。
- 必读：`docs/lite/LITE-02_ACCEPTANCE_2026-11-26.md`、`docs/lite/LITE-02_HANDOFF.md`、`docs/lite/PLUGIN_CONTRACT.md`、`docs/md/BCA-LITE_MASTER_HANDOFF.md`（第8节）和 `docs/md/BCA_PROJECT_CONTEXT.md` 第0节。
- 以已验收的 `ObservationCoordinator`、`MaaVisionFacade`、`CDPBridge` 和 `FixturePlugin` 组合为唯一生产路径；终端层不接管 Native/CDP 内部生命周期，不绕过 Coordinator 授权。

## 1. 实现目标

交付 Windows PowerShell 中可实际使用的交互式入口，例如 `bca-lite` console script 和/或 `python -m bca.lite`，支持有意义的 `--help`、诊断和用户输入。用户能选择一个**明确指定的 CDP Target**、选择已安装业务插件，看到持续视觉状态增量输出、输入命令、取得新截图结果并安全退出。

CLI 保持纯壳层职责：加载配置 → 连接独立浏览器/显式 Target → 启动 Capture/Input → 构造 require_authorization=True Bridge → 构造 Facade/Plugin/Coordinator → 展示/命令 → 关闭 Coordinator 核对 CloseReport → 关闭 Providers/Session。没有理由在 CLI 再搭建一套 Runtime、插件自动发现和任务执行框架。

### 分三小步实施，避免一笔大改

**03.1：启动/配置/资源定位。** 定义最小 TOML（endpoint、目标选择、单插件名、model/manifest、观察间隔、日志级别、回调与图片时效），命令行参数覆盖与输入校验，支持明确目标列表/交互选择（不可默选其他个人页面）；演示 fixture 插件加载 wheel 内 Bundle，显式 OCR 资源哈希/许可说明与错误显示。离线单测与 wheel 异 cwd 入口验证。

**03.2：异步终端 UI。** 一条可编辑用户输入行、后台按业务 signature 仅在变化时显示状态；输入中后台变更不能破坏编辑缓冲区。`?` 必须触发 Coordinator 新截图、不是缓存。支持 Ctrl+C/EOF、help、stop/恢复、退出，使用成熟轻量终端组件或明确受支持的终端策略。队列/背压与重复提交行为须明确。

**03.3：真实 Edge 交互与故障验收。** 受控自有 Target 中实际 CLI `click 123`→Maa定位→CDP点击→OCR124/DOM oracle，人工/PTY/ConPTY 可复现输入及更新；错误时展示 NOT_FOUND / AMBIGUOUS / expired / unknown / target lost / stop failed，而不是静默重试；在途命令取消、关闭时不提前释放依赖；退出不关闭原有用户 Target；保留 CLI transcript/进程和资源证据。

## 2. 验收门槛

- **功能**：从新的 Windows 安装环境可以运行帮助与 CLI、显式 Target/插件选择；真实 Edge 同时观察和输入；状态不重复刷屏，读请求拿到新的 Frame/ObservationRef；命令只在确证回合/唯一候选时点击。
- **交互**：输入中后台刷新、长命令/非法命令、批量输入、停止重启、退出时 pending native/job、Ctrl+C/EOF、无 TTY 与终端编码边界均有可复现证据。测试不得用仅打印状态替代终端可编辑性。
- **安全**：Bridge require_authorization=True；按已验收的 native+CDP 双重确认；未知结果禁重放；Target/Geometry 不确定时停止且不切换其他标签页；仅关闭由当前 CLI 创建的目标。
- **质量**：pytest（lite 与离线完整回归）、mypy strict、Ruff、wheel/sdist；真实 Windows Edge 与独立安装证据；CPU/RSS 采样并注明是否实现 ROI 计划，不能把02.3的3.26核资源消耗藏起来。
- **交接**：单独 `docs/lite/LITE-03_HANDOFF.md`，记录源码/公共接口、复现命令、原始日志、截图、终端交互、故障、资源占用与未覆盖；交架构主会话核对，未 Accepted 前不提前写入 README / PROJECT_CONTEXT 的已验收状态。

## 3. 注意的已知限制

- OCR 全图可能有多个候选：应明确提示歧义并允许配置 ROI，不得降阈值、默认 best 或推定坐标。
- 02.3 真实 Edge 平均CPU约325.63%单核基准，进一步压低 CPU 是后续目标，但必须先验证测量和有效 >=1Hz 频率的权衡；如不在03达成目标须留到06且显式记录。
- 旧 Vision/OpenCV access violation 仍未归因，Windows native 进程卡死不能强杀单个线程。不要掩盖风险。
- LITE-04 才引入完整 Quiz 10s 换题/两步确认/分数结算；本阶段先做好终端和单步受控 fixture 验收。

**请 Codex 从 03.1 的设计与最小可安装入口开始，每小步独立测试、提交原始证据，再交付整阶段验收。**
