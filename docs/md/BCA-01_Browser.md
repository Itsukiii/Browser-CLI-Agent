# BCA-01 / Browser — 浏览器连接与底层能力

> 任务编号：BCA-01  
> 子会话名称：BCA-01 / Browser  
> 项目根目录：`bca/`  
> 上游共享文件：`BCA_PROJECT_CONTEXT.md`  
> 必要前置成果：`BCA-00_MAIN_SYNC.md`、仓库 `docs/INTERFACES.md` 及 `src/bca/core/protocol/`  
> 状态：BCA-00 阶段性交接已核实；BCA-01 可启动设计与开发流程  
> 版本：v0.2 · 2026-11-12
> 公共协议基线：`browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2`（BCA-00 Codex 阶段报告）

## 1. 背景与任务目标

Browser CLI Agent（BCA）通过浏览器能力接口采集指定网页信息，并将插件产生的操作请求执行至目标页面。本任务负责 Core 中的浏览器接入和底层能力实现，首选 Chromium / Microsoft Edge 的 Chrome DevTools Protocol（CDP）。

实现一个可连接既有浏览器调试会话、选择并绑定指定页面、采集截图、执行标准动作、提供坐标元数据和可观测连接状态的浏览器适配层。

## 2. 阅读顺序与接口权威来源

1. `BCA_PROJECT_CONTEXT.md`：项目目标、整体架构、模块边界和跨会话规则。
2. 本文件：BCA-01 的任务范围与验收条件。
3. `BCA-00_MAIN_SYNC.md`：BCA-00 已交付模型、接口、验证结果和遗留事项。
4. 仓库中的 `docs/INTERFACES.md`、`docs/ARCHITECTURE.md`、`src/bca/core/protocol/`、`src/bca/core/providers/`：实际共享契约。

以仓库中已确认的公共协议为接口依据。进入 Codex 开发前，先核对仓库的实际导出类型、字段和签名。发现公共模型需要调整时，形成变更提案交架构主会话协调。

## 2.1 Protocol 2 实际交接契约

BCA-00 阶段性报告确认以下基线（精确字段与签名必须以仓库源码为准）：

- `bca.core.protocol`：`PROTOCOL_VERSION=2`，`Viewport`、`Frame`、`PageState`、`Command`、`Action`、`ActionResult`、`ErrorDetail`、`Event`；冻结的关键字 `dataclass`、`StrEnum` 和 `JsonValue/JsonObject`。
- `bca.core.providers`：`Provider` 异步生命周期 `start/close`、`CaptureProvider.capture(page_id) -> Frame`、`InputProvider.execute(action) -> ActionResult`、`ProviderLookup`、`ProviderRegistry`。
- `bca.core.errors`：统一错误基类及能力、生命周期、校验等异常类型。
- `Frame` 图像数据为 PNG/JPEG 编码 `bytes`；图片缓冲按不可变共享处理，内部调用使用 Python 对象。
- 输入以 CSS viewport 坐标为基准；截图/裁剪区域到视口的映射使用 Frame 元数据，特别验证 DPR、缩放和裁剪情况。
- 时间戳使用带 UTC 时区的 `datetime`；超时和延迟测量使用单调时钟。
- 测试基线由 Codex 报告为 Windows / Python 3.14.7、pytest 82 passed、mypy strict 和 Ruff 通过；BCA-01 在自己实施后记录实际运行结果。

## 3. 开发责任区

主要负责：

- `src/bca/core/browser/`：CDP 接入、连接管理、页面发现与目标绑定、浏览器适配器。
- `src/bca/core/providers/`：已有 Capture / Input Provider 抽象对应的浏览器具体实现及注册集成。
- `tests/core/browser/` 和必要的 Provider 集成测试。
- `docs/` 中与本模块实现直接相关的使用说明、约定及测试步骤。

遵循单仓库结构，按实际 BCA-00 目录与接口落位。

## 4. 功能需求

### 4.1 浏览器连接与目标选择

- 通过配置的本机 CDP 端点连接 Chromium 系浏览器。
- 枚举可连接页面，提供目标 ID、标题、URL 等基本信息。
- 通过明确的目标选择条件绑定一个指定页面，并维护稳定的会话标识。
- 处理目标页导航、关闭、断开及连接状态变化，向上层报告明确的状态和错误。
- 明确连接生命周期、释放资源和重连策略，便于 Runtime 层调度。

