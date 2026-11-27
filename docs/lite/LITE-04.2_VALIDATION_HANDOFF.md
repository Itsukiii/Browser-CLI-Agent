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

04.2c性能/干净wheel与最终回归仍待执行，尚不宣布功能Accepted。
