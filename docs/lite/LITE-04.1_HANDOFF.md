# LITE-04.1 Quiz 页面与受控资源

执行主会话已批准的`LITE-04_DESIGN.md`，基线lite@5547468；没有重新起草产品设计。

- `resources/quiz/page.html`可本地打开，`quiz.js`原始自制页面引擎，无CDN/外部字体/图片/网络/存储依赖。
- 960×640逻辑画板等比居中适应viewport；题号、剩余时间、题目、四项、选中双边框+绿色+勾、确认、分数均可见。资源由`quiz_bundle()`管理生命周期，`quiz_html()`可生成独立data页；纳入wheel。
- seed使用32位确定性LCG，下一题从其他9个数字直接采样，无无限重试；四项互异且恰好一个正确，位置变化。score/round采用BigInt，回合号最小六位、容量边界扩位、不回绕。长分数保留完整文本并可滚动，不能把屏外内容声称视觉可读。
- 每轮10s基于performance.now，题目生成与DOM发布同步；timer及每次select/confirm入口都先检验到期。选择保存selectedRound，确认原子检验轮次/选择/未提交；正确+1/错误-1立即新轮、清选择、重新计时。页面handler携带安装时的可见round，旧handler不能跨轮结算。
- 只有显式`#test=1`启用quizTest与模拟单调时钟；生产模式没有quizTest对象。业务插件尚未实现，不会将oracle接入插件。

证据`docs/evidence/LITE-04/04.1/`：

1. `node tests/lite/quiz_page_probe.cjs`的engine.json：500轮覆盖0..9与4个正确位置，9999/10000ms边界、选择不计分、重复确认/旧轮拒绝、16组正误/负数/多位/大整数、999999→1000000以及逆时钟拒绝。
2. `edge-02`实际Edge：DOM选择/确认、截图选中态、正误分数、过期handler无效、0/-1/-20/-305/12/345/6789截图、回合扩位；另真实时钟跨两次10s自动换题，题目数字改变且无test对象；原有Targets保留，pending0/readerfalse。
3. edge-01失败原文保留：仅改变data URL fragment是同文档导航，测试时钟仍存在；测试切换改为先about:blank再新文档，无产品语义变更。
4. Ruff/format、mypy108文件、wheel/sdist；独立安装异cwd包内资源可访问。

本阶段只验页面状态与资源，不冒充Maa识别或视觉点击验收。源码SHA见本子阶段提交；下一步04.2将用真实Maa验证各字段与模板，并保留OCR限制/性能测量。未修改旧Bridge/Facade/Coordinator/关闭语义；整阶段仍待主会话验收。
