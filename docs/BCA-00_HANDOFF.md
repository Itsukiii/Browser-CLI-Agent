# BCA-00 增量完善与阶段验收交接

日期：2026-11-12。基线：**browser-cli-agent 0.2.0 / Protocol 2**。本轮按已确定的**方案 A：Python 内部类型契约优先**完善首次成果，未重新初始化工程。

## 1. 完成状态与依据

依据 `docs/md/BCA_PROJECT_CONTEXT.md`、`BCA-00_Protocol.md`、原始初始化需求和增量验收提示词。两份共享文件在本轮由用户补充，已阅读并纳入任务地图与验收。需求来源文件保留其规划/任务定义，不将其“待开始”文字用作当前实现状态；当前状态以本交接为准。

本轮完成：标准库模型迁移、显式 JSON codec、编码截图边界、Provider 错误分类和只读查询端口、插件单一状态发布主路径、扩展测试及实际文档。真实 Browser/Runtime/Plugin Manager/Vision/CLI/Majsoul 不属于 BCA-00，不宣称已实现。

**验收结论：BCA-00 本轮代码、文档与本机工程验收通过，可作为 BCA-01～07 接入基线。** 运行证据限于 Windows / Python 3.14.7；Python 3.12/3.13 运行矩阵与 Git 仓库状态明确列为未验证/未建立项，不计作已完成。

仓库检查：当前路径 D:\Project\BCA；`git status --short` 返回 “not a git repository”。因此无法提供 Git diff/提交或确认版本控制状态；本报告按实际文件逐项列出修改。未发现 AGENTS.md 或并发开发进程指示，保留现有 src 布局和目录职责。

首次差距及修正：Pydantic 不符合方案 A → 移除运行时依赖并改 dataclass；Frame 默认整帧 JSON 边界不明确 → 默认仅元数据；裸 RGB/RGBA 与编码截图约定不符 → 限定 PNG/JPEG；缺失/不可用异常混淆 → 增加子类；Context 绑定 Registry → 改为 ProviderLookup；状态推送/拉取混用 → 固定 Runtime 拉取并单次发布；后续计划缺少编号 → 对齐 BCA-01～07。

## 2. 相较首次交付的文件变更

新增：

- `src/bca/core/protocol/validation.py`：JSON 类型别名及基础入口校验。
- `src/bca/core/protocol/codec.py`：显式、可测试的字典/JSON 编解码。
- `tests/core/test_protocol_incremental.py`：增量验收测试。
- `tests/app/package_smoke.py`：无第三方依赖环境中的 wheel 验收脚本。
- `docs/BCA-00_HANDOFF.md`：本交接报告。

修改：

- `pyproject.toml`、`src/bca/__init__.py`：包 0.2.0，运行依赖清空，移除 Pydantic mypy 插件。
- `src/bca/core/protocol/models.py`、`__init__.py`：标准库冻结模型、协议 2、公开 codec/类型别名。
- `src/bca/core/errors.py`：ValidationError/SerializationError、缺失能力与类型不符分类。
- `src/bca/core/providers/registry.py`、`__init__.py`：ProviderLookup 和分类查询错误。
- `src/bca/core/plugins/__init__.py`：元信息/配置 dataclass，Context 依赖只读 Protocol。
- `plugins/example/__init__.py`：原生类型构造动作、版本更新，无 Pydantic API。
- `tests/conftest.py`、`tests/core/test_protocol.py`：编码帧 fixture 与新模型/codec 调用。
- `tests/core/test_dependencies.py`：验证 Protocol 只依赖标准库和公共错误、无反向依赖及循环。
- `tests/app/test_foundation.py`：检查全部公开导出。
- `README.md`、`docs/ARCHITECTURE.md`、`INTERFACES.md`、`PLUGIN_SPEC.md`、`DEVELOPMENT_PLAN.md`：同步当前代码、例子、约定和后续阶段。
- `docs/BCA-00_REPORT.md`：添加历史标记，保留首次报告证据。

Provider ABC、StateSink/EventSink、日志配置及默认 TOML 的合理既有设计保留。用户本轮添加的两份共享需求文件不计为代理新增实现。`.venv`、缓存、egg-info、dist 均为忽略的本地验证产物。

## 3. 公共接口定稿清单

准确字段类型、默认值、校验与完整参数表见 [INTERFACES.md](INTERFACES.md)，均可由下列入口直接导入：

