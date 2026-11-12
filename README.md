# Browser CLI Agent（BCA）

通用浏览器页面感知与输入控制框架。本仓库已实现 BCA-00：项目初始化、公共数据协议、Provider 与插件接口，以及使用模拟 Provider 的集成测试。

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

当前包基线为 0.2.0，公共协议版本为 2，采用标准库 dataclass/Enum/Protocol，无第三方运行时依赖。浏览器、OpenCV 和 CLI 框架留待对应开发阶段添加。普通安装使用 `python -m pip install .`；第三方插件不随 `bca` 包自动加载。

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

`plugins/example` 是接口示例，通过测试中的模拟浏览器运行；当前没有真实浏览器连接、调度器或可交互 CLI。

## 文档

- [架构与目录](docs/ARCHITECTURE.md)
- [完整接口与坐标约定](docs/INTERFACES.md)
- [插件开发规范](docs/PLUGIN_SPEC.md)
- [后续开发计划](docs/DEVELOPMENT_PLAN.md)
- [BCA-00 开发报告](docs/BCA-00_REPORT.md)
- [当前 BCA-00 增量验收与交接](docs/BCA-00_HANDOFF.md)
- [原始需求](docs/md/BCA-00_项目初始化与公共接口设计.md)
