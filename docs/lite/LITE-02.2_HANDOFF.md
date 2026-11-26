# LITE-02.2 · BusinessPlugin 与观察/命令协调交接

2026-11-26。**实现与测试已交付，提交架构主会话复核；尚非02.2或LITE-02整体正式Accepted。** 02.1已按本日审查Accepted；未进入02.3。

## 基线与提交

- 开始基线 `lite@46dc585`，既有源码干净；用户新增 `LITE-02.1_ARCH_REVIEW_2026-11-26.md` 未跟踪，已完整阅读且原样保留，不代改主会话审查材料。
- 同时完整阅读批准设计与开发任务书，特别落实P1-A、P1-B及Bridge独占委托边界。
- 实现/测试/原始证据提交 **0dcaf74**。本报告及阶段索引另行提交，可用 `git log --oneline -- docs/lite/LITE-02.2_HANDOFF.md` 定位。
- 全程lite，未合并main、未推送、未改README/总纲的大阶段验收状态。

## 交付接口与源码

| 文件 | 增量 |
| --- | --- |
| `src/bca/lite/plugin.py` | 纯业务BusinessPlugin Protocol；冻结BusinessState/VisualTarget/ReadIntent/ActionIntent，递归不可变数据检查 |
| `src/bca/lite/observation.py` | ObservationCoordinator；start/stop/aclose、refresh、execute_text/execute_intent、latest/stats/take_change；一个业务门覆盖整次命令 |
| `src/bca/lite/vision.py` | 支持单次实际截图后调用plan；保存本Facade最后签发Batch；click仅接受同一Batch、唯一实际候选、明确授权模式，调用Bridge.authorize原始ref |
| `src/bca/lite/bridge.py` | 新增只读requires_authorization属性，不放宽授权/时效/坐标规则 |
| `src/bca/lite/_native_vision.py` | stop失败/仍running保留所有句柄；Destroy异常隔离指针、禁止重试；停止失败时Facade保留借用Bridge，释放成功才关闭 |
| `examples/plugins/lite_fixture.py` | 小型可导入fixture插件；模板button、可选OCR可见round；`?`读取、`click <round>`生成有限意图，无Controller/Session |
| `tests/lite/test_observation.py` | 去重、状态变化恢复、实际新图、短时持续观察、并发心跳、唯一目标授权、revision/deadline拒绝、unknown/取消 |
| `tests/lite/test_coordinator_lifecycle.py` | 命令与stop/close/cancel竞争、stop失败与重试、旧/复制Batch拒绝、start/stop竞争、插件关闭错误、stop异常/仍running |
| `tests/lite/test_vision_native.py` | 将旧“Destroy异常直接重试”用例改为stop失败重试；不确定Destroy另用假句柄验证，避免真的重复释放 |

准确调用与拥有权见 [PLUGIN_CONTRACT.md](PLUGIN_CONTRACT.md)。没有新通用Runtime、注册中心、目录扫描、DSL、事件总线或CLI。

## 实现决策与安全边界

**来源与业务分离。** state.signature只用于业务内容去重；interaction_revision须来自可见回合证据；ObservationRef是精确图像/绑定来源，三者不互换。VisualTarget仅指向request_key/candidate_index，框由Maa结果提供；VisualObservation记录来源、binding、Maa尺寸、框与坐标空间，不保存额外BGR数组。payload/signature仅允许不可变scalar/tuple。

**单门命令。** Coordinator独占Facade与插件；宿主不得并行绕过它直接调用Facade/Bridge。一次写命令持门执行：新截图/识别→原意图revision/deadline检查→业务resolve→实际唯一候选→精确Batch/ref校验→native点击→后置新观察。期间背景及读命令不能更换截图。Maa返回坐标只由Maa转raw、Bridge转CSS，不手工重复应用DPR。confirmed不是业务结算成功；CommandResult同时返回输入结果和新观察。

**查询与通知。** refresh和ReadIntent每次都等门后实际新截图；latest每次更新，内容相同不刷新提示。NOT_FOUND/AMBIGUOUS/ERROR/恢复会通知变化。通知为有界轻量序号/状态，满时丢最旧并计数，慢消费者不堵塞观察。间隔按单调时间、最多一个周期在途、不积压补跑；实际有效率以完整截图/识别/解析成功且来源有效未超龄计数。

**暂停和取消。** stop禁止新入口，排空在途命令/周期，可再次start；启动尚未完成时stop胜出。close不可重启。取消观察/命令先退役Bridge/Facade，shield排空native，随后Coordinator执行并核对aclose。unknown永久退役该组合，不换新ref重试旧动作。主动重建必须新Bridge/Facade/Coordinator，旧命令不继承。

