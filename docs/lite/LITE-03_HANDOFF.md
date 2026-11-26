# LITE-03 Interactive CLI 交接

日期2026-11-26。基线`lite@ed24468`，LITE-02正式Accepted后实施；本报告提交架构复核，**不自行宣布LITE-03 Accepted**。

## 子阶段与接口

- 03.1 `bdd3f8a`：console script与模块入口、严格TOML/CLI优先级、显式Target ID、离线资源验证、内置fixture，见`LITE-03.1_HANDOFF.md`。
- 03.2 `f9fef05`：prompt_toolkit异步可编辑输入、增量输出、忙时拒绝、stop/resume/新截图查询、完整退出，见`LITE-03.2_HANDOFF.md`。
- 03.3：真实Windows ConPTY/Edge、干净wheel、故障与性能测量，以及本阶段发现的入口导入和Target收尾修复；源码/证据提交`b62d57b`。

使用说明`docs/lite/CLI.md`，样例`configs/lite.example.toml`。安装`[lite]`新增prompt-toolkit>=3.0.51,<4，实测3.0.53；pywinpty3.1.2仅测试工具，不是应用依赖。

新增模块：`cli_config.py`配置/参数、`cli.py`进程入口、`cli_session.py`Application所有权、`terminal.py`受保护输入输出、`interactive.py`命令路由与变化提示。没有引入旧Runtime、插件发现器或任务框架。已有Bridge/Facade/Coordinator接口未改。

## 安全、交互和退出语义

1. 只支持显式安装的内置fixture；完整Target ID或终端输入完整ID，无默选、模糊标题匹配/失效兜底。创建测试页必须`--create-fixture`；现有用户页面不改尺寸、不关闭。
2. 模型/manifest显式给出并校验来源/SHA256；包内Bundle的as_file作用域持续到native释放。默认ROI，上半图模板/下半图OCR，不能把fixture当作通用页面识别插件。
3. 唯一Coordinator执行业务观察与命令，require_authorization=True，?始终新截图。单条命令在途，忙时明确拒绝、不排队；退出/help可响应，1024字符提交限制。
4. prompt_toolkit同一Application保护可编辑行；background输出使用独立AppSession，控制符转义。变化通知有界合并，只显示业务内容改变；显式命令结果独立输出，可能与一次状态通知包含相同内容，不是周期重复刷屏。
5. Python诊断通过最多16条deque经renderer显示，满时丢最旧诊断，不丢命令结果。固定Maa5.16.1的Tasker.set_stdout_level(Off)防止native直接写终端，normalized ERROR/unknown/CloseReport仍显示。CLI进程全局设置，不改SDK默认行为。
6. Ctrl+C/EOF/quit取消在途命令并等待native排空，不承诺动作未发生、不得据此重放。外部SIGINT只请求一次取消，重复信号不能绕过清理。
7. Coordinator close后核对released/errors；stop失败最多额外2次close，未确认释放或Destroy隔离时保留全部依赖并在CDP loop还活时os._exit(3)，避免析构重试未知指针。该终止只作用CLI自己的进程；遗留的自建页需要显式清理。不能强杀job.wait线程，永久native卡死仍可能阻止退出。
8. native已释放后，Provider个别错误不阻止剩余清理；只关闭仍存在的自建Target，Session最终关闭。正常exit0，普通错误2，未释放3，外部SIGINT取消130；prompt内Ctrl+C正常安全退出。

## Windows / Edge 实测

平台Windows11/Python3.14.7/Edge158/Maa5.16.1。原始目录`docs/evidence/LITE-03/03.3/`。

| 证据 | 实际内容 |
| --- | --- |
| final-pty | **7 passed / 32.36s**：正常退出、Ctrl+C、EOF、Target丢失、非TTY拒绝；另stop_failed和native pre-click-failure注入 |
| clean-pty | **6 passed / 23.93s**：全新venv安装的wheel，在系统Temp cwd以ConPTY运行上述4种退出路径、无TTY拒绝、交互完整ID选择且原有页保留 |
| 部分输入与重绘 | 输入`click 45`后不提交，测试通过DOM仅作刺激将可见回合变为456；后台显示456后补`6`，Maa唯一候选点击，DOM命中button、round456，视觉后置457 |
| 命令限制 | 旧回合拒绝、重复stop/resume、目标消失NOT_FOUND/双候选AMBIGUOUS/恢复、中文非法命令、1030字符超长、批量粘贴Busy，实际输入次数不增加 |
| unknown注入 | 真实Maa组合中替换post_click Job为回调前失败；显示unknown，后续click拒绝，DOM hits=[]；不是新增真实网络ACK丢失实验，底层相应证据沿用已验收阶段 |
| stop_failed注入 | 真实native创建后模拟close返回未释放；CLI打印released=False并exit3，未打印CDP closed，自建Target保留；测试宿主在进程结束后明确清理该自建页，不把它当正常释放 |
| expired补测 | 最终干净wheel设置max_frame_age=1微秒，实际截图识别后显示expired=True、点击拒绝、DOM hits=[]、释放成功；**1 passed**。该新增浏览器用例在全量离线运行后单独验证，不篡改原日志的66 deselected计数 |
| 正常清理 | released=True/errors=()、pending=0/reader=False，所有正常测试自建页消失；交互选择的既存页仍保留，无Target切换 |
| manual-powershell.txt | **用户提供**实测：click123→124；旧123拒绝；click124→125；三次?具有三个不同frame ID；quit完整释放。此记录并非自动录制，不包含IME候选窗/退格/闪屏的明确确认 |

