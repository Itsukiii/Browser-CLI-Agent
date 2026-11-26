# LITE-03 · Interactive CLI 正式验收记录

- 日期：**2026-11-26**
- 分支：`lite`，实施/证据 `bdd3f8a`、`f9fef05`、`b62d57b90a39d4597077079c5be451f55c523d78`，交接 `815cda10beefa60113f8afe0cca7deb4ac4ce8f0`。
- **正式裁决：LITE-03 Accepted。批准准备 LITE-04 Quiz Demo 设计。**

> 依据 GitHub 远端源码、pytest/ConPTY运行测试、原始 JSON、终端记录和wheel完整性文件静态/证据复核。架构主会话未在用户 Windows 机器独立运行测试。验收当前Windows/Edge/maafw版本的功能与风险边界，不扩大到任意终端输入法、OS或网页。

## 1. 接口及架构

- `bca-lite` console script 与 `python -m bca.lite`；`--help`、`--check`、`--list-targets`、`--once`、`--create-fixture`；严格 TOML、显式 OCR 模型/manifest 哈希，CLI 参数覆盖和明确 Target ID 绑定。
- `cli_session` 唯一控制 Session、Providers、Bridge、Facade、Coordinator 的组合与关闭；既有浏览器页面不自动关闭或修改 DPR；只有用户明确 `--create-fixture` 才创建并拥有测试 Target。
- `prompt_toolkit` 可编辑命令输入、后台有限状态提醒、单命令在途 Busy 拒绝；`?` 总是请求新截图；`click <visible-round>` 由已验收 Maa/Coordinator 动作校验和后置视觉观察完成。
- `stop/resume` 排空并保留/重启组合，`quit/exit/EOF/Ctrl+C` 层层排空并核验 native CloseReport；失败时最多有限重试，无释放证明则退出 CLI 自身进程码3，避免原生句柄不确定的重复析构；无法保证永久Native卡住时强行退出。

## 2. 原始证据矩阵

| 验收项 | 证据 | 结论 |
| --- | --- | --- |
| ConPTY × Edge | `docs/evidence/LITE-03/03.3/final-pty/stdout.txt`: **7 passed / 32.36s**；可编辑缓冲、后台更新、点击与DOM oracle、quit/Ctrl+C/EOF、失效/故障 | 通过 |
| Wheel × ConPTY × Edge | `clean-pty/stdout.txt`: **6 passed / 23.93s**；干净venv、系统Temp cwd、显式Target选择与用户页保留 | 通过 |
| 失效来源 | `expired/stdout.txt`: **1 passed**，超龄拒绝、零DOM输入、released=True | 通过 |
| 人工终端 | `manual-powershell.txt`: 用户提供 `click123→124→125`、旧回合拒绝、三次`?`帧均不同、quit释放 | 已有基础人工证据；IME候选窗等尚未独立确认 |
| 观察频率 | `performance-01/data/performance/metrics.json`: 66.1624s、87/87有效、**1.31495Hz**，0 dropped/skipped、同内容只提示一次 | 通过 |
| CPU / RAM | `performance-01/summary.json`: 单工作PID平均CPU **397.02%**（单核=100%）、峰值RSS **153.35MiB**、PrivateBytes **611.52MiB** | 已量化，后续性能专项 |
| 异常退出 | `final-pty/data/stop_failed/report.json`：exit3、依赖未提前关闭；`pre_click_failed/report.json`：unknown、DOM零点击、禁止重发 | 通过 |
| 全量离线 | `offline-final/stdout.txt`: **907 passed / 66 deselected / 57.06s**；真实浏览器用例另跑 | 通过 |
| 分发质量 | `installation-final.json`：源码、最终wheel、干净安装中的lite文件全部一致；mypy107、Ruff/format284、build与pip check通过 | 通过 |

## 3. 风险与继承约束

1. **性能：** 此运行CPU约3.97核，LITE-02性能证据约3.26核，但测试时的其他构建/安装负载及不同采样口径使这两个数字不能直接解释为CLI引起的回归；LITE-04及06做固定频率/ROI/模型线程的隔离剖析。该项作为性能追踪，而非现阶段硬阻断。
2. **人工输入法：** 已有ConPTY半行输入重绘和人工PowerShell基本命令证据；中文IME候选窗、退格及闪屏尚无明确人工确认，不能写成全通过。LITE-04用户试玩时补录。
3. **原生稳定性：** 历史旧Vision/OpenCV access violation未归因；LITE-02的12轮混合进程稳定测试仍是既有证据。Maa native长期卡死无法安全杀死单个线程，仍以保守退出为原则。
4. **可支持范围：** 当前内置实际测试插件为fixture，只验证 Windows11/Python3.14.7/Edge158/maafw5.16.1。Quiz双点击、10s轮次和分数结算、WebGL雀魂尚属LITE-04/05。

## 4. 后续

进入 **LITE-04**，先形成 Quiz业务状态与两步动作协议设计（每步新观察/唯一目标/回合防ABA），再实现受控网页、真实Maa视觉插件、CLI多轮交互和计时/结算/故障矩阵；沿用现有Coordinator与CLI，不重造Runtime。

**结论：LITE-03 Accepted。**
