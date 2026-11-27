# LITE-04_DESIGN · Quiz Demo 正式架构方案

> **架构设计者：ChatGPT 架构主会话（小樱）**
> **基线：** `lite@d773fab`（LITE-03 Accepted） · **日期：** 2026-11-26
> **状态：** Architecture Design Approved for implementation；**不是** LITE-04 功能验收。
> **2026-11-27 补充技术裁决：** 04.2 真实 Maa OCR 对单数字出现 6→空、1→7，原单 JOCR 参数不足以保证受控 Quiz 识别准确性。允许有限引入原生 `JTemplateMatch` 的自制数字字形与 JOCR/only_rec 进行验证；冲突必须拒绝，模板单独主判定需满足独立盲测。详见 [`LITE-04.2_ARCH_DECISION_2026-11-27.md`](LITE-04.2_ARCH_DECISION_2026-11-27.md)。**04.1 Accepted，04.2 尚未 Accepted。**
> **职责：** 本文件决定产品行为、边界与接口；Codex 实现、测试、复现 Maa/Edge 真实约束。任何需改变产品语义的偏差提交 `DESIGN_DEVIATION.md` 给主会话批准。

## 1. 一句话方案和不变约束

复用 BCA-lite 已验收的 Browser/CDP、`ObservationRef`、`MaaVisionFacade`、`BusinessPlugin`、`ObservationCoordinator` 和 `prompt_toolkit` CLI；引入一个**可见回合编号的自制 Quiz 页面**、`QuizPlugin`、最小 `LockedVisualPort`（一次占有协调门跨多个独立观察及单次点击）和 `QuizAnswerFlow`（仅 Quiz 业务步骤）。插件仍纯视觉数据，不读取 DOM。页内隐藏 round id 仅供页面自我保护及测试 oracle。

**强约束：** 每次写操作由当次 Maa screenshot 的唯一识别候选产生，并经单次 `ObservationRef` 授权、Maa Job 和本次 CDP 确认；一张图授权最多一次点击；不能用缓存坐标、DOM/JS 读取、多个原生点击宏或旧回合的 retry。`confirmed` 仅表示输入确认，不自动认定答题结算。

## 2. Quiz 页面的确定性规格

受控静态 HTML/JS 页面（可通过 CDP 新建自有 `data:` Target 或本地静态文件/HTTP 加载），显示一个题目框、A/B/C/D 四个选择按钮、一个确认按钮和分数框。题目是随机单数字 0..9；四个选项也均为 0..9 的互异单数字，恰好一个等于题目；正确选项位置在运行期间变化。请设计避免上一题与下一题题目数字相同的重采样规则。

**在题目框中同时显示辅助信息：可见 `题号 #000001`（每轮递增，字体清晰供 OCR）以及倒计时/剩余时间提示。** 此回合编号是用户能直接看到的页面信息，不是偷偷读取 JS 状态；它解决连续不同轮次碰巧同题同选项导致的 ABA 问题。回合编号必须真实对应页面每次换题。显示固定宽度只是推荐，达到容量边界须明确扩位/拒绝回绕，不能静默重用仍可能有效的编号。

每轮从**题目实际出现**开始 10 秒（使用单调时基）；10 秒到期：同步生成新题、分数不变、选择清空、题号递增、倒计时重置。成功提交：验证当前轮有且只有一个选中选项，正确 +1 / 错误 -1；立即产生新题并开始新的10秒。初始分数0；允许负数和任意有限长度的多位整数。按钮点击与页面换题在单线程 JS 事件处理内保持同步的轮次校验。

页面内部必须在选项点击时标记 `{selected_option, selected_round_id}`，在确认事件中**原子检查** `selected_round_id === current_round_id` 且该轮未提交；失效选择不得被结算到下一题。每次换题清空选择。选择后按钮具有明确、由截图可识别的选中态（颜色/边框/标记至少两种可辨手段，不靠鼠标 hover）；未选中时确认无效。多次确认同轮最多结算一次。

