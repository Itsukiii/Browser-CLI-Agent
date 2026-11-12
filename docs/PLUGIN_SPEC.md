# 插件开发规范

核心接口定义在 `bca.core.plugins`；SDK 的 `bca.plugin_sdk.interfaces` 是同一接口的重导出。Plugin 是结构化 typing.Protocol，无须继承某个具体实现。参考 `plugins/example/__init__.py` 和 `tests/plugin_sdk/test_example.py`。

## 元信息与目录

插件提供 `metadata: PluginMetadata`，声明唯一 plugin_id、插件 version、required_capabilities 名称元组。目录采用 `plugins/<plugin_id>/`，包含 `__init__.py`；后续可添加 resources、插件配置、README 和测试。当前 setuptools 仅打包 src/bca，不自动发布或扫描业务插件；发现机制在插件管理器阶段决定。

## 生命周期和接口

| 方法 | 调用约定 |
| --- | --- |
| `async initialize(context) -> None` | Provider 就绪后调用一次；检查所需能力和配置，取得引用。失败后允许 Core 调用 close 清理部分资源 |
| `async start() -> None` | 初始化后启动，重复启动保持幂等；stop 后可重新 start；close 后禁止启动 |
| `async observe() -> PageState` | 仅运行时调用，插件自行选择 capture 或未来其他能力并解析。Core 发布返回值，插件不再重复发布同一状态 |
| `parse_command(text, *, source="cli") -> Command` | 同步解析，禁止 I/O；非法命令抛 CommandError |
| `async handle_command(command) -> tuple[Action, ...]` | 仅运行时调用，映射成有序动作，可返回空元组；不直接执行浏览器输入 |
| `format_state(state) -> str` | 同步输出格式化，业务展示归插件所有 |
| `async stop() -> None` | 幂等，停止并 await 自有后台任务；保留可重启资源 |
| `async close() -> None` | 幂等，包含 stop，释放插件自有资源；部分初始化失败也必须可清理 |

调用顺序：Core 创建/启动 Provider → 检查 required_capabilities → initialize → start → 串行 observe/handle_command → stop → close → Core 关闭 Provider。Core 关闭时先取消并等待所有在途调用，再关闭资源；清理应在 try/finally 中完成。示例插件没有自有后台任务，重复调用行为由实现和测试展示。

上下文 providers 类型为只读能力端口 `ProviderLookup`（Protocol），支持名称与类型查询。插件可使用 `context.providers.get(CaptureProvider)` 获得类型化能力，不引用具体浏览器库。Runtime 可注入 ProviderRegistry 或其他实现。插件不得注册、关闭或替换 Core 的共享 Provider；此端口是类型约束，不是安全沙箱。

## 状态、事件和配置

插件定义 PageState.data 的业务 schema，用 schema_version 表明结构版本。sequence 在插件实例生命周期内递增，stop/start 后不重置；重建实例可重新起算，未来 Core 应按实例会话区分。来自截图时填写 source_frame_id；来自其他 Provider 时可不填。识别失败应提交明确的 recognition_status/diagnostics，不能伪造成功状态。

本基线采用唯一标准主路径：Core await observe 后 await context.states.publish。插件不得在 observe 内发布同一状态。PluginContext 保留 StateSink 端口供 Runtime 编排及后续扩展，自有推送任务尚未标准化，须在 BCA-02/03 明确调度方式后接入。插件可 await context.events.emit 发布自定义命名空间事件。发布成功后不再修改模型内部 dict/list，也不得修改构造模型时传入的原始载荷引用。

```python
# Runtime 的最小调用片段；providers 已由 Core 注册并启动。
from bca.core.protocol import ActionStatus
from bca.core.providers import InputProvider

try:
    await plugin.initialize(context)
    await plugin.start()
    state = await plugin.observe()
    await context.states.publish(state)  # 只发布一次
    command = plugin.parse_command("click 12 23")
    for action in await plugin.handle_command(command):
        result = await context.providers.get(InputProvider).execute(action)
        if result.status is not ActionStatus.SUCCEEDED:
            break
finally:
    await plugin.close()
```

上例位于异步 Runtime 函数体内。initialize 失败后的部分资源也由管理器在 finally 中 close。完整可执行链路见 `tests/plugin_sdk/test_example.py`。

当前数据模型为关键字参数 dataclass，枚举显式传入，不进行字符串自动转换；插件元信息和配置也遵循此约定。模型非法参数抛 `bca.core.errors.ValidationError`，命令语义错误抛 CommandError；如需 JSON 交换使用 protocol 的独立 codec。

PluginConfig.values 是 JSON 兼容配置；插件负责业务配置验证。示例使用 page_id（默认 demo）。Logger 由 Application/Core 注入，插件不配置全局日志。

## 示例行为

ExamplePlugin 需要 capture 和 input；observe 捕获指定页面并报告图像宽高。`click 12 23` 转换成以 CSS 视口坐标定位的左键点击 Action，携带原请求 ID。Core 执行动作并收集结果。该示例没有识别算法、截图坐标自动定位或真实浏览器依赖。
