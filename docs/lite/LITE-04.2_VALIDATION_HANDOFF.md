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

04.2b/04.2c结果将在后续独立子步骤提交补充。现阶段不宣布准确率/可用率/频率验收完成。
