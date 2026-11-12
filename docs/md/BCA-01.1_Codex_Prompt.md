# BCA-01.1 — CDP Transport & Target Session

> **执行对象：** Codex  
> **项目根目录：** `bca/`（在现有统一仓库中开发）  
> **任务编号：** BCA-01.1  
> **所属子系统：** BCA-01 / Browser  
> **当前基线：** `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> **语言及环境：** Python 3.12+；优先 Windows，Chromium / Microsoft Edge

## 一、任务目标

为 BCA 实现可靠、可测试的原生异步 CDP（Chrome DevTools Protocol）连接层及浏览器页面会话管理能力，使上层能够连接用户已经启动并开放本机调试端口的 Chromium / Edge，枚举页面，显式选择并绑定目标页面，管理 Target/Session 生命周期，并准确报告连接和绑定状态。

本阶段重点完成 **CDP Transport、Target Discovery、Target Binding、BrowserSession** 四项基础能力。后续 BCA-01.2 截图、BCA-01.3 输入及 Provider 具体实现将复用本阶段成果。

本阶段的三个已确定技术选择：

1. 通过原生异步 **CDP over WebSocket** 通信，使用成熟的异步 WebSocket 客户端库作为传输依赖。
2. **显式 Target 选择与绑定**：先列出页面，由调用方传入明确 `target_id` 后绑定。
3. 截图由后续 Capture Provider **按需采集，Runtime 负责调度**；本阶段为该调用链建立稳定的会话基础。

## 二、开发前必须核验的现有仓库

先进入现有 `bca/` 仓库，阅读并核对以下内容，不以任务提示词中的示例签名覆盖仓库事实：

- `BCA_PROJECT_CONTEXT.md`、`BCA-00_MAIN_SYNC.md`、`BCA-01_Browser.md`（如在工作区可访问）
- `docs/INTERFACES.md`
- `docs/PLUGIN_SPEC.md`
- `docs/ARCHITECTURE.md`
- `src/bca/core/protocol/`
- `src/bca/core/providers/`
- `src/bca/core/errors.py` 或现有错误定义所在位置
- `pyproject.toml`、相关既有测试

已知交接基线：公共模型为冻结、关键字初始化的标准库 dataclass，Provider 具有异步 `start()/close()` 和只读 `available`；`CaptureProvider.capture(page_id) -> Frame`、`InputProvider.execute(action) -> ActionResult`；`ProviderRegistry` 仅注册与查询能力，不管理 Provider 生命周期。最终实现必须以仓库中的实际定义为准。

保留 `PROTOCOL_VERSION=2` 和现有公共 API。若确有跨模块协议调整需求，**记录设计理由、影响范围和建议变更**，提交架构主会话协调后再实施。

## 三、实现范围与模块职责

在 `src/bca/core/browser/` 中实现相互解耦的组件。文件命名可按现有仓库风格适度调整，建议如下：

```text
src/bca/core/browser/
├── __init__.py       # 本子系统稳定的公开导出
├── connection.py     # CDP WebSocket 传输、请求匹配、事件分发
├── targets.py        # Target 发现和页面描述
├── session.py        # BrowserSession、绑定状态及生命周期
├── models.py         # BrowserTarget、会话状态等内部类型
└── errors.py         # 浏览器专属异常及与 Core 异常的关系
```

### 3.1 CDPConnection

实现单个 WebSocket 长连接的异步 CDP 客户端，职责包括：

- 接收本机 CDP HTTP 端点（例如 `http://127.0.0.1:9222`），通过 `/json/version` 发现 browser-level `webSocketDebuggerUrl`；明确连接和 HTTP/WebSocket 超时。
- 在一个常驻 Reader 任务中收取全部 CDP 消息。
- 每个请求分配唯一递增的 `id`，通过 `id -> asyncio.Future` 匹配异步响应。
- 支持同时挂起多个 CDP 请求及乱序返回；以发送锁保护消息发送边界与编号状态。
- 支持 CDP flattened session：当调用特定 Target Session 的命令时，在消息顶层携带 `sessionId`。
- 区分带 `id` 的响应和带 `method` 的异步事件；可按事件名及 Session 注册/注销处理器，并隔离处理器异常，避免单个回调终止 Reader。
- CDP 返回 `error` 时提供包含 method、CDP code、message 的可诊断异常；清理 Future。
- 支持每次请求的超时和协程取消；移除对应 pending 项，安全丢弃迟到响应。
- WebSocket 断连时只进行一次统一失效处理，通知上层并结束全部 pending 请求；关闭过程应停止 Reader、释放 socket 和事件订阅资源。
- `connect()` 与 `close()` 遵守明确的生命周期约定，`close()` 幂等，并能处理部分初始化失败。
- 避免在网络回调持有内部锁时调用任意外部用户回调，避免死锁与重入问题。