测试用ConPTY实际启动生产CLI进程，不用仅打印替代可编辑行；离线pipe_input测试同时直接检查buffer保持。CLI不会把DOM暴露给插件；DOM仅由测试进程作为刺激/oracle。

## 性能与历史风险

`performance-01`：CLI周期0.75s、raw/ROI开启、原生模型与LITE-02相同；静态页连续观察65秒，实际Coordinator存活66.1624s，**87/87有效，1.31495Hz**，0 skipped/0 dropped，同内容State输出恰好1次，退出released=True。

逐PID监控从进程树定位实际CLI工作PID17608（不是venv启动器），149次样本跨度66.0311s：

- CPU累计差/单调时间=**397.02%单核基准，约3.97逻辑核**。
- 峰值RSS=160800768 bytes（153.35MiB），PrivateBytes=641220608 bytes（611.52MiB）。
- 原始process.json含测试/CLI/隔离Edge进程树、系统可用内存和commit；`summary.json`使用metrics.json中的PID过滤后计算。
- 同时有构建/干净安装活动，且时长/进程统计边界与LITE-02不同，不推断CLI导致性能退化或改善。**未实现降CPU目标，仍交LITE-06治理**。LITE-02约3.26核记录继续有效，未隐去。
- 旧OpenCV4096² access violation仍未归因，未在本阶段重做那12轮矩阵；全量离线回归包含旧代码但不能替代独立混合进程归因。原始02.1/02.3证据保留，无“已修复”声明。

## 测试与失败记录

- 03.1：24 passed，mypy105文件，Ruff/build与异cwd安装入口检查。
- 03.2：50 passed（终端/配置、点击可靠性、Coordinator生命周期），mypy107文件。
- 03.3最终全量离线 **907 passed / 66 deselected / 57.06s**；mypy strict107文件、Ruff、284文件格式检查、wheel/sdist通过；干净venv完整安装[lite]及pip check通过，CLI代码从site-packages加载。
- `pty-01`：3通过、Target丢失组因重复关闭已不存在页返回2；修复检查后pty-02全部5通过。保留失败原文。
- `offline`：906通过、1失败；导入所有包时`__main__`无保护执行argparse。加标准main guard后重跑，失败不删除。

## 复现与边界

```powershell
$env:BCA_CDP_ENDPOINT='http://127.0.0.1:9341'
$env:BCA_CLI_EVIDENCE='NEW_OUTPUT/data'
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe -m tests.lite.stability_probe NEW_OUTPUT -- .venv/Scripts/python.exe -m pytest tests/lite/test_real_cli.py -q
# 性能单独进程设置 BCA_CLI_LONG=1，-k observation_cost。
# 安装环境：BCA_CLI_PYTHON为新venv解释器绝对路径，BCA_CLI_CWD为系统Temp，
# 使用 -k 'editable or non_tty or selection'，fault测试替身模块需要仓库cwd。
$env:BCA_OCR_MODEL=(Resolve-Path .maa-models/ppocr-v3-en).Path
.venv/Scripts/python.exe -m pytest -m 'not browser_integration' -q
```

需测试依赖`pywinpty>=3,<4`（本机手工安装，仅Windows）；不在普通import下载组件或模型。每次新输出目录避免覆盖失败证据。完整命令/工作目录/起止/PID/退出码在对应process.json。

未覆盖：人类中文IME候选窗口/具体PowerShell字体下闪屏反馈、其他操作系统、Python3.12/3.13、多小时内存、WebGL雀魂、CLI退出期间永久native卡死。没有扩大正式阶段验收边界。

仅在lite分阶段提交，无push/main变更。README/BCA_PROJECT_CONTEXT仍保持LITE-03未Accepted，等待架构主会话复核。
