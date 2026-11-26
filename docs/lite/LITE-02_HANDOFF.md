# LITE-02 阶段交接索引

2026-11-26。设计已 Approved；**LITE-02.1 子阶段已Accepted，LITE-02.2实现交付，等待架构审查**。LITE-02整体尚未正式Accepted。

| 子阶段 | 状态 | 代码/证据 | 报告 |
| --- | --- | --- | --- |
| 02.1 原生 Vision / 资源 | 子阶段Accepted（2026-11-26） | `3316abb`；`docs/evidence/LITE-02/02.1/` | [LITE-02.1_HANDOFF.md](LITE-02.1_HANDOFF.md) |
| 02.2 插件 / 观察 | 已实现与验证，提交审查 | `0dcaf74`；`docs/evidence/LITE-02/02.2/` | [LITE-02.2_HANDOFF.md](LITE-02.2_HANDOFF.md) |
| 02.3 Edge / 长时 / 分发 | 未实现 | — | — |

02.1 新增58项测试，最终 lite 集合82 passed / 5 skipped，全量离线且显式模型844 passed / 50 skipped；另一次诊断复跑的旧 OpenCV 原生异常与92项独立复查均在子报告披露，不以单次通过隐去异常。模型哈希/来源/许可和离线加载见 [models/README.md](models/README.md)。

精确接口、释放/取消/来源边界、原始命令、失败轮次和后续事项以子报告为准。Codex 负责实现与测试；架构主会话负责复核与正式验收。未改 main，未提前更新全阶段 Accepted 状态。

02.2最终lite105 passed/5 skipped，全量867 passed/50 skipped；stop-failure保留所有依赖、不确定Destroy禁止指针重试。历史OpenCV异常未归因，已纳入02.3稳定性计划。02.2的短时原生图片观察不替代02.3真实Edge与长期验证。
