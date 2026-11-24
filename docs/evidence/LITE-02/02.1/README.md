# LITE-02.1 原始证据

环境：Windows 11、Python 3.14.7、maafw Python/native v5.16.1、NumPy 2.5.5、Pillow 12.3.0；固定 OCR 模型见 `docs/lite/models/ppocr-v3-en.json`。全为**真实 DLL + 受控图片/模拟 Browser Provider**，不是 Edge 识别或 LITE-02.3 验收。

## 最终复现

```powershell
$env:BCA_OCR_MODEL = (Resolve-Path .maa-models/ppocr-v3-en).Path
$env:BCA_VISION_EVIDENCE = '.test-artifacts/vision-new-evidence'
.venv/Scripts/python.exe -m pytest tests/lite -q -W error --basetemp=.test-artifacts/vision-new
Remove-Item Env:BCA_VISION_EVIDENCE
.venv/Scripts/python.exe -m pytest -q -W error --basetemp=.test-artifacts/vision-all-new
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m build
```

选择新的证据目录与 basetemp，保留既有失败记录。无需 CDP 端点，本阶段没有发送浏览器输入。

| 原始记录 | 含义 |
| --- | --- |
| `final/`、`lite-native-final.txt` | 最终 58 个新增测试 + 24 个原有 native/桥接测试通过，5 个 Edge 用例 skip；82 passed / 5 skipped，21.89s |
| `offline-with-model.txt` | 全仓库 844 passed / 50 skipped，77.79s；旧回归只作兼容性证据 |
| `no-model-env.txt` | 不设置模型环境变量：36 passed / 22 skipped，2.35s；没有静默下载 |
| `mypy.txt`、`ruff.txt`、`format.txt`、`build.txt` | 96 源码文件 strict 通过；Ruff、格式、wheel/sdist 成功 |
| `wheel-install.txt`、`wheel-foreign-cwd.txt` | --no-deps 独立 target 安装，离开仓库 cwd 后确认从该安装目录导入及显式模型校验；复用 .venv 依赖，不冒充全新依赖环境测试 |
| `api-probe.txt` | 最初 direct/Pipeline Template/OCR 真实结果形状探针 |
| `run-01.txt` | pytest 参数误用保留名 request，收集失败 |
| `run-02.txt` | 版本 guard 忽略 distribution 返回 v 前缀，46 failed / 3 passed；后允许精确 5.16.1/v5.16.1，未放宽版本范围 |
| `run-03/`、`run-03.txt` | 正负例 Job 语义假设失败，11 failed / 38 passed；实际直接识别无命中仍 succeeded |
| `run-04/`、`run-04.txt` | 中间版本 53 passed |
| `run-05/`、`run-05.txt` | Pipeline 负例 recognition=None 的读取假设失败，2 failed / 55 passed |
| `run-06/`、`run-06.txt` | 修正探针后的 57 passed；最终再加 OCR 双候选/only_rec 用例 |
| `offline-interrupted.txt` | 名称来自疑似停滞时的归档操作，实际与 offline-with-model 同为完整成功日志，未成功终止任何进程 |
| `offline-diagnostic.txt` | 后续 -vv / faulthandler_timeout=25 诊断复跑，在旧 OpenCV decode 出现 access violation，无完整成功结论 |
| `memory-after-diagnostic.json`、`legacy-recheck.txt` | 诊断轮次后低可用内存快照；旧 dataset/decode 单独重跑 92 passed，6.82s，exit=0；不足以确定原异常原因 |

`final/template-*`：10 个正例（不同位置）与 10 个负例（不同文字），各 full/ROI 两次识别共用同一个截图/ref。`final/ocr-*`：0～9、-1/-20/-305、12/345/6789 的 full/ROI 文本与框；另有双候选、only_rec。template 阈值0.9、OCR阈值0.3只适用于这组受控 fixture，不外推真实字体/缩放。

`final/*Probe.json`：正例 Pipeline 单截图；`*Probe-negative.json`：有界超时的 Pipeline 可重试截图，失败节点可没有 recognition，明确 authorized_batch=false。

`final/native-missing-model.json` 说明缺模型也可能 native succeeded/hit=false；生产适配先校验/加载模型，返回 ERROR，不把此情形当合法无文字。`source-*`、`cancel-*`、`destroy-retry`、`start-*`、`lifecycle` 覆盖来源、超龄、取消、释放和部分失败。

所有原始日志按 UTF-8/LF 保存，去掉行末空白；没有删除失败内容。测试图和模型许可见 `docs/lite/models/README.md`。