推荐内部接口草案（根据实际实现可细化）：

```python
class CDPConnection:
    async def connect(self, endpoint: str) -> None: ...

    async def send(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, object]: ...

    async def close(self) -> None: ...
```

请求的超时使用单调时钟相关机制；日志打印请求 ID、method、Session、耗时和错误类别，不记录敏感字段或大型消息负载。

### 3.2 TargetManager 与页面发现

通过 browser-level Session 的 `Target.getTargets` 枚举 Target，对 `type == "page"` 的目标建立稳定的页面描述对象。至少包含：

- `target_id`
- `title`
- `url`
- `type`

提供 `list_targets()` 和 `bind(target_id)` 的明确接口。目标选择由调用方显式给定 Target ID；对已经不存在、非页面类型或不可 attach 的 Target 给出明确错误。

推荐使用 `Target.attachToTarget` 并设置 `flatten=true`，保存返回的 CDP `sessionId`。`target_id` 是浏览器 Target 标识；CDP `sessionId` 表示一次 attach 会话，连接重建或重新 attach 后会变化。首版可将 BCA 的 `page_id` 定义为绑定 Target 的 `target_id`，并在文档中固定该映射。

支持监听和处理与当前绑定 Target 相关的 `Target.targetInfoChanged`、`Target.targetDestroyed`、`Target.detachedFromTarget` 等事件；导航通常保持 Target 绑定，必要时刷新页面信息。对事件语义与实际 CDP 行为进行测试。

### 3.3 BrowserSession

`BrowserSession` 是 BCA-01 的共享浏览器会话对象，拥有 `CDPConnection`，维护当前绑定的 Target、CDP sessionId 及可观测状态。建议提供：

```python
class BrowserSession:
    async def connect(self) -> None: ...
    async def list_targets(self) -> tuple[BrowserTarget, ...]: ...
    async def bind(self, target_id: str) -> None: ...
    async def unbind(self) -> None: ...
    async def close(self) -> None: ...
```

并提供只读状态，例如 `connected`、`is_ready`、`bound_target`、`page_id`、`session_id`，以及一个内部递增的 `generation`。实际类型及公开属性由本阶段定稿。

生命周期建议：

```text
DISCONNECTED -> CONNECTED -> BOUND
                      ^          |
                      |          v
                      +------ UNBOUND

断线/Target 消失 -> 失效并报告错误 -> 调用方触发恢复或重新绑定
close() -> CLOSED
```

行为要求：

- 连接成功后可枚举页面；绑定成功后才进入 `is_ready=True`。
- 同一会话同一时刻只维护一个当前绑定页面。
- 重复绑定同一有效 Target 时行为明确且幂等；切换到另一 Target 时先安全解除旧绑定，再绑定新目标。
- 页面导航更新 Target 信息，普通导航不应错误地视为 Target 丢失。
- 当前 Target 被关闭、detach 或底层 WebSocket 断开时，立即将当前绑定状态失效，更新 `generation`，不再允许新的页面操作。
- 每次成功重新绑定或重建连接时更新 `generation`，为后续 Capture/Input 识别过期操作提供依据。
- 重新连接时重新获取 Target 信息，核验原 Target 是否仍存在；恢复连接后不应默默绑定其他页面。
- 与浏览器连接和解绑相关的清理应当可以重复调用。
- BrowserSession 拥有底层连接的关闭权，未来 Capture/Input Provider 只借用 Session 引用；其关闭操作不应互相关闭共享 Session。
- 对并发 `connect/bind/unbind/close` 进行必要的状态串行化，避免 attach/detach 竞态。

对于断线恢复，本阶段实现可由调用方触发的明确恢复路径和必要清理，不要求在后台永久自动重试；应记录恢复后的 Target 重新确认规则。

### 3.4 错误模型和诊断