| 入口 | 公开接口与语义 |
| --- | --- |
| `bca` | `__version__="0.2.0"` |
| `bca.core.protocol` | `PROTOCOL_VERSION=2`；`Model`、`Viewport`、`Frame`、`PageState`、`Command`、`Action`、`ActionResult`、`ErrorDetail`、`Event`：冻结、关键字参数 dataclass；`JsonValue/JsonObject` 类型别名 |
| `bca.core.protocol` | `ImageFormat`、`CoordinateSpace`、`RecognitionStatus`、`ActionType`、`MouseButton`、`ActionStatus`：StrEnum，构造器要求实例 |
| `bca.core.protocol` | `to_dict(model: Model, *, include_frame_data=False) -> JsonObject`；`to_json(...) -> str`；`from_dict(model_type: type[M], data: JsonObject) -> M`；`from_json(model_type: type[M], text: str) -> M`；只在外部边界使用 |
| `bca.core.providers` | `Provider` 的 available/capability、async start/close；`CaptureProvider.capture(page_id: str) -> Frame`、`InputProvider.execute(action: Action) -> ActionResult` 均 async |
| `bca.core.providers` | `ProviderLookup` Protocol：get(str)->Provider / get(type[P])->P、available(str或类型)->bool；`ProviderRegistry` 实现它并提供 register(provider)->None、capabilities 属性 |
| `bca.core.runtime` | `StateSink.publish(state: PageState) -> None`、`EventSink.emit(event: Event) -> None`：异步背压端口 |
| `bca.core.plugins` | `PluginMetadata(*, plugin_id, version, required_capabilities=(), protocol_version=2)`；`PluginConfig(*, values={}, protocol_version=2)`；`PluginContext(providers: ProviderLookup, states: StateSink, events: EventSink, logger: Logger, config: PluginConfig)` |
| `bca.core.plugins` | `Plugin` Protocol：metadata；async initialize(context)、start、observe()->PageState、handle_command(Command)->tuple[Action,...]、stop、close；同步 parse_command(text, *, source="cli")->Command、format_state(PageState)->str |
| `bca.plugin_sdk.interfaces` | 重导出 Plugin、PluginMetadata、PluginConfig、PluginContext，不重复定义 |
| `bca.core.errors` | BCAError、ValidationError、SerializationError、CapabilityUnavailableError、CapabilityNotFoundError、CapabilityTypeError、ProviderRegistrationError、ProviderError、PluginError、CommandError、LifecycleError |
| `bca.app.logging` | `configure_logging(level: str="INFO") -> None`，显式配置，不在 import 时执行 |

## 4. 关键约定及兼容影响

- 内部按 Python 类型传递，不自动统一成 JSON Schema；外壳冻结、载荷浅层引用，默认容器独立。发布后不得修改原数据引用。codec 产生独立 JSON 快照。
- Frame 持有编码 PNG/JPEG bytes 原引用，跨 await 可持有 Frame，禁止复用可变存储。签名检查不替代图像解码/完整性检查。
- 鼠标标准为 CSS viewport，截图坐标按两个轴的 capture 尺寸比与裁剪偏移转换；不重复使用 DPR，不加文档滚动偏移。
- 默认 UTC、带时区 datetime、JSON 微秒精度；状态 sequence 与 schema_version 分离。耗时与超时用单调时钟，墙上时间不定义事件顺序。
- I/O 和生命周期异步；查询/解析/格式化同步。依次 await 的动作有序，并发调度由调用方管理；取消传播、部分失败显式报告，不自动重放。
- 标准状态路径为 Runtime 调用 observe 后 publish 一次；插件在 observe 内不重复发布。推送模式尚未标准化。
- 默认序列化 Frame 元数据；完整 bytes 需 include_frame_data=True 明确 Base64，约增加 1/3 体积。JSON 不能序列化 Context/Provider。
- **破坏性迁移**：移除 Pydantic model_validate/model_dump 系列 API；字符串枚举/时间自动转换移至显式 codec；裸 RGB8/RGBA8 Frame 移除；异常改用 BCA 自身类型。因此从 0.1.0/协议 1 升到 0.2.0/协议 2。旧载荷不自动迁移，禁止只改版本号冒充新协议。
- 缺失/类型不符异常仍属于 CapabilityUnavailableError 子类，兼容旧宽泛捕获，同时允许精确分类。

## 5. 验收命令及实际结果

本机 Windows、Python 3.14.7；`.venv` 为开发环境。当前实际记录：

