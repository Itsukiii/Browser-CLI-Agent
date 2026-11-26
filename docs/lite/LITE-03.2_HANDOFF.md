# LITE-03.2 异步终端壳层

接续03.1 `bdd3f8a`。`terminal.py`以prompt_toolkit 3.x维护单可编辑行，输出串行且绑定独立AppSession，转义控制字符、截断显示，不记录历史到磁盘。`interactive.py`仅路由现有Coordinator，不另造Runtime或动作队列。

- 单命令在途，忙时输入明确拒绝，不排队/重放；1024字符提交限制。help、quit、EOF/Ctrl+C始终能响应。
- stop等待当前Coordinator工作、resume显式恢复；?无条件通过execute_text取新截图。
- bounded take_change合并为latest显示，独立消费者不阻塞观察；业务状态和expired展示，unknown明确提示永久退役，断线不重连/改绑。
- EOF/quit/Ctrl+C都取消在途命令并等待Coordinator排空（不承诺完成先前动作）；随后Application依序关闭。释放未确认时不关闭Provider；正常释放后即使某个Provider失败仍尝试剩余清理，错误不吞没。
- 缺--target时在真实TTY列出ID/host并要求输入完整ID，空输入取消；无TTY互动模式拒绝，显式--once/--check/--list-targets仍可管道使用。

原始`docs/evidence/LITE-03/03.2/`：50 passed，包括新终端/配置以及原生点击可靠性与Coordinator生命周期回归；mypy107文件、Ruff、build通过。pipe_input + DummyOutput验证后台输出后同一输入buffer仍是原部分命令并可继续编辑。此为软件渲染测试，**不是人类IME或Windows实际终端验收**；03.3另做ConPTY/Edge。历史CPU与OpenCV限制未改变。阶段SHA见所在提交。
