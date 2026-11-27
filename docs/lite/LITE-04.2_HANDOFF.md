# LITE-04.2 部分实现与 OCR 阻断交接

日期2026-11-27。**未完成、未Accepted，提交供架构审查与裁决。**
页面基线21ea28b；本报告对应的实现提交可用 `git log --oneline -- docs/lite/LITE-04.2_HANDOFF.md` 查询。

## 已落地接口

- `quiz.py`：纯 QuizPlugin、不可变QuizSnapshot及集中payload解码；按实际Maa图像尺寸生成字段ROI与有限尺度模板；每次17请求共用既有单图RecognitionBatch。题号为interaction_revision，内容signature排除倒计时。
- 完整题号/题目/四个互异且包含题目的选项/当前分数/选中态/确认唯一才发布targets。错误/缺失/歧义无目标，旧分数与best候选均不能补齐。`?`只读，其他通用插件命令拒绝，尚无Quiz CLI注册。
- `quiz_vision_bundle()`：原始包内资产经临时目录派生8..128px模板；上下文拥有临时目录。调用方须保持上下文到native关闭完成；未改Resource/Tasker所有权。
- 自制neutral/selected可见按钮标记，两种模板均保留来源；候选中心是未来可点击位置，ROI中心从未作为输入坐标。
- 页端事件记录修正为while裁剪，防止每次提交push两笔时历史突破256条。增加500次提交上限回归。

## 实际验证与证据

全部原始记录位于 `docs/evidence/LITE-04/04.2/`。

- 初始真实PNG原生OCR：probe-01，8字段同图读取，三次约0.342/0.192/0.204s；不是完整观察或≥1Hz证明。
- 真实Edge的DPR1/1.5/2 × raw/nonraw：edge-02原阈值5通过1失败；提高阈值后的edge-03六组失败且无执行目标。字体探针存在1→7误读。详见 `LITE-04_DESIGN_DEVIATION.md`，不能标成04.2通过。
- 最终edge-final再次保留六组拒绝，包括原始CDP PNG与实际送入Maa的BGR转RGB PNG；修正测试资源上下文顺序，临时模板保留到facade关闭完成。所有六组关闭released=True，原有Target保留。
- mode-probe记录真实Maa only_rec的两张失败PNG重放，非新Edge截图，不作为字体/DPR矩阵通过证据。
- 纯语义20个测试验证零/负/多位分数、倒计时去重、题号变化、错误/歧义拒绝、无旧值回退与通用写拒绝。
- 全量离线928通过、74 browser用例未运行（offline.txt）；包含现有新/旧架构回归，但不替代Quiz原生矩阵。随后新增的mode探针单独执行通过（只证明诊断流程），未篡改原计数。
- Ruff通过，mypy109源文件通过，wheel/sdist构建通过。全仓format发现主会话原有DESIGN.md代码块格式问题，保留原件；Python范围格式单独检查。
- 添加模板后页端真实回归1通过（page-regression，21.78s，含两次10秒自动换题）；Node新增500次提交验证事件历史始终≤256，engine.json同时保留原500轮数字覆盖。
- 独立已有clean安装环境强制安装本轮wheel，从C:/Windows/Temp以-I运行quiz_wheel_probe：site-packages导入、244模板、显式模型哈希校验、临时目录释放；不声称新建全空venv，也不声称此检查完成原生关闭验收。
- 模型沿用 `docs/lite/models/ppocr-v3-en.json` 的固定来源/版本/三文件SHA256，模型未放入wheel，无隐式下载。

## 未完成与恢复点

先由主会话裁决OCR偏差方案，之后完成04.2全部0..9、字体、80/100/125桌面缩放、
ROI/full、负例/重复候选、wheel原生生命周期与性能矩阵。本次不把它们标成完成。
04.3 LockedVisualPort/QuizAnswerFlow/CLI及04.4三分钟真实终端尚未实施。

既有高CPU3.26~3.97核和历史旧OpenCV access violation仍保留，未借本轮短测试宣布解决。
Accepted仅由架构主会话决定；README/PROJECT_CONTEXT验收状态未改。