| 命令（根目录） | 结果 |
| --- | --- |
| `git status --short` | 非 Git 仓库，版本控制检查不可用 |
| `.venv\Scripts\python.exe -m pip install -e ".[dev]"` | 成功安装 0.2.0，替换首次 0.1.0 |
| `.venv\Scripts\python.exe -m pytest` | **82 passed，0 failed**，包括首次 54 项迁移及新增 28 项 |
| `.venv\Scripts\python.exe -m mypy` | strict 通过，21 个源码文件 |
| `.venv\Scripts\python.exe -m ruff check src plugins tests` | 通过 |
| `.venv\Scripts\python.exe -m ruff check .` | 根目录完整检查通过 |
| `.venv\Scripts\python.exe -m ruff format --check .` | 通过，45 个文件已格式化（包括文档示例） |
| `.venv\Scripts\python.exe -m pip check` | 无依赖冲突 |
| `.venv\Scripts\python.exe -m build` | 隔离构建成功：`dist/browser_cli_agent-0.2.0.tar.gz`、`dist/browser_cli_agent-0.2.0-py3-none-any.whl` |
| `.venv\Scripts\python.exe -m venv .venv/acceptance` | 创建全新验收环境，不继承开发环境的 Pydantic |
| `.venv\acceptance\Scripts\python.exe -m pip install --no-index dist/browser_cli_agent-0.2.0-py3-none-any.whl` | 离线安装成功，无第三方运行依赖 |
| `.venv\acceptance\Scripts\python.exe -I tests/app/package_smoke.py` | 通过：从新环境 site-packages 加载 19 个子模块；全部导出、py.typed、Frame 元数据/完整 Base64 和 Action 往返通过；确认找不到 Pydantic |
| `.venv\acceptance\Scripts\python.exe -m pip check` | 无依赖冲突 |

额外静态检查：21 个源码文件通过 `ast.parse(..., feature_version=(3,12))` 语法解析；源码发行包实际检查包含 handoff、两份共享需求、配置、示例与验收脚本。语法检查不等同于 Python 3.12 运行验证。首次 0.1.0 产物可能仍在 dist，使用者应明确选择 0.2.0 文件。

本轮修正后没有测试失败。开发中遇到的类型检查提示、Ruff 格式提示均已修复；最后一次项目 pytest 为 82/0。全新环境脚本是独立安装冒烟验收，未宣称在该无 pytest 环境中重新执行全部单测。

覆盖六模型有效/非法字段、全部七种动作正反例、独立默认值、非等比/裁剪/DPR 映射、二进制共享、元数据边界、时区微秒与嵌套 codec、非法 JSON、能力分类/关闭、Provider 顺序/取消/可预期失败、插件完整 fake 流程、导入/层次/循环。

Python 3.12/3.13 实际运行矩阵、真实图像解码、真实浏览器和 CLI 集成未验证；本轮不将静态 3.12 配置等同于实际运行。

## 6. 后续开发接入

| 阶段 | 必须遵守 |
| --- | --- |
| BCA-01 Browser | 编码截图及准确 CSS capture 元数据；Input 的参数/能力/执行失败分类；取消后输入状态清理 |
| BCA-02 Runtime | 单次状态发布、Sink 背压、序号检查、同页串行与首错停止、单调超时、先停止在途任务再释放 Provider |
| BCA-03 Plugin System | 声明能力与版本检查、ProviderLookup 注入、初始化失败清理、实例级状态 sequence 与版本协商 |
| BCA-04 Vision & Assets | 按需解码、图像完整性检查、载荷只读、截图点通过 Frame 转 CSS；资源 schema 留在 SDK/插件 |
| BCA-05 CLI | Command 规范化、插件格式化、显式 codec 和日志；TOML 加载及异步终端实现仍待开发 |
| BCA-06 Majsoul | 独立 schema_version、真实帧关联、未知/部分识别诊断、业务映射在插件侧 |
| BCA-07 Integration | 真实后端全链路、断线/背压/取消/输入释放、单调计时性能和 Python 版本矩阵 |

## 7. 协调事项

本轮方案 A 的破坏性调整必须随本交接同步后续子系统，不能继续引用首次 Pydantic 接口。共享总纲架构方向未改变。Browser 后端细节、队列策略、插件发现/版本协商、截图新鲜度、跨进程传图和推送模式仍由对应阶段确定，不阻塞 BCA-00 公共契约。Git 初始化/提交状态尚未建立，不声称完成版本控制交付。
