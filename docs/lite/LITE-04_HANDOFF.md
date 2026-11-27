# LITE-04 阶段进度（未完成，非最终验收）

按主会话正式方案实施，已同步lite@5547468；全部变更仅在lite。

- 04.1实现、原始证据与报告已提交 `21ea28b`，见LITE-04.1_HANDOFF.md。
- 04.2纯视觉插件/模板资源草案及真实Maa实验已归档，**存在OCR阻断，未通过**。
  见LITE-04.2_HANDOFF.md和LITE-04_DESIGN_DEVIATION.md。
- 04.3与04.4尚未实施。请先裁决数字OCR验证方案，再恢复按子阶段提交与验收。

没有更改已验收的单图单次授权、输入双确认、native关闭或fixture CLI语义。
本文件是中间断点索引，不能替代最终LITE-04全部验收证据。

## 04.2a～c执行更新

已按lite@16f2119完成补充实验：a提交6cf43b4、b提交a2e3a94。独立准确性矩阵180/180，
真实缩放30/30，负例6/6拒绝；但四轮60秒完整有效频率均未达到1Hz，故04.2仍未通过。
干净wheel原生资源校验通过，全量离线933通过，页面/fixture CLI回归10通过。
详见[LITE-04.2_VALIDATION_HANDOFF.md](LITE-04.2_VALIDATION_HANDOFF.md)及偏差报告新增性能章节。
04.3/04.4未实施，等待主会话复核及下一步性能实验裁决。

## 2026-11-27 主会话架构裁决

- **04.1 页面与受控资产：子阶段 Accepted**（仅涵盖页内规则、时间边界、资源与测试，不视为完整 Quiz 视觉操作）。
- **04.2：原 OCR 实现未 Accepted。** 审核原始 `6→空` 与 `1→7` 证据，批准 Maa JTemplateMatch 自制数字字形与 JOCR/only_rec 的补充验证方案；独立准确性/有效频率通过后再复核。
- 裁决文件：[`LITE-04.2_ARCH_DECISION_2026-11-27.md`](LITE-04.2_ARCH_DECISION_2026-11-27.md)。04.3 保持等待；LITE-04 整阶段仍未 Accepted。

## 2026-11-27 主会话第二次性能裁决

独立数字识别180/180、真实缩放30/30、六项负例拒绝认可；四轮真实持续观察依然未满足有效1Hz，故04.2整体仍未Accepted，04.3继续等待。主会话对性能脚本发现统计口径扰动：逐帧DOM oracle/双PNG/完整JSONL写盘影响elapsed但不计入单帧total。裁决先做lean/全证据配对，再逐请求profile、实验性合并模板（仅在完整候选归属可证时）；nonraw确认模板另做独立校准及盲测。详见 [`LITE-04.2_PERFORMANCE_DECISION_2026-11-27.md`](LITE-04.2_PERFORMANCE_DECISION_2026-11-27.md)。