自制页面支持确定性 `seed` 和注入式时钟推进/特定时刻换题，用于测试；这些内部控制只允许**测试夹具**使用，生产 QuizPlugin 仍只接收 Maa 截图识别结果。测试使用 DOM/JS 读取 score、round、hits 作为独立 oracle，绝不能出现在 plugin/CLI 实现路径。页面/模板/字体资产注明自制来源及许可。

## 3. 可见语义数据

建议新增 `quiz.py`（页面业务插件）及 `quiz_flow.py`（Quiz 专属动作流程），不更改已冻结 `BusinessState` 与 `RecognitionBatch` 数据语义。内部数据类型可以使用不可变 `QuizSnapshot`：

~~~python
@dataclass(frozen=True)
class QuizSnapshot:
    round_mark: str             # 从屏幕OCR读取的可见题号
    question: int               # 0..9
    options: tuple[int,int,int,int] # A/B/C/D
    score: int                  # 可以是0、负数和多位
    selected: str | None       # 必须由选中态视觉证实
    time_left: float | None    # 只读可见计时线索，严禁替代精确授权

    # 注意：此类是推荐草案，Codex 可按纯类型需要调整字段，
    # 但不能从 DOM/隐藏 round_id 获取上述值。
~~~

`QuizPlugin.observe(batch) -> BusinessState`：`payload` 使用现有递归 immutable tuple（顺序由插件集中管理并提供 `decode_quiz_state`，避免别的模块直接按神秘下标解析）；`signature` 包括题号、题目、四项、分数与选中态，不含时间戳/Frame ID，倒计时不应导致终端每秒重复整题；`interaction_revision` 使用可见 `round_mark`，不使用题目数字或四项拼接冒充唯一轮次。

`status=MATCHED` **要求当前动作所需的全部视觉证据完整、唯一且自洽**：题号合法，题目0..9，A-D各单数、互不重复且包含题目，分数可辨认，确认/目标位置能唯一定位；选中态也必须可辨认。若无法辨认显示 NOT_FOUND / AMBIGUOUS，底层 Job/模型故障为 ERROR。部分可读快照可以提供只读诊断，但不发布任何可执行 `VisualTarget`；也不能以较早观察的分数填补本次 OCR 失败。

`targets` 仅引用本次 batch 中 Maa 真实识别结果，例如 `option_A`/`option_B`/`option_C`/`option_D`/`confirm` 的 `VisualTarget(key, request_key, candidate_index=0)`；每个目标要有自己的**唯一候选**。OCR 的最佳结果用于诊断，不得默选。插件只负责将视觉语义与候选绑定，不调用 Browser、Bridge、Maa native 或 asyncio。

## 4. 视觉资源与 OCR 方案

固定自制页面先确定响应式/缩放策略和可靠视觉 ROI。明确字段 ROI：`round`、`question`、`option_A..D`、`score`、选中态和 `confirm`。文本数字/负号使用 Maa `JOCR`；按钮位置/按钮样式使用 Maa `JTemplateMatch` 等已验收原生能力，结果中心必须落在当前按钮的可点击区域内。只要 ROI 与模板能自适应不同截图尺寸，就不把页面 CSS 或 DOM 位置作为点击的输入。

多个字段尽可能复用**一次截图上的多次识别**；若分区 OCR 次数使真实有效观察低于 1Hz，可以优先测试合并 OCR 区域后按照 Maa 坐标区分候选、有限模板/ROI 或调整模型/线程配置，但必须保留逐字段唯一性检查。不得为了提升频率把旧分数缓存当作当前识别；亦不得回退到旧 BCA-04 Vision 实现。

初始化时核验 `ResourceSpec`、OCR 文件哈希、来源许可证，资产维持 `importlib.resources.as_file` 上下文直至 native Destroy；不同 DPR / Edge 80%、100%、125%/raw 与 nonraw 全部按 Maa image pixel coordinate 判定，坐标换算仅交 `MaaVisionFacade` / `CDPBridge`。

## 5. 最小的多步骤动作边界（核心设计）

