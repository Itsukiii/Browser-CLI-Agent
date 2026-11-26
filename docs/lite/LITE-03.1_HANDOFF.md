# LITE-03.1 启动、配置与安装入口

基线lite@ed24468，LITE-02整体已Accepted。本子阶段为CLI启动基础，不宣称终端交互已验收。

- `cli.py`/`__main__.py`与console script提供`bca-lite`、`python -m bca.lite`。
- `cli_config.py`：扁平TOML、未知字段拒绝、正有限数校验、loopback endpoint；CLI覆盖TOML，配置文件内路径相对文件目录、CLI路径相对cwd。不自动搜索配置。
- `--list-targets`不绑定、不启动Maa，显示完整ID/type/host，省略title/URL路径与query；`--target`只按精确ID匹配，无候选时失败，不兜底其他页面。
- 当前明确支持已安装的内置`fixture`插件，不扫描目录/执行任意模块；使用wheel内Bundle，OCR model/manifest必须同时显式指定并校验。没有引入PluginManager。
- `--check`离线验证资源；`--once`新截图后退出；`--create-fixture`才创建自有页并设640×400/DPR1，原有页面不改配置、不关闭。交互选择在03.2补充。
- require_authorization=True且唯一Coordinator。完整close共享shield排空；stop失败最多追加2次close尝试，仍不释放或Destroy不确定时保留依赖，CLI在CDP loop仍活时exit3终止进程，不调用未知指针析构。不是强杀正在执行的native job，job.wait无界风险仍保留。

证据`docs/evidence/LITE-03/03.1/`：配置/入口24 passed；mypy105源码文件、Ruff、build；从系统Temp目录运行独立已安装环境的bca-lite --help/--check，model来自明确外部目录。构建/install命令同02.3，安装仅替换本项目wheel，复用已干净安装依赖环境；不冒称重新下载所有依赖。

样例`configs/lite.example.toml`。03.1仅启动路径，03.2继续可编辑输入、状态增量显示和安全命令；03.3实测Windows/Edge终端。CPU约3.26核与历史OpenCV异常未归因仍按LITE-02验收记录保留。阶段源码SHA见该文档所在Git提交；不更新README/总纲验收状态。
