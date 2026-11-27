# BCA-lite · Codex Repository Instructions

## Project authority

本仓库当前开发目标为 `lite` 分支。

开发前应阅读：

- `docs/md/BCA-LITE_MASTER_HANDOFF.md`：产品路线、阶段边界、质量与协作规范。
- `docs/md/BCA_PROJECT_CONTEXT.md` 第 0 节：当前已验收架构与接口。
- 当前阶段的 `DESIGN`、`KICKOFF`、架构裁决及交接文件。

已批准的架构设计与安全不变量优先于 Agent 自行提出的替代实现。需要实质性调整时，先提交证据和设计偏差，交架构主会话裁决。

## Subagent orchestration

允许 Codex 根据任务复杂度、独立性和决策风险，使用子 Agent 并行完成有边界的工作。

具体角色、模型档位、委派条件、并发约束和汇总要求，遵守 `docs/md/BCA-LITE_MASTER_HANDOFF.md` 第 16 节。

不要为了使用多 Agent 而拆分简单任务。

## Repository and runtime safety

- 主 Agent 统一管理工作树、代码集成和最终交接。
- 子 Agent 的修改范围必须明确，避免并发修改同一文件。
- 共享 Edge/CDP Target、Maa native 对象及相互依赖的集成测试不得无协调地并发执行。
- 严格保留 ObservationRef 一次性授权、输入结果确认、未知结果禁止重试和原生资源安全释放规则。
- 不擅自修改或合并 `main`。
- 不使用强制 reset、force push 清除已有开发成果。
- 推送、合并和外部发布遵守用户的明确授权。

## Verification and delivery

子 Agent 的结论必须由主 Agent 复核。

交付必须包含实际代码变更、源码引用、测试命令、原始证据、失败记录与未解决问题。

阶段完成由架构主会话正式验收；Codex 不得自行宣布后续阶段已获批准。
