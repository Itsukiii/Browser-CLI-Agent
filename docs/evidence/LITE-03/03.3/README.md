# LITE-03.3 原始证据

报告与复现：`docs/lite/LITE-03_HANDOFF.md`、`docs/lite/CLI.md`。

- `final-pty/`：7项ConPTY/真实Edge与故障验证，通过。`data/*/transcript.txt`保留终端控制流，report.json保存可读transcript、DOM oracle、命令及退出结果。
- `clean-pty/`：全新venv安装完整[lite]依赖，从系统Temp cwd运行已安装CLI；6项通过，包括显式Target交互选择、不关闭既存页。安装环境通过BCA_CLI_PYTHON指定、cwd通过BCA_CLI_CWD指定。
- `expired/`：最终安装wheel过期拒绝，1项通过；位于全量离线之后，未修改之前日志计数。
- `performance-01/`：独立65秒持续观察；production Coordinator由测试launcher只包装start/close记录stats，未改变运行调度。metrics.json真实工作PID用于从process.json过滤CPU/RSS，summary.json为其派生统计。监控149样本实际约0.45s一次，未声称严格0.25s采样。
- `manual-powershell.txt`：用户提供人工操作记录，不是自动采集，不证明未反馈的IME/闪屏行为。
- `offline-final/`：907 passed、66 deselected，包含全部新CLI离线与历史回归；不把历史回归当新链路验收。
- `installation-final.json`：最终源码、最终wheel、干净安装的全部lite文件逐字节一致；final-wheel-help/check/import展示入口及导入保护；pip-check通过。
- `ruff-final.txt`、`mypy-final.txt`、`format-final.txt`、`build-final.txt`；最后只增加浏览器过期测试后补做`resume-ruff.txt/resume-format.txt`。

失败保留：`pty-01/`的Target已关闭后再次closeTarget导致退出2，其他3组通过；修复后`pty-02/`5项通过。`fault-01/`初始2项故障通过。`offline/`906通过/1失败，原因__main__导入即运行argparse，标准main guard后offline-final通过。旧installation.json对应修订前wheel，最终使用installation-final.json，不覆盖失败/旧快照。

进程监控复用02.3的`tests.lite.stability_probe`，每个process.json包含完整命令、cwd、起止时间、进程树/隔离Edge、退出码和原始资源采样。CLI测试配置使用仓库`configs/lite.example.toml`的显式模型/manifest，未自动下载模型。应用无pywinpty依赖；测试机单独安装pywinpty3.1.2。

性能复算：按`performance-01/data/performance/metrics.json.pid`从所有sample.processes筛选，CPU=(末cpu_seconds-首cpu_seconds)/(末monotonic-首monotonic)*100；RSS/PrivateBytes取该PID最大值；Hz=stats.valid/duration。原始测试期间存在构建/安装活动，不能当作无其他负载的跨阶段对照。
