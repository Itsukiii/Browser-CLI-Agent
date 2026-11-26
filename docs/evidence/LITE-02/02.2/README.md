# LITE-02.2 原始证据

本轮使用真实 MaaFramework v5.16.1 DLL、受控 PNG 图像 Provider 和受控输入 Provider。**不是实际 Edge 识别/点击，也不是02.3长时稳定性验收。** 环境与模型路径清单见 environment.json；模型沿用02.1显式校验文件，未下载新模型。

## 复现

```powershell
$env:BCA_OCR_MODEL = (Resolve-Path .maa-models/ppocr-v3-en).Path
$env:BCA_VISION_EVIDENCE = '.test-artifacts/coord-new-evidence'
.venv/Scripts/python.exe -m pytest tests/lite -q -W error --basetemp=.test-artifacts/coord-new
Remove-Item Env:BCA_VISION_EVIDENCE
.venv/Scripts/python.exe -m pytest -q -W error --basetemp=.test-artifacts/coord-all-new
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m build
```

不设置 BCA_CDP_ENDPOINT。新运行使用新输出目录，避免覆盖失败现场。未配置模型时模型专项会明确 skip，不自动联网。

## 索引与轮次

- `run-01.txt`：69 passed / 1 failed；stop注入失败后的旧关闭流程先关闭Bridge，导致重试Tasker.post_stop报告not inited。已调整为释放失败时保留Bridge/Providers；该失败不隐藏。
- `run-02.txt` / `run-02/`：76 passed；含 stop失败修正及命令停止/取消/关闭竞争。
- `lite-before-start-stop.txt`：104 passed / 5 skipped；补充启动/停止竞争之前的完整lite轮次。
- `lite-final.txt` / `final/`：105 passed / 5 skipped，22.97s。新增23项测试（test_observation.py、test_coordinator_lifecycle.py）；原有stop-failure专项由02.1的Destroy-before-release重试测试改为stop重试，并另加不确定Destroy禁止重试测试。
- `offline.txt`：全仓库结果，单独记录，不与lite累加；不是新视觉验收的替代。
- `mypy.txt` / `ruff.txt` / `format.txt` / `build.txt`：静态与构建结果。

## 最终关键JSON

- `dedup.json`：连续不同Frame的相同业务内容只通知一次；显式查询真实新截图；NOT_FOUND/AMBIGUOUS/ERROR/恢复；容量溢出丢弃计数。
- `frequency.json`：interval=0.5s 的短时实际完成时间、110次心跳、stats；有效频率 **1.950586Hz**。rate基于 stop 前的连续观察，completed_at 最后一个元素是随后 restart+refresh 的验证，不参与该rate公式。不是3分钟/120周期结果。
- `command.json`：OCR可见回合123，新图匹配唯一模板→精确ref授权→输入(77,63)→后置OCR124；在输入被持有期间并发refresh无截图插入。
- `reject-*.json`：revision不一致、缺revision、deadline、伪造候选请求、歧义全部零输入。
- `unknown.json`：模拟输入ACK异常后unknown，后续命令被阻断，无重放；不是真实CDP代理故障（真实传输证据属于01）。
- `cancel.json`、`command-cancel/stop/close.json`：在途真实Maa作业/回调与取消/暂停/关闭排空。
- `stop-retry.json`、`coordinator-stop-failure.json`：失败时released=false、原句柄保留、没有Destroy/关闭Bridge，恢复后同worker成功释放。
- 其余final JSON/PNG为原有02.1回归，原始坐标/模板/OCR负例继续保留。

不确定Destroy测试使用假句柄+注入异常，断言只调用一次、保存隔离句柄、禁用可调用指针、released=false；不向真实DLL发送假指针，不为测试制造真实泄漏。运行失败/仍running/stop异常注入同样验证零Destroy。真实释放/stop恢复由native测试补证。

历史OpenCV原生异常保持未归因；02.3复测计划见 `docs/lite/LITE-02.3_STABILITY_PLAN.md`。本目录没有删改02.1原始异常日志。
