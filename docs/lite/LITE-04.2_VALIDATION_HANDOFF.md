# LITE-04.2a～c 补充验证交接（进行中，非Accepted）

基线lite@16f2119，执行2026-11-27架构裁决；04.3不实施。

## 04.2a 原生对照

`tests/lite/quiz_native_diagnostics.py`只调用既有Facade的JOCR/only_rec/逐数字JTemplateMatch。
自制字形由`generate_quiz_glyphs.py`中的原始坐标路径生成，CC0，20个normal/bold PNG，
`resources/quiz/glyphs.json`记录来源/尺寸/SHA256。不使用字体文件或截图裁剪制作生产模板。
Maa5.16.1本地Python Binding的JTemplateMatch接受template列表，但未承诺结果携带模板ID；
因此按十个独立请求保留资产身份，不从多模板best推断数字。

证据`docs/evidence/LITE-04/04.2-validation/a-native`与`a-cross`：各120条；20条为
历史两张图×5个模板尺寸×2个字重，100条为10数字×48/56/64/72/80高度×2字重。
历史det稳定6→空、1→7；only_rec两者正确。自制字形两种OCR及模板诊断top均100/100正确。
normal模板对bold的最小首二分差0.214388，同字重0.265704。这里top只做混淆统计，
没有选择答案/执行点击，也不将合成数据当作Edge验收。原始PNG、来源哈希、所有候选、
ROI、请求、时间、混淆表与完整释放结果均保留。

外置process监控记录真实PID，不使用venv启动器CPU冒充负载；a-native实际PID34580，
采样平均6.308核，峰值RSS215916544、Private702701568 bytes（包括初始化及全部实验）。
每条全流程均值0.155s，仅单字段对照，不能推断完整观察≥1Hz。cross均值0.167s。

复现：先配置BCA_OCR_MODEL，再运行`python -m tests.lite.stability_probe 新监控目录 --
python -m tests.lite.quiz_native_diagnostics 新证据目录`；设置BCA_CROSS_WEIGHT=1做跨字重。
脚本拒绝覆盖已有目录。后续必须在新Edge调参样本上冻结阈值，再用独立seed矩阵盲测。

04.2a提交：6cf43b4。

## 04.2b 真实页面适配与独立矩阵

页面仅将题目与四选项数字改为40×60px可见自制字形（normal/bold两种字重），有alt文本；
题号、时间、分数仍使用文字。没有改变随机/计分/10秒规则。常规字重模板同时支持粗体，
不从待识别图或DOM生成模板；启动核验原始字形SHA256，临时尺度模板上下文保留到native关闭。

校准b-calibration-01：宽ROI使only_rec输出标点，六组失败；02：紧ROI改善但det额外
检测空文本造成歧义；03：依裁决采用紧ROI only_rec+模板双路径，六组通过。
02/03短暂并发造成02的Target清理检查失败与性能干扰，完整失败日志保留，不作性能依据。
后续所有验收串行独占运行。b-parameters.json记录固定策略，登记文件在盲测进行中生成，
识别参数自盲测启动前即未再调整：多数字OCR阈值0.7；单数字only_rec保留全部置信结果，
必须为唯一单数字并与唯一≥0.9模板一致，模板首二差≥0.15；没有模板独立兜底。
同图67请求，共用原精确ObservationRef；模板候选定位按钮，仍禁止通用Quiz写命令。

独立未参与调参seed9173/60127/88219，各自覆盖DPR1/1.5/2×raw/nonraw且十个题目数字，
60127使用bold。b-blind-01：18组180次，180正确MATCHED、0错误MATCHED、180来源有效且
未过期，完整可用率100%；各位置OCR及十模板混淆表在summary.json。所有组原始PNG、Maa
实际输入PNG、完整请求/ROI/候选/nativeJSON、Frame/绑定、DOM独立oracle、耗时及关闭均保存。
监控真实工作PID31164，包含启动/资源派生在内平均3.467核、峰值RSS207704064、Private
687525888 bytes，不能与60秒持续观察直接混用。字形变化支持只承诺这两套自制资产，
不承诺任意字体。旧56px真实误读图片保持原样；当前56px系统字体替换另作为不支持负例。

b-zoom：独立seed55391，真实OS快捷键Ctrl+0/-/+，每次核验专属前台窗口；实际DPR比率验证
80/100/125%，每档十数字，共30/30正确。不是Emulation.pageScale模拟缩放。关闭前复原100%。
b-faults：模糊、低对比、遮挡、ROI偏移、重复字形、系统字体56px六例全部安全拒绝；同时
保存全图OCR诊断及PNG（仅诊断，不以多候选best赋予动作）。纯语义新增低置信OCR冲突、
模板近似、双候选、模板缺失拒绝测试；不把这些合成测试当作实际图像准确率。
真实matrix/zoom/faults全部released=True、pending0/readerFalse，原有Targets保留。

04.2b提交：a2e3a94。以上是限定矩阵结果，不代表任意窗口形状/缩放均受支持。