原 `ObservationCoordinator.execute_intent()` 已验收为一次新观察 + 一次授权点击 + 新观察；**不能直接把它调用两次并在中间放开应用级命令锁来拼凑两步事务。** 通过一个**窄接口**扩展 Coordinator，使单个业务流程在同一 `_gate` 下运行，同时每一步使用不同截图和不同授权。

推荐 API 草案（类型名称允许 Codex 在类型检查下微调；公共安全语义不可变）：

~~~python
class LockedVisualPort(Protocol):
    async def observe(self) -> VisualObservation: ...
    async def click(self, observed: VisualObservation, target_key: str) -> str: ...

async def ObservationCoordinator.run_exclusive(
    operation: Callable[[LockedVisualPort], Awaitable[T]],
) -> T: ...
~~~

`run_exclusive` 持有**现有同一把** `_gate`，仅向主应用层可信 `QuizAnswerFlow` 提供受限的 LockedVisualPort；绝不把 Facade/Bridge 句柄传给插件。`LockedVisualPort` 为本次 scope 专用、离开 scope 失效，不允许外部保留后调用；`observe` 必须调用原 `_refresh_locked()` 产生新 Frame/Batch，并同步保存**精确的最新 observation 对象与 batch 对象**。`click` 只能消费自己**最后一次**观察的身份相同对象，要求 source_current、未过期、MATCHED、唯一 candidate、当前 revision/流程前置守卫和时间预算均满足；之后立即使该 batch 对本 port 不可再用，再调用现有 Facade.click。任一 unknown 立即 retire；不额外增加一把独立动作锁。

**一个重要的实现细节：** `click` 的 `observed` 不能仅凭相等值/sequence/string revision 比较，必须与这个 scope 实际签发的当前对象同一身份，且与最近 batch 对应；防止旧观察通过复制相同字段重新授权。后续观察可读取新 batch 但不可复活旧授权。实现重用单步点击的共享内部安全 helper，避免和现有 `execute_intent` 两套点击逻辑逐渐分歧；原 Fixture 的单步行为、测试和公开接口保持兼容。

`run_exclusive` 的取消继承现有 `_cancel_cleanup` 语义：取消在途 native 必须等待排空；不确定输入不重复；关闭时 native release 失败不销毁依赖；其他周期观察在独占流程中等待但不会取走流程中的观察引用。建议由应用在流程开始时暂停无关的高频通知，仅显示必要进度；不得持有门等待人工输入或任意长的外部事件。

### 5.1 QuizAnswerFlow 的严格顺序

1. CLI 收到 `A/B/C/D`（大小写兼容），纯解析为 QuizAnswerIntent；保存用户下令时可见 `expected_round_mark` 和有限的单调截止时间。后台最新若无可验证回合则直接要求用户等待有效题目，**不随手改成下一题作答**。
2. 进入 run_exclusive，`observe()` **先取新截图**。解析题号、题目、四项、分数 `score_before`、选中态和倒计时；验证 round_mark 等于用户下令时的可见回合、目标唯一、页面仍允许点击。超时或靠近换题保护窗口时拒绝，不替用户转去新回合。
3. `click(observed, option_X)` 第一次独立授权点击。若不是 confirmed，立刻结束 unknown / rejected，绝不点确认或补偿重放。
4. `observe()` 重新截图并验证**同一可见 round_mark、四项与题目指纹没有变化、选中态确实为 X、score 未被提前修改**。有任何不一致即停止，禁止确认。
5. `observe()` 再次截图形成**确认按钮专用的新授权**；重新检查同一轮和 selected=X、`score==score_before`、候选唯一、剩余时间足够；`click(observed, confirm)` 第二次独立授权。这里必须有与第一次不同的 Frame ID/ObservationRef，不得复用按钮坐标。若输入 unknown，流程退役并不自动重试。
6. 第二次点击 confirmed 后进入**有上限的结算观察**：每次真实新截图，检查新题号变化及 score delta。delta +1 → correct；delta -1 → incorrect；delta 0 → pending 直到超时，届时 outcome unsettled；其他差值/识别歧义/题目与分数不对应 → unattributed。**必须同时视觉确认新题出现**才算业务结算完成；不拿 Maa Job 成功替代。
7. 输出结构化 `QuizAnswerResult`：`input_status`（每一步 confirmed/rejected/unknown）、`settlement`（correct/incorrect/pending/unsettled/unattributed/round_changed 等）、`before_round/after_round`、`score_before/score_after`（仅本次识别可信时）。命令耗时有界，非确定结果清楚显示，绝不重发确认。

