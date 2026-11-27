# LITE-04.2 视觉实测偏差：请求架构裁决

2026-11-27；基线 lite@5547468，页面提交 21ea28b。本文不是新的产品设计。
**04.2 尚未通过；04.3/04.4 尚未实施。** 保持所有现有输入授权、关闭与 fixture 接口。

## 可复现事实

固定 MaaFramework 5.16.1、现有已校验 ppocr-v3-en，真实 Edge 自有测试页。
17 次原生识别共享一个截图：8 个字段 OCR、8 个选项状态模板、1 个确认模板。
模型/API 均能运行并完整释放；问题是 OCR 对单数字的输出，未证明是 Maa API bug。

| 证据目录（docs/evidence/LITE-04/04.2） | 实验 | 结果 |
| --- | --- | --- |
| edge-01、edge-02 | 原页面，JOCR 检测+识别，阈值0.3 | 完整六组合中5通过、1失败；DPR2/raw 下题目6被检测到，但识别为空、score0 |
| font-probe-01 | 仅测试脚本将题目72px改为56px，其他条件相同 | 前2组合通过；DPR2/raw 下真实1被识别为7，score0.472792；四选项恰好含7，字段自洽检查不能发现误读 |
| edge-03 | 原页面保持72px，提高字段阈值到0.9 | 六组合全部保守拒绝；正确的1亦只有0.45~0.83，无法靠统一高阈值达到可用性 |
| mode-probe/digit-modes.json | 重放上述两张原始PNG，同一图分别检测OCR与only_rec | only_rec输出6/1，但置信度仅0.422543/0.766014；只证明两张样本改善，不能作为完整验收 |

每个 Edge 条件保存 PNG、DOM 独立 oracle、原生 all/filtered/best JSON、候选框、耗时、Frame ID、绑定和关闭结果。没有发送视觉点击，没有 DOM 数据进入插件。失败日志未覆盖。

## 当前保守边界

QuizPlugin 草案使用0.9阈值；低置信度/缺失/歧义/不自洽均不发布执行目标。
它尚未注册 CLI，不能把测试通过的几个截图解释为已可安全答题。
原72px页面未被实验性56px覆盖。Bridge、Facade、Coordinator、CLI 无语义修改。

## 最小建议与待裁决项

建议先批准一条明确的数字验证方案，再继续04.2：保持 JOCR 读取所有数字，
对受控字体的题目/四选项追加原生 JTemplateMatch 数字一致性验证；only_rec 可作为
待验证的字段识别路径，但不直接将这两张样本或降低阈值作为通过依据。
模板必须来自自制、许可明确的字体/资产，真实候选与 OCR 一致且唯一才发布状态；
不读 DOM、不使用旧值、不改变图像来源及坐标授权，不减少 raw/nonraw/DPR/缩放门槛。
这会增加原生请求及CPU，须实测≥1Hz，不预先承诺性能达标。

请架构主会话裁决是否采用上述补充验证方案，或指定其他 OCR/受控字体方案。
没有请求放宽单次授权、native/CDP双确认、结算判断或10秒业务规格。
依照设计第8节“遇到…OCR识别率…问题…先…最小方案偏差”，在裁决前暂缓将此草案
用于两步动作和CLI，而不是把已知误读带入后续验收。

## 复现

PowerShell，明确已启动的自有 Edge 9341：

```powershell
$env:BCA_CDP_ENDPOINT='http://127.0.0.1:9341'
$env:BCA_OCR_MODEL='.maa-models/ppocr-v3-en'
$env:BCA_QUIZ_EVIDENCE='.test-artifacts/quiz-reproduce-new'
.venv/Scripts/python.exe -m pytest tests/lite/test_quiz_vision.py -q
```

当前提交默认0.9，预期复现保守拒绝（测试失败是待修问题，未标xfail）。历史0.3结果
见edge-01/02；如需复现历史参数，仅在隔离工作区将QuizPlugin.plan中OCR阈值设0.3。
设置 `$env:BCA_QUIZ_PROBE_FONT='56'` 可复现字体实验，运行后删除该环境变量。
重放模式对比：配置模型后运行 `pytest tests/lite/test_quiz_ocr_probe.py -q`；其pytest
成功仅表示完成实验及释放对象，识别是否正确必须查原始JSON，不能当作识别验收。