## 04.2c 持续性能：未通过

四轮独立进程串行运行，无其他本任务性能测试并发；每轮真实Edge观察至少60秒，
页面使用真实10秒时钟；来源失效、字段不全或原2秒时效超限均不计valid。
没有放宽max_frame_age、native关闭或一次授权规则。原始证据、完整每帧JSON/图片及
监控在c-*目录，汇总c-comparison.json。每轮仍保留原生失败断言，没有改为skip/xfail。

| 条件 | 观察数/秒数 | 有效数/Hz | total median/p95 秒 | 工作PID/平均核数 | 峰值RSS/Private bytes |
| --- | --- | --- | --- | --- | --- |
| 原生窗口raw，1386×1562 | 61 / 60.778 | 59 / 0.971 | 0.830 / 1.457 | 9156 / 4.784 | 193011712 / 671416320 |
| viewport 960×640 DPR1 raw | 24 / 61.546 | 0 / 0 | 2.442 / 2.725 | 34548 / 4.171 | 146960384 / 623521792 |
| 原生窗口nonraw，Maa720×811 | 24 / 61.518 | 0 / 0 | 2.485 / 2.668 | 34884 / 4.065 | 157364224 / 635895808 |
| 960×640，测试进程限制CPU0/1 | 27 / 60.589 | 0 / 0 | 2.159 / 2.228 | 2016 / 1.791 | 148668416 / 624631808 |

CPU/RSS列为外置采样的真实工作PID整个进程（含初始化与关闭）；观察时段capture/native/
parse/total的median/p95均在各report.json中单列，未混算为主机总CPU或venv启动器CPU。
首轮2帧过期；后三轮全部过期。nonraw另有全部24次确认模板未命中，首帧score0.893674
低于0.9，故NOT_FOUND无目标；四个选项模板仍约0.999。这里是矩阵外窗口形状/二次缩放，
不能用矩阵180/180掩盖它。其余轮次字段读数正确，但过期帧不能授权，也不算有效频率。
四轮无错误MATCHED；全部native按Tasker→Controller→Resource释放，pending0/readerFalse，
原有Target保留。CPU限制仅在诊断子进程生效，未加入产品或影响其他进程。

性能退化跨进程原因尚未定位，不能把后两轮慢帧简单归因于像素量、某个库或主机负载。
逐请求计时已加入c-affinity：8次OCR与59次模板均有累计成本；没有自行重写OCR/匹配器。
**结论：准确性限定矩阵达到门槛，但完整≥1Hz未通过，04.2不可解锁04.3。**
最小后续建议见LITE-04_DESIGN_DEVIATION.md新增章节，交主会话裁决。

## 分发、回归与证据

- 从不存在的`.test-artifacts/lite04-validation-clean`新建venv，仅安装本轮wheel[lite]；
  clean-install.txt保留依赖与固定Maa5.16.1安装记录。没有复用旧clean环境。
- 从C:/Windows/Temp以-I执行quiz_wheel_probe.py，导入确认来自site-packages；2524模板
  可定位、包内ocr-model.json与原manifest一致、外部模型三文件哈希验证，缺manifest拒绝。
  真Edge新截图与DOM独立oracle一致，本轮expired=False；native完整释放后临时目录删除，
  pending0/readerFalse。此一次通过仅证明分发/生命周期，不推翻60秒性能失败。
- `offline.txt`：933 passed、74 browser用例deselected；旧架构回归不替代新视觉验收。
- `edge-regression.txt`：真实页面及fixture ConPTY 10 passed、1 skipped（原有65秒fixture
  成本测试未显式启用）；覆盖quit/Ctrl+C/EOF/断开、输入失败/stop失败、过期及精确选择。
  原始CLI报告/transcript由本轮pytest-60目录原样复制到fixture-cli，页面证据page-regression。
- Ruff、Python范围format、mypy strict109源文件、wheel/sdist构建通过；证据原文保留。
- 原高CPU与历史OpenCV access violation仍未归因，不能由本轮未崩溃认定解决。

复现盲测：设置BCA_CDP_ENDPOINT、BCA_OCR_MODEL、BCA_QUIZ_BLIND=1及新的
BCA_QUIZ_EVIDENCE目录，执行pytest tests/lite/test_quiz_vision.py -q。
性能：`python -m tests.lite.stability_probe 新监控目录 -- python -m
tests.lite.quiz_edge_validation 新证据目录 performance`。可显式设置
BCA_QUIZ_VIEWPORT=960x640、BCA_QUIZ_NONRAW=1或BCA_QUIZ_AFFINITY=2复现对照；
各次应清除不使用的环境变量，不混用配置。zoom/faults替换最后一个mode参数。
保持失败断言，可复现当前未达标，而非承诺运行即通过。

本子步骤源码/证据提交可用`git log --oneline -- docs/lite/LITE-04.2_VALIDATION_HANDOFF.md`
定位；04.2c为完成实验与交接，不是功能Accepted。未实施04.3/04.4。
