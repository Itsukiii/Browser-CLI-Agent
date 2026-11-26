# 02.3 稳定性验收计划及执行索引

2026-11-26 已按下列计划执行，结果见 `LITE-02.3_HANDOFF.md` 与
`docs/evidence/LITE-02/02.3/`。真实 Edge 185.01秒/239有效观察、三轮四种进程配置、
干净wheel和全量离线均已有原始证据，等待架构复核。历史access violation本次未复现，
仍未归因；新增stop成功但running尚为true的现场及bounded idle等待另见报告，不混为同一问题。

来源：`LITE-02.1_ARCH_REVIEW_2026-11-26.md` P1-B，历史证据 `docs/evidence/LITE-02/02.1/offline-diagnostic.txt`。旧 OpenCV 4096×4096 decode 用例曾出现 Windows access violation；92项独立复查通过不等于已归因或已修复。低内存快照只能作为相关现场，不能认定内存不足是原因。

02.3 必须分别执行并记录退出码、stdout/stderr、PID/开始结束时间、Python/包/native版本和完整命令：

1. 独立新进程执行旧 dataset/decode；先后多轮复跑，记录异常样本与堆栈。
2. 独立新进程执行新 Maa截图→视觉→业务链，不导入旧 Vision/OpenCV Python 后端。
3. 同一进程混合运行旧 Vision 与 Maa，比较两种先后顺序；不能将混合进程异常直接归于新 Coordinator，也不能因新链不用旧解码就忽略发布风险。
4. 每轮按单调时间采集进程 RSS/WorkingSet、PrivateBytes/commit、线程/句柄数、系统可用物理内存与已提交/限制；包括运行前、期间、关闭后。保留原始采样，不只报告峰值。
5. 真实 Edge ≥3分钟、≥120个有效完成周期，记录 capture/native/parse/total耗时、完成间隔、median/p95、内容变化/丢失/恢复、输入确认及 DOM oracle、最终 Target/pending/reader/native句柄。
6. 若崩溃，保留完整失败现场并用相同输入在独立进程复现；不删除用例、降低阈值或关闭用户其他程序来制造通过。模型、OCR/font/DPR/raw/ROI和系统负载条件单独记录。

02.2 只交付轻量业务与协调功能；短时原生合成图循环证明调度可用，不冒充以上稳定性结果。正式环境资源定位、完整干净依赖安装和wheel异cwd fixture验证同属02.3。
