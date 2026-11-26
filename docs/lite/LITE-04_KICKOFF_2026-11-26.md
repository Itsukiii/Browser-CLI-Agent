# LITE-04 · Quiz Demo 设计与开发启动交接（Codex）

**状态：正式获准准备设计（2026-11-26），尚未开始 LITE-04 功能验收。** 基线 LITE-03 Accepted。LITE-04 首次要交付真正有两步动作、10秒有效回合与分数结算的垂直示例。

## 0. 先读材料与协作

- `docs/md/BCA-LITE_MASTER_HANDOFF.md` 第9节（9.1～9.3）是**业务规格权威**，本文件是实施/验收分解，不能擅自缩减业务。
- `docs/lite/LITE-03_ACCEPTANCE_2026-11-26.md`、`docs/lite/LITE-03_HANDOFF.md`、`docs/lite/CLI.md`、`docs/lite/PLUGIN_CONTRACT.md`、`docs/md/BCA_PROJECT_CONTEXT.md` 第0节。
- 必读源代码：`src/bca/lite/{observation.py,plugin.py,vision.py,bridge.py,cli_session.py,interactive.py,fixture.py}` 和 `tests/lite/test_real_cli.py`、`tests/lite/test_real_vision.py`。
- **本阶段架构方案由主会话设计并已定稿**：`docs/lite/LITE-04_DESIGN.md`。Codex 负责本地 `lite` 实现、实测、证据及归档；遇到实际 API / OCR / race 约束时提交最小偏差说明，主会话审核调整。确认分支、工作区与最新提交；别提前标记 Accepted。

## 1. 产品需求（必须逐项满足）

**网页：** 一个0～9随机单数字题目，A/B/C/D四个互不重复的一位整数选项（恰好一个等于题目，正确位置变化），一个确认按钮、一个可见分数框。每10秒自动换整题（至少改变题目数字）；用户在本轮先点选项、再点确认，答对+1、答错-1；零、负数、多位分数均需显示及正确识别。任意成功提交都立即结算并生成新题、10秒重计；倒计时和提交交叉时，旧选择不能结算到新题。测试提供确定性随机种子与可控时钟；业务插件对页面只看截图，DOM仅限测试刺激与oracle。

**终端：** 至少1Hz真实完成的题目/四选项识别；题目发生变化时只打印一次`【题目已更新】`及完整题目选项；输入 `A/B/C/D`（大小写兼容）回车后完成选择+确认；点击目标必须来自新视觉唯一候选与每步精确授权。`?` 在任何时刻请求新截图读取**当前分数**。提交前后可见分数差+1/-1分别提示正确/错误；差0标记待结算/未知并限时观察，不得判为错误；更大差值、题目刷新/歧义、输入不确定时保守拒绝或说明无法归属。提交后验证新题确实出现，不用native `succeeded`冒充结算。

## 2. 设计执行检查项（以主会话已归档的 LITE-04_DESIGN.md 为准）

正式方案已由主会话写入 `LITE-04_DESIGN.md`。以下列举的原问题现在作为 Codex **实施自检与偏差报告** 的检查项：