统一利用 `bca.core.errors` 的现有异常体系，对网络连接失败、CDP 协议错误、目标不存在/不再有效、attach/detach 失败、生命周期非法及超时设置可辨识的错误类型或包装层。浏览器内部自定义异常应与 Core 错误约定兼容，清晰保留因果链 `raise ... from ...`。

建议日志涵盖：连接建立/关闭、Target 发现、attach/detach、断线、Session 失效、异常与超时。必要时暴露可只读获取的会话诊断状态，供后续 CLI 和 Runtime 使用。

## 四、依赖与工程要求

- 在现有 `pyproject.toml` 中加入最少必要的运行时依赖，推荐使用 `websockets`，并按 Python 3.12+ 和实际 API 选择兼容版本范围。
- 维护现有 mypy strict、Ruff 和 pytest 工程约定。
- 网络 I/O 全部走 asyncio；避免阻塞事件循环。
- 浏览器调试端点仅面向用户明确配置的本机地址；HTTP 发现阶段验证实际连接地址，避免任意远端或不受信任的 WebSocket 地址被静默接受。保留将来扩展的设计空间。
- 使用 Python 类型注解，定义清晰的可复用内部模型；与 Protocol 2 保持类型一致。
- 保证模块导入不会连接浏览器或产生运行时副作用。

## 五、测试与验收

编写可稳定重复运行的单元测试，并在具备测试浏览器时执行真实 CDP 集成测试。至少覆盖：

1. 正常连接与 `/json/version` 端点解析。
2. CDP 多请求并发、请求 ID 匹配、乱序响应、事件分发。
3. CDP 错误响应、超时、取消、迟到响应和断连清理。
4. Target 枚举与过滤，显式绑定、重复绑定、解绑和目标切换。
5. 页面导航、关闭与 detach 导致的状态变化。
6. 并发生命周期调用、部分初始化失败和重复 close。
7. 重新连接后 Target 与 Session ID 重新核验，避免误绑定。
8. `generation` 在连接或绑定变化时按约定更新。

建议加入本地 mock HTTP/WebSocket CDP Server，避免核心单元测试依赖浏览器或外部网络。真实浏览器测试使用单独标记或明确的启动说明。

真实浏览器验收至少应能：

- 使用 Chromium/Edge 的本机调试端口建立连接。
- 枚举两个测试标签页，看到不同的 Target ID、标题和 URL。
- 显式绑定其中一个页面，读取正确的 Session 标识。
- 页面导航后保持合理绑定状态；关闭已绑定页面后准确失效。
- 执行关闭并确认任务、pending Future 与 WebSocket 资源正常清理。

运行并记录项目现有测试、类型检查和代码检查命令及结果，特别关注是否影响 BCA-00 的现有测试。Python 3.12/3.13/3.14 的实际运行范围应如实列出。

## 六、本阶段交付

完成后提交：

1. 新增及修改的源码、依赖和测试文件。
2. BrowserSession/CDPConnection 的实际公开接口、状态模型、错误和生命周期说明。
3. 使用现有 Chromium/Edge 调试端口进行连接与 Target 绑定的最小运行示例或开发说明。
4. 单元测试、真实浏览器测试、mypy、Ruff 的具体执行命令和结果。
5. 设计决策说明：端点连接方式、flatten session、Target/page_id/session_id 关系、事件处理和恢复策略。
6. 阶段交接报告 `BCA-01.1_HANDOFF.md`，说明完成范围、主要文件、验证结果、遗留问题和后续 BCA-01.2/01.3 需要使用的接口。

本阶段交付以实际代码与测试结果为准；若某项真实浏览器验证受环境限制未运行，应明确标注并给出可复现步骤。后续由 BCA-01 子会话整理最终 `BCA-01_MAIN_SYNC.md`，提交架构主会话。

## 七、执行顺序

1. 核对仓库实际接口与依赖，汇报发现的差异。
2. 落实 CDP 连接与请求/事件分发机制，配套 mock 测试。
3. 实现 Target 发现、显式绑定与 BrowserSession 生命周期。
4. 补充异常、取消、断连恢复和并发测试。
5. 执行真实浏览器验证、完整测试及静态检查。
6. 更新相关开发文档，输出 `BCA-01.1_HANDOFF.md`。

在统一的 `bca/` 项目主目录内直接完成上述开发和验证，并根据实际结果形成交接报告。
