# LITE-02 阶段交接索引（正式验收归档）

**状态：Accepted（2026-11-26）。** 子阶段 02.1 / 02.2 / 02.3 已全部完成代码与原始证据复核。正式决定见 [LITE-02_ACCEPTANCE_2026-11-26.md](LITE-02_ACCEPTANCE_2026-11-26.md)。

| 子阶段 | 状态 | 实现与证据 | 交接 |
| --- | --- | --- | --- |
| 02.1 Maa 原生视觉与模型 | Accepted | `3316abb` · `docs/evidence/LITE-02/02.1/` | [02.1 报告](LITE-02.1_HANDOFF.md) |
| 02.2 BusinessPlugin 与 Coordinator | Accepted | `0dcaf74` + P1 修复 `b7118e3` · `docs/evidence/LITE-02/02.2/` 和 `02.2-click-fix/` | [02.2 报告](LITE-02.2_HANDOFF.md) · [P1 验收](LITE-02.2_P1_ACCEPTANCE_2026-11-26.md) |
| 02.3 真实 Edge / 长时 / 打包 | Accepted | `5b107e4` · `docs/evidence/LITE-02/02.3/` | [02.3 报告](LITE-02.3_HANDOFF.md) |

**整阶段实测摘要：** 12 组 Edge DPR×raw×ROI、桌面80/100/125%、点击DOM oracle及失效拒绝通过；185.0128s／239有效／**1.2918Hz**；干净 wheel+模型完整性；最终离线878 passed／57 deselected，独立 Edge 矩阵5 passed、缩放1 passed、长时1 passed。

**保留风险：** OCR 全图歧义会拒绝写入（5/12 初始矩阵和3/36字体样本）；平均 CPU ≈3.26核；历史 OpenCV access violation 在12个独立稳定性进程未复现、仍未归因。详情和边界见正式验收书。

后续进入 [LITE-03 Interactive CLI](LITE-03_KICKOFF_2026-11-26.md)，不将单帧视觉闭环误写成完整终端应用或雀魂插件。`main` 无修改。