1. `BusinessPlugin` 可以怎样表示Quiz的 `question`、四选项 `A/B/C/D`、`score`、`selected_option`（视觉可证）、当前回合依据，以及`signature`和`interaction_revision`；是否需要安全兼容扩展，保证旧fixture测试仍完整通过。
2. 原 `ObservationCoordinator.execute_intent` 是**一次新观察→一笔点击→后置观察**。两步操作必须先完成**选项点击并视觉验证选中态与同一回合**，再取得另一张新图、唯一确认按钮候选及新的`ObservationRef`，执行第二笔点击；不允许重用第一次点击授权、直接绕过Coordinator、缓存坐标或把两个点击打包为不可观察的宏。
3. 两次点击跨越倒计时时存在竞态：设计如何依据**可见回合标志/题目与四选项完整指纹、预期状态和时间预算**阻止旧题交叉，如何在页面端以 **round_id 对选择归属作原子校验**（仅用于受控网页防止旧选择误计新题；插件不能读隐藏 JS round_id）。应解释在单纯CDP图像+普通点击条件下无法提供真正跨网页定时器的原子事务承诺；竞争发生时按视觉可证结果退役/报告无法归属。
4. 分数读数失败、先后读数0、负数、多位数、偶发OCR歧义、计时已换题、两个选项重复或缺失时分别是什么失败/待定状态；在哪一层实现有限重观测、超时和状态通知，避免再次搭建通用任务调度器。
5. CLI如何选择`--plugin quiz`、配置其自制页面/Bundle/ROI，保持原有fixture无需变更；命令忙时如何定义`?`与A/B/C/D的顺序；怎样让人类读到题目更新而不破坏编辑输入缓冲。

**设计关已完成：** `LITE-04_DESIGN.md` 是当前执行规范。Codex 可立即开始 04.1，但遇到真实接口与设计不一致时需提交实测证据与差异，不自行改写本规范。

## 3. 实施阶段（设计批准后分步）

**04.1 网页与受控资源。** 实现可独立打开的静态/本地服务Quiz，确定性seed/time注入和截图素材；选项唯一、题目变化、10秒超时、正确/错误、旧选择无效以及提交后立即换题要有纯页面/浏览器测试。

**04.2 Maa Quiz 识别插件。** 使用 Maa Template/OCR 与明确ROI读取题目、四选项、确认、选中态、分数；对0～9、负分、多位数、错误字符和置信/歧义有真实截图正负样本；与Coordinator状态签名和轮次语义配合。

**04.3 安全两步交互与 CLI。** 扩展最小业务协调、每次新截图/精确授权，用户输入 A/B/C/D 和?；正负/待结算分数差明确反馈；通过ConPTY/真实PowerShell进行多轮自动换题及人为正确/错误作答，证明按可见页面状态决定动作、DOM仅是测试oracle。

**04.4 真机稳态/竞态验收。** 真实Windows Edge + Maa、1Hz有效观察、自动换题多轮、计时边界交叉、缩放/字体/ROI/歧义/DOM变化、Ctrl+C/EOF/Target断开、unknown/后置验收不充分；记录命令→结算median/p95、CPU/RSS、清理状态、原始PNG/识别JSON/状态轨迹与DOM oracle。正式报告 `LITE-04_HANDOFF.md`。

## 4. 对既有安全门的继承

- 只绑定明确 Target，`require_authorization=True`；每一步实际 Maa 视觉唯一候选，Bridge一次性ref授权，native Job/本次CDP双确认；unknown后不重放；用户自己的其他页面完整保留。
- 一次CommandResult的`confirmed`仅是输入确认；Quiz业务结算必须通过新截图+分数差+题目变化确定，不可借用隐藏DOM或缓存状态。
- 后台观察与人类命令共用现有唯一协调门，不积压任务；终端重绘沿用PromptTerminal，避免引入独立任务队列、事件总线或第二套视觉识别框架。
- 对CPU约3.97核的CLI测量保留性能预警；模型线程、ROI、运行频率优化必须在不降低可见正确性和≥1Hz有效观察的前提下测量。

## 5. 交付及复现纪律

每子阶段提交代码/测试/原始证据，`docs/lite/LITE-04_HANDOFF.md` 引用可复现命令、Git SHA、模型/素材版权、Windows/Edge版本；失败轮次保留。按 LITE-04 总交接规格的 9.3 测试矩阵逐项附证据；不得把单次模拟输出当成真实用户闭环。主会话审计通过才更新 README/PROJECT_CONTEXT 的 LITE-04 Accepted 状态。

**启动指令：阅读主会话完成的 `LITE-04_DESIGN.md`，确认契约后从 04.1 页面与受控资源开始实施。**