### 4.2 Capture Provider

- 对绑定页面进行完整截图，并返回公共 `Frame` 模型。
- 记录采集时间、图像尺寸、视口和页面坐标相关元数据，以及会话/目标标识。
- 具备按区域采集或规范化区域裁剪的能力，区域坐标语义与公共协议一致。
- 明确截图图像编码、字节缓冲持有方式及失败时的异常语义。
- 设计并尽可能执行后台标签页、Canvas / WebGL 页面截图新鲜度和帧率限制的验证，记录已测范围及数据。

### 4.3 Input Provider

- 接收公共 `Action` 模型，执行鼠标移动、点击、按下/释放、键盘按下/释放及文本输入等标准动作。
- 将截图空间、视口 CSS 像素和 CDP 输入坐标进行可靠映射；统一管理缩放和裁剪偏移。
- 明确顺序、超时、输入失败的反馈和 `ActionResult` 填充方式。
- 操作限定于当前绑定的目标页面，并在目标变化时执行必要的有效性检查。

### 4.4 Provider 与运行状态

- 使浏览器能力可通过 BCA-00 定义的 Provider 机制访问。
- 报告连接、页面绑定、捕获和动作执行中的基本运行状态与诊断信息。
- 采用与 BCA-00 协议一致的异步接口，并提供合理的资源清理流程。

## 5. 关键设计事项

在设计讨论阶段重点确认：

1. CDP 客户端选型和依赖开销；是否采用原生 WebSocket 协议封装。
2. 既有浏览器连接方式、页面发现和绑定后的 Target / Session 生命周期。
3. 页面视口、截图实际像素、设备像素比与裁剪区域的坐标定义。
4. 采集数据格式与复制次数，考虑未来视觉识别的低延迟要求。
5. 截图和输入的超时、失败、断线处理及并发行为。
6. 真实浏览器中如何验证页面截图新鲜度及输入落点准确性。

以轻量、低延迟、通用接口为实现取向。

## 6. 模块关系

- **上游**：BCA-00 提供 `Frame`、`Action`、`ActionResult`、Provider 抽象及异常约定。
- **下游**：BCA-02 Runtime 管理截图调度与事件；BCA-03 Plugin System 向插件提供能力；BCA-05 CLI 管理用户会话；BCA-06 Majsoul 使用截图和输入。
- **公共接口协调**：改动 `core.protocol` 中共享契约应先提交主会话确认。

## 7. 测试与验收

- 公共接口的实际 Capture / Input Provider 实现可以实例化并被获取。
- 能连接测试浏览器、发现并绑定指定页面，获取有效图像及坐标元数据。
- 能在可控制的测试页面执行点击、鼠标与键盘动作，并验证结果。
- 通过不同视口尺寸、缩放比例和区域截图测试坐标映射。
- 覆盖连接失败、目标关闭、截图失败、动作失败和资源释放等情形。
- 输出测试命令、执行结果及测得的截图耗时、输入延迟与必要的运行指标。
- 明确真实浏览器测试与模拟测试分别覆盖的内容。

## 8. 子会话工作方式与交付

1. 先读取共享总纲、BCA-00 同步报告和公共接口实际定义。
2. 汇报已有基础、需确认的技术选择与拟开发模块。
3. 与用户讨论后生成 Codex 可执行的阶段提示词。
4. Codex 在统一 `bca/` 目录开发与测试。
5. 子会话输出 `BCA-01_MAIN_SYNC.md`，供主会话更新总纲和安排后续任务。

### `BCA-01_MAIN_SYNC.md` 建议内容

- 实际完成范围和主要文件路径。
- CDP 连接方式、页面绑定生命周期及公共接口实现模块路径。
- Frame / Action / ActionResult 的实际映射、坐标与异步语义。
- 实测性能数据与测试通过情况。
- 可供 BCA-02、03、05、06 使用的调用约定。
- 公共协议变更建议、未决事项和下一阶段注意事项。

## 9. 当前启动条件

本任务文档用于启动 BCA-01 设计会话。正式 Codex 开发前，子会话应确认 BCA-00 已有可使用的公共协议和测试基础，并在实际仓库核对接口；BCA-00 已按交接摘要达到阶段性交接条件；子会话须以真实仓库接口核对结果作为进入 Codex 开发的直接依据。
