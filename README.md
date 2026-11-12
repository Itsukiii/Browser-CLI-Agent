# Browser CLI Agent（BCA）

通用浏览器页面感知与输入控制框架。已实现 BCA-00 公共契约，以及 BCA-01.1 的本机异步 CDP 连接、页面发现与显式目标绑定。真实浏览器完整验收由用户接续执行。

## 开发环境

需要 Python 3.12+。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
```

Linux/macOS 将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。如果 Windows 的 `python` 指向不可用的应用执行别名，请使用实际 Python 安装路径创建虚拟环境。

当前包基线为 0.2.0，公共协议版本为 2，公共模型保持标准库 dataclass/Enum/Protocol。BCA-01.1 增加唯一直接运行依赖 `websockets>=15,<16`；视觉与 CLI 框架留待对应阶段添加。普通安装使用 `python -m pip install .`；第三方插件不随 `bca` 包自动加载。

```python
from bca.core.protocol import Action, ActionType, MouseButton, from_json, to_json

action = Action(
    page_id="demo",
    type=ActionType.MOUSE_CLICK,
    x=120,
    y=80,
    button=MouseButton.LEFT,
)
assert from_json(Action, to_json(action)) == action
```

`plugins/example` 是公共接口示例，通过模拟 Provider 运行。当前尚未实现 Capture/Input Provider、调度器和可交互 CLI。

## 浏览器连接与测试

浏览器需先由使用者启用本机 CDP 调试端口。查看 [浏览器开发与用户验收说明](docs/BROWSER.md)，然后运行：

```powershell
.\.venv\Scripts\python.exe examples/browser_session.py --endpoint http://127.0.0.1:9222
.\.venv\Scripts\python.exe examples/browser_session.py --endpoint http://127.0.0.1:9222 --target-id <目标ID>
```

默认 pytest 不连接真实浏览器，网络测试仅使用本机模拟服务器；真实测试须显式设置 `BCA_CDP_ENDPOINT`，详见 BROWSER.md。

## 文档

- [架构与目录](docs/ARCHITECTURE.md)
- [完整接口与坐标约定](docs/INTERFACES.md)
- [插件开发规范](docs/PLUGIN_SPEC.md)
- [后续开发计划](docs/DEVELOPMENT_PLAN.md)
- [BCA-00 开发报告](docs/BCA-00_REPORT.md)
- [当前 BCA-00 增量验收与交接](docs/BCA-00_HANDOFF.md)
- [BCA-01.1 交接](docs/BCA-01.1_HANDOFF.md)
- [原始需求](docs/md/BCA-00_项目初始化与公共接口设计.md)
