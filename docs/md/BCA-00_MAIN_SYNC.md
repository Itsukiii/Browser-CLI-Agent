# BCA-00 / Protocol — 架构主会话同步摘要

> 日期：2026-11-12  
> 来源：`BCA-00_HANDOFF.md`（Codex 阶段交接报告）  
> 核验范围：依据交接报告整理；本次未独立运行仓库代码与测试。

## 1. 阶段状态

BCA-00 公共协议和工程基线已完成阶段验收，**可供 BCA-01～BCA-07 接入**。当前基线为 **browser-cli-agent 0.2.0 / PROTOCOL_VERSION=2**，采用方案 A：Python 内部类型契约优先（标准库 dataclass / StrEnum / Protocol），外部边界显式 JSON codec。

Codex 报告的本机结果：Windows / Python 3.14.7，pytest **82 passed / 0 failed**；mypy strict、Ruff、打包及离线安装 smoke test 均通过。Python 3.12/3.13 运行矩阵尚未验证。Git 仓库尚未初始化（`git status --short` 返回 not a git repository）。

## 2. 公开接口基线

| 入口 | 当前契约 |
| --- | --- |
| `bca.core.protocol` | `PROTOCOL_VERSION=2`；冻结的关键字 dataclass：`Viewport`、`Frame`、`PageState`、`Command`、`Action`、`ActionResult`、`ErrorDetail`、`Event`；相关 `StrEnum` 和 `JsonValue/JsonObject` |
| `bca.core.protocol` codec | `to_dict`、`to_json`、`from_dict`、`from_json`；Frame 默认元数据序列化，完整图像数据显式开启 Base64 |
| `bca.core.providers` | `Provider` 生命周期 `async start/close`；`CaptureProvider.capture(page_id) -> Frame` 与 `InputProvider.execute(action) -> ActionResult` 异步接口；`ProviderLookup` 查询端口及 `ProviderRegistry` |
| `bca.core.runtime` | `StateSink.publish(PageState)`、`EventSink.emit(Event)`：异步背压接口 |
| `bca.core.plugins` | `PluginMetadata`、`PluginConfig`、`PluginContext`、`Plugin` Protocol；插件运行生命周期及观察/命令处理异步，文本解析和格式化同步 |
| `bca.core.errors` | BCAError 及验证、序列化、Provider 能力、插件、命令、生命周期等具体异常类型 |

完整参数、字段、校验条件以实际仓库 `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md` 与源码为准；本摘要不代替 API 文档。

## 3. 关键跨模块约定

1. Frame 保存 PNG/JPEG 编码的 `bytes`，数据按不可变共享使用；截图坐标通过 Frame 元数据转换到 **CSS viewport** 输入坐标，避免重复应用 DPR 和文档滚动偏移。
2. 内部使用 Python 类型传递，JSON 只在边界显式编解码；默认不将 Frame 的图像二进制放入 JSON。
3. 时间采用带时区 UTC `datetime`，JSON 保留微秒；耗时及超时采用单调时钟。
4. Provider 与 Plugin I/O / 生命周期采用异步语义；查询、解析及格式化同步。
5. 标准状态链路由 Runtime 调用 `observe()`，随后 `publish()` 一次；按顺序 await 动作执行，并明确处理失败和取消。
6. **协议 1 → 2 属破坏性迁移**：Pydantic API、旧版 Frame 裸像素格式与自动字段转换接口不可作为后续模块的依赖。

## 4. 后续子系统交接重点

- **BCA-01 Browser**：实现编码截图、准确的 viewport/capture 元数据、输入行为及异常和取消清理。
- **BCA-02 Runtime**：实现单次状态发布、Sink 背压、状态序号和动作队列的排序/取消/释放策略。
- **BCA-03 Plugin System**：依据版本及能力声明加载插件，注入 `ProviderLookup`，完成生命周期失败清理。
- **BCA-04 Vision & Assets**：按需解码与校验图像，保持帧载荷只读，使用 Frame 坐标映射。
- **BCA-05 CLI**：使用规范化 Command、插件格式化、显式 codec 与异步输出。
- **BCA-06 Majsoul**：维护插件自己的状态 Schema 与识别诊断，动作映射保留在插件。
- **BCA-07 Integration**：验证真实浏览器全链路、断连/背压/取消、性能及 Python 运行矩阵。

## 5. 建议主会话更新事项

1. 更新 `BCA_PROJECT_CONTEXT.md`：BCA-00 状态改为“阶段验收完成（基于 Codex 报告）”，记录 **0.2.0 / Protocol 2** 和方案 A；校正 BCA-00 任务文件索引。
2. 在各 BCA-01～07 任务文件中注明 Protocol 2 及其关键契约，并指向仓库 `docs/INTERFACES.md` 与 `docs/PLUGIN_SPEC.md`。
3. 为后续阶段安排 Git 初始化、Python 3.12/3.13 运行测试以及实际集成验证。
4. 公共模型、Provider 或 Plugin 接口后续如需破坏性修改，由架构主会话统一协调，并更新协议版本与依赖任务。

## 6. 证据边界

以上完成状态及测试数字来自用户提供的 `BCA-00_HANDOFF.md`。本会话未获得完整仓库，也未独立复现构建、测试或接口调用。正式发布时应以仓库源码、测试日志和对应版本记录为最终依据。