时间预算默认由 Codex 实测后明确配置，例如动作截止时间、确认前最小可见剩余时间、结算有限轮数与总时长。不能用远大于 10 秒的重试窗口来跨回合寻找成功；字段时间不能用墙钟代替单调时钟。可见倒计时只是安全辅助，无法形成浏览器定时器与外部 CDP 点击之间的真正原子事务。

### 5.2 状态转移与失败语义

| 当前阶段 | 下一步条件 | 不满足时 |
| --- | --- | --- |
| 收到命令 | 当前可见轮、A-D唯一且有效 | rejected，不点击 |
| 第一步前截图 | 轮次/选项/分数唯一；有时间余量 | stale/ambiguous/rejected |
| 选项 click | 本次 native + CDP 同时确认 | unknown 则 retire；无确认 |
| 选中态后截图 | 同轮、选中 X、分数未改变 | round_changed/selection_unknown；不确认 |
| 确认前新截图 | 同轮、同选中、确认唯一、未超龄 | rejected；不确认 |
| 确认 click | 本次输入被确认 | unknown，禁止重发 |
| 结算观察 | 新轮次 + 分数 delta 为+1或-1 | 0 pending→unsettled；异常则 unattributed |

**页内 race 防护和算法安全的界限：** 页内 `selected_round_id` 检查确保旧选择不会结算到新轮；但截图与第二次 CDP 点击之间仍可能恰好进入换题事件。不能向用户宣称“跨网页定时器的两步原子事务”。记录这种窗口的输赢实测，保守报告未知/未归属而不是推断正确。

## 6. CLI 集成决策

CLI 增加显式 `--plugin quiz` 和受控 `--create-quiz` 或等效显式命令；现有 fixture 保持原样。创建自有页才拥有并退出时关闭该页；接入用户已有目标只能精确绑定，不更改其缩放或关闭。Quiz 的资源/模型显式校验，与 fixture 走同一 Maa 依赖和关闭顺序。

终端继续复用 `PromptTerminal` 的可编辑输入。Quiz 状态输出由独立 `QuizRenderer` 比较最新可信快照：当可见 round_mark 变化且题目/四项均可靠时，仅一次打印 `【题目已更新】` + 题目及四个选项；同题持续观察不重复刷屏。分数变化/错误状态单独提示；不要因 countdown 每秒改变而打印整题。状态通知来自当前 Coordinator，而不是新建第二套 EventBus。

`?` **在任何时刻**可被输入，命令空闲时立即通过 Coordinator 获取新截图并显示本次可信分数（含0/负/多位）；两步作答进行中只允许保留**一个待读槽**，明确提示排在安全点后，并在动作结束后重新截图（不是缓存），重复 `?` 合并。A-D 在忙时拒绝，不进入无界队列；help 和 quit 仍及时响应。`?` OCR 失败应显示“当前分数无法识别”，不得回退展示旧分数作为即时查询结果。

现有通用 CLI 的 `interactive.py` 可通过小型 Quiz session/命令适配层配置不同 help/parse/render，不把 Quiz `if/else` 散布到 CDP 或 native。`quit`/Ctrl+C/EOF 在步骤中取消并排空原生工作；若第二次点击是否生效不确定，不能重新尝试。

## 7. 测试与验收门槛（每项有实际源码+原始证据）

**04.1 页端：** deterministic seed/clock；0..9、四选项互异且一项匹配、正确位置变化；10s自动换题（题目数字变化）；确认即时换题；选中无确认不计分；旧轮选择/重复确认/交叉到期不结算；分数0、负、多位，回合编号可见。

