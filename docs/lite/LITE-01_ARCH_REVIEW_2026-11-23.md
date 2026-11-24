# BCA-lite · LITE-01 架构主会话源码审查记录

- 日期：2026-11-23
- 仓库：`https://github.com/Itsukiii/Browser-CLI-Agent`
- 审查目标：`lite`，远端 HEAD `3e54a2dbb531bd2026e8ae6349dd1559f58cba40`（交接提交的远端 SHA；此前本地报告中记录为 `1581ee1`）
- 原基线：`main@6763016ff5fee86fb194ebe0e0c9ca17d775adfe`
- 涉及提交：`72d8709`（审计）、`22b4c71`（桥接实现与证据）、`3e54a2d`（交接与主交接书归档）
- 审查类型：GitHub 远端源码、测试实现、已提交日志及报告的静态复核；**主会话未在用户 Windows/Edge 上重跑**。

## 1. 判定

**LITE-00：审计材料认可。LITE-01：核心实现预验收通过，待两项定向证据补充后正式 Accepted。** 暂无证据要求推倒桥接架构；可立即准备 LITE-02 方案/素材/测试设计，但不要把 01 的缺口写成已经通过。

## 2. 已确认的实现事实

| 关注点 | 已审查依据 | 结论 |
|---|---|---|
| 固定绑定 | `src/bca/lite/bridge.py` 的 `_binding`、`_check` | 单实例固定 `(connection,page_id,session_id,generation)`，重新绑定旧 bridge 失效 |
| 线程桥接 | `_call`、`_serialized`、`run_native` | native 回调从其他线程进入 owner loop，同 loop 快速拒绝；使用 owner-loop asyncio 锁，避免旧同步锁阻塞 |
| 观察身份 | `ObservationRef`、`authorize`、`_click_frame` | 精确对象身份、单次消费；**还不是**业务回合签名或最终的按坐标授权 |
| 坐标和 BGR | `MaaCDPController`、`Frame.pixel_to_css` | BGR ndarray；原生返回截图的坐标经 Maa raw/target 映射回 raw，再用 Frame 转 CSS |
| 超时和输入未知 | `_blocked`、`input_outcome`、Provider | 未确认输入后阻断桥接，不重试，作业成功不等于页面效果成功 |
| 生命周期 | `invalidate`、`aclose`、`MaaCDPController.close` | 停止入口、排空 owner tasks、native worker 结束后销毁 Controller；Maa v5.16.1 私有 Destroy 调用已被版本锁保护 |
| 原生调用 | `tests/lite/test_maa_native.py` | 真实 DLL callbacks、raw/nonraw、Resource/Tasker/DirectHit、取消与模拟丢 ACK 已有测试实现 |
| Edge 测试 | `tests/lite/test_real_bridge.py` | 12 组坐标矩阵、DOM oracle、5 类失效与资源收尾有自动化断言 |

## 3. 交付证据范围

- `docs/evidence/LITE-01/offline.txt`：**784 passed、46 skipped**，跳过的是明确需 CDP 的测试。
- `lite-offline.txt`：**24 passed、1 skipped**；`lite-live.txt`：**25 passed、0 skipped**（此处 25 是 lite 集合总数，而非 25 个不同真实浏览器案例）。
- `browser/report.json`：12 组（DPR 1、1.5、2 × 全图/ROI × raw/nonraw），每组 3 次、合计 **36 次真实 Edge 点击**；DOM 目标和坐标被单独核验。
- `summary.json`：DOM CSS 最大误差 **0.667 px**；混合样本截图 median/p95 **93.16/143.00 ms**、点击 **3.59/6.27 ms**。仅是此矩阵的局部耗时，不是完整 1Hz 观察和 OCR 性能。
- `mypy.txt`：92 个源码文件通过；`ruff.txt`、`format.txt`、`build.txt`、独立安装结果均已提交。
- 已见 5 类真实 Edge 失效：resize、pinch zoom（显式拒绝）、navigation、unbind/rebind、Target destroy。

## 4. 正式 Accepted 前仍需的两组定向补证

**G1 — 原生 Edge 桌面缩放：** 在受控隔离 Edge 上使用实际浏览器菜单或 `Ctrl + + / -`（而非仅 `Emulation.setDeviceMetricsOverride` 或 pinch），覆盖至少 80%、100%、125% 的可实际设置缩放档位；如版本/环境无法使用某档位，记录实际档位，报告不支持的组合。每组记录 Frame、Maa returned image、raw/native callback、预期 CSS、DOM 实际坐标、目标命中，验证原有授权和取消。

**G2 — Edge 真实传输故障代理：** 使用受控本地 CDP 代理/注入点，至少分别验证 `mousePressed` 响应丢失、连接断开，以及关闭与在途回调竞争。观察是否已实际派发输入、后续是否被阻断、有没有自动重发、browser/provider/native 清理和 pending=0。注入方的“丢 ACK”必须可从代理日志核实，不能仅凭测试名称说明。

两组产出 `docs/evidence/LITE-01-addendum/`（原始日志、JSON、截图、复现命令），更新 `docs/lite/LITE-01_HANDOFF.md` 并附新提交哈希后重新提交架构主会话。

## 5. LITE-02 必须延续的约束

1. 应用命令必须 `require_authorization=True`；每个动作新截图、新授权。默认 `False` 仅供受控 smoke / 底层调用，不能直接供终端插件写操作。
2. `ObservationRef` 只能证明截图来源、几何与有效期；页面内 DOM/Canvas 变化未必改变这些值。业务插件还需 `semantic_revision / signature`，确认意图的目标仍是同一回合。
3. 背景观察与用户命令的 Maa 控制器作业序列应由**一个拥有者**统一协调，避免新截图在授权与点击之间更换观察引用。
4. `MaaCDPController.close()` 当前依赖固定版本内部 native Destroy；LITE-02 需统一 Tasker/Resource/Controller 释放顺序并做释放验证，而不是对未标注公开的私有接口假定永久兼容。
5. Maa 识别评分与历史 BCA-04 weighted-RMSE 不能直接比较，也不能沿用 `threshold=0.96`。
6. LITE-02 必须做**真正的 TemplateMatch / OCR** 和真实 CDP 截图识别；LITE-01 的 DirectHit/DoNothing 只证明原生绑定可用。

## 6. 变更与仓库纪律

本次架构主会话仅审阅和准备交接，没有修改或推送 `lite`/`main`。待 LITE-01 正式 Accepted，按既定流程同步 `docs/md/BCA_PROJECT_CONTEXT.md` 与 `lite` README，并记录通过的实际证据；不得提前宣称 01 已正式验收。