**所有权。** Application明确将Bridge独占委托给Facade关闭，并将Facade/插件交Coordinator；Providers仍由Application管理。CloseReport.released=false时不继续关闭Providers。plugin.close纯同步且幂等，其异常进入errors，可再次close；released只证明native释放，不能忽略其他错误。

## P1-A：Tasker stop-failure

- post_stop失败、wait异常或stop成功但仍running：不调用任何Destroy，released=false，保留Tasker/Controller/Resource、worker及Bridge；对照stop_status/errors核验，恢复后同worker重试stop。
- 本轮第一次测试发现“stop失败仍关闭Bridge”会导致重试Tasker not inited，已修正。`run-01.txt`保留69 passed/1 failed，不当作通过证据。
- Destroy已经发起但抛异常：无法证明是否释放，因此不调用原指针第二次。原句柄转入进程期隔离记录，可调用_handle清空以禁止析构重试，回调/依赖对象保留；released=false。隔离不是释放证明；此运行组合必须结束进程，不声称可恢复。
- 假句柄注入验证不确定Destroy只调用一次；真实Maa stop失败注入验证失败时句柄仍持有、无Destroy，恢复后Tasker→Controller→Resource顺序正常释放。没有向实际DLL传假句柄。
- 本规则取代02.1报告中的Destroy-before-release重试语义。native永久卡死仍无法强杀线程；不扩大为进程隔离能力。

## 实际测试与证据

环境：Windows / Python 3.14.7 / Maa Python-native v5.16.1，完整版本在 `docs/evidence/LITE-02/02.2/environment.json`。模型沿用02.1固定PP-OCRv3英文哈希，测试显式设置BCA_OCR_MODEL，无默认下载。

| 验证 | 结果与证据 |
| --- | --- |
| 新专项及原生回归中间轮 | 76 passed，20.80s；run-02.txt |
| 最终lite | **105 passed / 5 skipped，22.97s**；lite-final.txt；新增23项，5项Edge未启用 |
| 全仓库离线+显式模型 | **867 passed / 50 skipped，59.56s，exit_code=0**；offline.txt；旧回归仅兼容性证据 |
| 静态/构建 | mypy strict 99源码文件通过，Ruff/check format通过，wheel/sdist成功；mypy/ruff/format/build.txt |
| 短时真实native持续观察 | interval0.5s，实测 **1.950586Hz**；110次并发心跳，stop/restart后总13个有效结果；final/frequency.json |
| 去重/查询 | 同内容不同Frame仅一次通知，读请求再次新截图；丢失/歧义/解析错误/恢复均更新；final/dedup.json |
| 授权/串行命令 | 回合OCR123→模板唯一候选→精确ref→输入(77,63)→后置OCR124；输入在途并发refresh未插入；final/command.json |
| 拒绝/不重放 | revision不一致、无revision、超时、伪造candidate请求、歧义零输入；unknown后再次执行被拒，只有一次输入；final/reject-*.json、unknown.json |
| 清理 | 在途截图/命令cancel、重复close、stop失败保留并同worker恢复、插件close异常、stop/start竞争；final/cancel*.json、command-*.json、stop-retry.json等与测试断言 |

复现命令、轮次区别和原始JSON说明见 [证据索引](../evidence/LITE-02/02.2/README.md)。频率是受控合成图native短时测量，**不是Edge、三分钟/120周期或游戏效果证明**。不把配置interval当作实际频率，不累加不同测试轮次。

## P1-B 与02.3遗留

历史OpenCV原生异常仍未归因，本轮全量通过不宣称修复。已新增 [LITE-02.3_STABILITY_PLAN.md](LITE-02.3_STABILITY_PLAN.md)：独立新进程复跑旧Vision、新Maa及混合顺序，记录进程RSS/PrivateBytes/commit、系统内存、PID/退出码/堆栈；保留失败样本。旧测试进程稳定性与新Maa链路性能分别报告，发布前评估混合影响。

02.3还须真实Edge图像/视觉点击/DOM oracle、DPR/raw/ROI/字体、≥3分钟与≥120有效周期、完整模型/包内fixture分发和干净依赖安装。本轮不扩展到这些工作，也没有新增终端交互或完整Quiz多步骤。

下一步请架构主会话复核02.2子阶段，尤其stop-failure/不确定Destroy、独占委托、串行授权和取消边界；复核后再进入02.3。