**04.2 Maa 视觉：** 真实图像 Template/OCR，题号、题目、A-D、score/selected/confirm 全字段验证；0..9覆盖、-1/-20/-305及多位、不同字体与1/1.5/2 DPR、80/100/125%桌面缩放、raw/nonraw、ROI/full；负例/歧义候选拒绝。截图/定位/识别 JSON 与坐标保留；模型哈希与 wheel 异 cwd 校验。

**04.3 两步动作：** 正确/错误及大小写 A-D；两笔不同的原生截图和精确 ObservationRef；第一步后真正看到 selected=X；第二次确认前再识别；native/CDP unknown、旧轮/过期/无按钮/被换题不得重试或误确认；?在提交中排队且最终新 Frame；Busy命令拒绝；分数+1/-1/delta0 pending/更大跳变/新题未出现所有业务分支。

**04.4 真实 Edge 运行：** 多次自动十秒换题，实际CLI ConPTY和人工PowerShell正确/错误答题、查分、quit；10s边界前/两步之间/确认后换题竞态，DOM oracle与截图轨迹独立一致。至少3分钟连续真实观察并**≥1Hz有效完成**，记录CPU实际PID、RSS/PrivateBytes、median/p95命令到结算、状态去重、pending/worker关闭和原有Target保留。失败轮次日志不能覆盖。

**所有阶段：** `.venv` 安装 wheel 的独立目录测试、pytest lite与全量离线、mypy strict、Ruff/format、build；OCR 模型来源/哈希/许可；保留 LITE-03 已验收 `fixture` 的全链路与 `bca-lite --help` 行为。CPU 高负载（先前 3.26~3.97 核）必须继续采集，采用 ROI/请求频率/原生线程等优化时确保≥1Hz和无猜测性点击；历史 OpenCV 异常仍未归因。

## 8. 开发次序与交付规范

Codex 按 **04.1 页面 → 04.2 QuizPlugin 真实 Maa 视觉 → 04.3 LockedVisualPort + QuizAnswerFlow + CLI → 04.4 真机持续/竞态/打包** 提交。允许在 04.1/04.2 做不改变公共安全接口的技术实验；实现共享多步骤 API 前可写最小验证原型，但对外行为须以本设计为准。

Codex 必须在每步报告具体 commit、通过/失败的原始测试、OCR样本、Frame/round/score/点击轨迹、频率/CPU和未覆盖。遇到真实绑定接口、OCR识别率、时间预算或可见回合布局问题，先用实验证据描述影响范围和**最小方案偏差**，不要自行放宽旧观察授权/结算判定或改变业务规格。主会话负责审核偏差及最终 LITE-04 Accepted。

交付 `docs/lite/LITE-04_HANDOFF.md`、独立 `docs/evidence/LITE-04/` 原始记录与演示说明；只有整阶段通过架构主会话审查后，才同步 README 与 PROJECT_CONTEXT 的 Accepted 状态。

## 9. 与既有接口的兼容要求

- `BusinessPlugin` / `BusinessState` / `ObservationRef` / Maa `RecognitionBatch` 保持原签名和一次性授权；由 QuizPlugin 提供纯内部解析 helper。
- `ObservationCoordinator.execute_text/execute_intent` 的原先 fixture 行为、旧单步 native/CDP 结果和 unknown 语义保持；`run_exclusive` 只在协调门内暴露受限 port，不成为可外部触达 Facade 的逃逸口。
- `cli.py` `--help`/`--check`/`--list-targets` 和 `PromptTerminal` 编辑行为保持；启动时通过明确定义的插件工厂/静态注册选择 fixture/quiz，无目录动态扫描或多宿主自动调度。
- 执行次序必须做到视觉新帧→业务验证→一次 click→视觉新帧，不能以页面 DOM、缓存 CSS 坐标、隐藏 round_id、旧截图或旧 score 替代。

**架构裁决：本设计批准 Codex 开始 LITE-04 实现；先向主会话报告接口实测偏差，后修改设计，不再让 Codex 重新自行起草产品方案。**
