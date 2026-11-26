# LITE-02.2 P1 输入结果归属补证

2026-11-26；基线e38e916。真实Maa v5.16.1 DLL + 受控图片/输入Provider，native Job提前失败/后置失败采用明确故障注入。不是实际Edge传输故障，既有真实CDP故障证据见LITE-01；本轮未做02.3功能。

## 复现

```powershell
$env:BCA_OCR_MODEL = (Resolve-Path .maa-models/ppocr-v3-en).Path
$env:BCA_VISION_EVIDENCE = '.test-artifacts/click-new-evidence'
.venv/Scripts/python.exe -m pytest tests/lite/test_click_outcome.py -q -W error --basetemp=.test-artifacts/click-new
Remove-Item Env:BCA_VISION_EVIDENCE
.venv/Scripts/python.exe -m pytest tests/lite -q -W error --basetemp=.test-artifacts/click-lite-new
.venv/Scripts/python.exe -m pytest -q -W error --basetemp=.test-artifacts/click-all-new
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m build
```

无BCA_CDP_ENDPOINT；模型使用已校验的02.1资源，无下载。原始日志UTF-8/LF，去掉行末空白；不同运行不累加。环境版本见environment.json。

## 记录

- targeted-initial.txt / targeted/：首轮9 passed，1.17s。
- targeted.txt / final-targeted/：补充重复授权断言并在重试前保存诊断，9 passed，0.98s；最终JSON以本目录为准。
- lite.txt：114 passed/5 skipped，23.70s，exit=0；含原有取消、stop、native实际回调/模拟CDP ACK丢失回归。运行时尚未增加上述仅测试层补充断言，生产源码相同。
- offline.txt：全量离线回归日志及实际退出码；旧架构回归不替代本次输入可靠性验收。
- mypy/ruff/format/build.txt：严格类型、lint、格式和wheel/sdist结果。

## 关键断言

`click-pre_failed.json`：第一步真实native confirmed→第二次新Frame→注入post_click Job.failed且未进Bridge callback→unknown；累计callback=1/实际输入=1（均来自第一步）。

`coordinator-native-pre-failure.json`：完整Coordinator同序列，第二步callback=0、累计输入=1、outcome=unknown、结果source=None；再次命令被拒绝。

其余7种参数/成功路径覆盖：native提交异常、虚假成功却没有callback、callback返回False、Provider已接收输入但ACK丢失、真实已确认callback后Job.failed或wait异常；全部失败均unknown、退役、没有重发。callback后失败只允许已发生的第二次输入，不额外发送第三次。

`confirmed-new-actions.json`：两次不同截图、各自native/CDP一致确认，各发送一次；同帧重复authorize不会累积点击许可，消费后再次authorize或重复使用Batch被拒绝。

callback计数与输入计数分别保留，不能从一个False推断“绝对未触达”。回调前失败同样保守unknown，明确与真实已确认结果区分。native错误或取消后排空仍沿用已验收生命周期；不会为了报告失败强杀native工作线程。
