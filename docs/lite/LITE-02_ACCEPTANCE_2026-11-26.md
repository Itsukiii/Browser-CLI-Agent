# LITE-02 · Maa Vision & Plugin 正式验收

- 决议日期：**2026-11-26**
- 仓库与分支：`Itsukiii/Browser-CLI-Agent` / `lite`
- 源码与原始证据提交：`5b107e463c85292cd8ecb5653dce54ebd341a164`
- 实际远端交接归档提交：`984c61c8a9a05c22aaa96c54e40a2083714dfdd4`；用户消息所述 `7cff131` 未作为当前远端提交检索到，故以 Git 提交图为准
- 子阶段：**LITE-02.1 Accepted、LITE-02.2 Accepted、LITE-02.3 Accepted**
- **正式决定：LITE-02 整体 Accepted；批准进入 LITE-03 Interactive CLI。**

> 验收方式：架构会话核对 GitHub 远端源文件、测试代码、原始 report.json、进程采样、包探针和验收日志；未在用户 Windows / Edge 环境另行重跑。正式 Accepted 只覆盖这里记录的功能、安全与时间/性能条件，不等同于对未来任意网页/机器的承诺。

## 1. 代码与设计审查

- `MaaVisionFacade` 在单 worker 持有/调用 Maa Controller/Resource/Tasker；依赖固定 maafw v5.16.1；识别详情在原生对象存活期间物化为不可变 DTO，来源使用精确 `ObservationRef`。
- `BusinessPlugin` 只实现业务数据的 plan/observe/format/parse/resolve/close；`ObservationCoordinator` 串行新截图、识别、状态签名去重、可见交互 revision、精确授权、一步点击与后置观察。
- `CDPBridge.finish_native_click()` 对本次 Maa Job 成功和本次 CDP confirmation 严格核对；失败为 unknown 并阻断重放。
- `src/bca/lite/fixture.py` 和包内 `resources/fixture/` 使用自有页面/标记资产；`examples/lite_vision.py` 用于受控 Target 原生端到端 smoke。分发资源路径使用 `importlib.resources` 上下文保证其直到 native Destroy 才失效。
- `NativeVision.close` 增加 **Tasker stop succeeded 之后至多 1s 的有界 idle 等待**；仍仅在 `running==false` 确认时才 Destroy，失败/超时不释放依赖；Destroy 结果不确定时不会重复释放。

## 2. LITE-02.3 原始验证

| 验收门 | 实际证据与判定 |
| --- | --- |
| Edge 视觉闭环 | `docs/evidence/LITE-02/02.3/final-edge/data/matrix/report.json`：DPR 1/1.5/2 × raw/nonraw × ROI/full 共12组；模板/OCR→结构化状态→视觉点击→DOM button 和 OCR 123→124；通过 |
| 真实桌面缩放 | `zoom-02/data/zoom/report.json`：80/100/125%，实际 DPR 1.2/1.5/1.875，最大定位偏差约0.4695 CSS px；通过 |
| 正负、歧义、字体 | 全图 OCR 5/12 组初始 AMBIGUOUS，拒绝点击并通过显式 ROI 新观察恢复；36 个字体样本 33 MATCHED/3 AMBIGUOUS，后者未写入；目标移除/重复/恢复与旧 revision 拒绝覆盖 |
| 退役与关闭 | 导航、关自有 Target、受控 capture 延迟、截图取消：失效授权拒绝、输入未尝试、released=true；pending=0、reader=false、保留原 Target；通过 |
| >=180s / >=120 有效 | `sustained-01/data/sustained/report.json`：185.0128s、245完成/239有效、1.2918Hz、5变更通知，0丢弃；通过 |
| 延迟 | 实测总链路 median/p95 139.71/187.32ms；capture 76.93/95.39ms，native 61.75/104.95ms；有原始逐帧日志及可再生成 summary |
| 独立稳定性 | legacy、maa、legacy→maa、maa→legacy 各3轮，12最终进程 exit_code=0；旧 access violation 未复现，仍未归因 |
| 原生 stop 收敛 | 发现 stop succeeded 但 running=true 暂态，bounded idle 等待，100轮单独探针未再现；仍保留 stop失败不 Destroy 的保护；通过本阶段安全准则 |
| Wheel / clean env | 干净 venv 安装含 wheel[lite] 依赖；异 cwd 包内 Template、OCR、缺/损模型拒绝、真实 Edge 示例确认；`package-integrity.json` wheel 与安装字节一致，模型不打包；通过 |
| 离线与工具链 | `final-offline/stdout.txt` 878 passed / 57 deselected；另 `final-edge` 5 passed、`zoom-02` 1 passed、`sustained-01` 1 passed；mypy/Ruff/format/build 成功 |

## 3. 不阻断验收、必须保留的限制

1. **CPU 使用偏高（P2 性能）。** `summary.json` 持续运行进程树平均 CPU=325.63%（单核=100%，约3.26个逻辑核）；峰值 RSS=164.60MiB，PrivateBytes=619.14MiB。无法归因给某一子模块；LITE-03/06 测量弱设备上的有效频率与资源预算，考虑 ROI/请求频率及原生线程配置，优化前先做基线剖析。
2. **全图 OCR 误识别（业务配置风险）。** 5/12 DPR/raw/full条件以及3/36字体条件存在歧义，当前安全拒绝并通过显式ROI新观察恢复。LITE-03 UI 应提示“歧义/未命中”，LITE-04 需要稳定的题目/答案/分数分区 ROI，不允许默认选 best。
3. **历史 native crash 仍未归因（追踪项）。** 旧 BCA-04 OpenCV `decode_frame` 的 access violation 在本次12个独立进程未复现；未证明修复、也不能推断历史为 OOM。LITE-06 前保留原始日志和独立进程混合复查能力。
4. **兼容边界。** 当前真机平台 Windows 11 / Python 3.14.7 / Edge 158 / maafw v5.16.1；WebGL 雀魂、长周期多小时泄漏、CLI 交互式输入仍未在本阶段验证。`MaaTaskerDestroy` 等私有接口升级需独立复审。

## 4. 里程碑与后续

- 02.1 原生视觉与资源：`3316abb`，见 `LITE-02.1_HANDOFF.md`。
- 02.2 纯业务插件、协调与动作校验：`0dcaf74`，P1 fix `b7118e3`，见 `LITE-02.2_P1_ACCEPTANCE_2026-11-26.md`。
- 02.3 Edge、长时、稳定性与发行：`5b107e4`；交接 `LITE-02.3_HANDOFF.md`；原始证据 `docs/evidence/LITE-02/02.3/`。
- **LITE-03 可以从现有 Coordinator/Fixture 底座开始**：正式 `bca-lite` 入口、TOML 配置、Target/插件选择、增量显示与可编辑异步输入、只读新帧查询、Ctrl+C/EOF 安全退出、人类可读诊断；不重新开发 Runtime。
- 按项目纪律，正式阶段 Accepted 后同步 `lite` README 与 `docs/md/BCA_PROJECT_CONTEXT.md`；`main` 历史基线不动。

**最终裁决：LITE-02 正式 Accepted。**
