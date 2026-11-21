# BCA-04.2 / Vision Engine & Integration 实施交接

2026-11-21。本阶段实现、测试和交接由本地工作区提供，等待架构主会话正式源码验收。包版本仍为 browser-cli-agent 0.2.0，PROTOCOL_VERSION=2。没有修改 Core、Browser、Runtime、Plugin System 的公开接口，也没有修改04.1的资产实现。

## 基线、范围与文件

实际 HEAD 为 main / `fe151645beaa7bfbaa4dcb19dc5499cbe48fdf01`，与任务书一致。开始时仅有用户未跟踪的04.2任务书和“下载 - 快捷方式.lnk”，均保留。没有修改项目总纲和根 README 的正式验收状态；当前交付为未提交 diff，未 commit/push。

以 `docs/md/BCA-04.2_Vision_Engine_Integration_Codex_Prompt.md` 为实施任务书，核对 PROJECT_CONTEXT、00～03 MAIN_SYNC、04.1 HANDOFF、ASSETS、INTERFACES、PLUGIN_SPEC、BROWSER、RUNTIME、ARCHITECTURE 与实际源码。仓库中未找到 `BCA-04_Vision_Assets.md`，按当前详细任务书和已提交接口实施，不伪称已读取外部共享文件。历史归档的旧提交号和“待验收”表述不覆盖当前总纲及源码基线。

主要文件：

- `src/bca/plugin_sdk/vision/{__init__,models,errors,decode,preprocess,matching}.py`：稳定导出、模型和边界、完整解码、ROI/缩放、评分和候选处理。
- `examples/vision_foundation.py`：独立临时资源、离线 MATCHED/AMBIGUOUS 及 CSS 映射。
- `examples/plugins/vision_fixture/`：可信本机插件包，包含 create_plugin 工厂、预热资产生成器及插件实现。
- `examples/vision_integration.py`：显式 CDP、独立目标、两主题/DPR/区域矩阵、性能和清理证据。
- `examples/vision_benchmark.py`：六组离线微基准及独立内存采样。
- `examples/__init__.py`、`examples/plugins/__init__.py`：统一示例包命名，避免 mypy 将共享辅助文件识别为两个模块。
- `tests/plugin_sdk/vision/`：解码、评分 oracle、输入、预处理、几何、固定数据集、性能报告结构、真实浏览器与生命周期测试。
- `docs/VISION.md`、本交接、`docs/BCA-04_MAIN_SYNC.md` 及三处SDK交叉链接；`docs/evidence/BCA-04.2/` 保存可随 diff 审核的实测 JSON。
- `pyproject.toml` 增加 vision extra，保留 assets extra 和基础依赖。
- `MANIFEST.in` 补齐源包中的示例插件manifest、Assets/Vision固定fixture、文档与04.2证据；wheel仍只安装src中的库，不把测试模板当作用户资产自动加载。

## 已定稿接口与算法

公开签名、字段与规则以 [VISION.md](VISION.md) 为准。新增 DecodedFrame、PixelRect、PreprocessMode、MatchOptions、MatchCandidate、MatchStatus、MatchResult、VisionTiming 及 VisionError/Input/Decode/MatchError，均位于 SDK 命名空间，不进入 Protocol codec。

`decode_frame` 用 Pillow verify+load 验证完整性，再用 OpenCV 解码到 RGB uint8；透明截图以 `(RGB*alpha+127)//255` 合成黑底。Frame引用保持同一对象，像素为 bytes 支撑的只读数组。限制16,777,216像素与128MiB编码数据，拒绝损坏、截断、16位、动画及尺寸/格式不符。

ROI仅限制搜索，输出回到原始Frame。缩放按两轴 floor(size*scale+.5)，模板缩小AREA、放大LINEAR，Mask线性插值后整数舍入，沿用Assets权重。GRAY使用OpenCV RGB2GRAY。最终CSS位置只调用匹配来源Frame的pixel_to_css，不叠加DPR或滚动。

评分使用TM_SQDIFF：`1-sqrt(SSD/(C*255²*sum(W²)))`，W=mask/255，非概率。分母float64；负SSD诊断并截0、非有限值报VisionMatchError；提案用float64像素块复核分数，修复完全匹配的float32消减误差。3×3峰值、每尺度有界扫描、同身份跨尺度NMS、不同身份锚点竞争，支持重复位置与同位置歧义。排序固定为分数降序、ID、变体、y/x、尺度；比较边界容差1e-9。

数量边界为每次1～256模板、1～16尺度；每变体最多max_proposals_per_variant（默认128），matches最多max_results（默认32）。歧义状态在输出截断前确定；歧义列表最多max(2,max_results)个候选，确保max_results=1时仍能展示竞争对。到达上限有诊断，不保证无限多目标的完全枚举。同一身份重复输入报错。

reason固定为 matched、below_threshold、template_larger_than_roi、ambiguous_candidates。best_candidate仅用于诊断，不能绕过歧义或Runtime授权。输入/解码/OpenCV失败有独立稳定code；没有修改Assets错误类型。

## 独立标签与正确性

`tests/plugin_sdk/vision/fixtures/expected.json` 保存76个场景。输入由固定种子、预设粘贴位置、Pillow缩放/编码生成，不调用被测matcher生成期望值。测试期间未根据算法输出回填标签。

| 组 | 正例 | 负例 | 结果 |
| --- | ---: | ---: | --- |
| RGB | 4 | 4 | 全部通过 |
| GRAY | 4 | 4 | 全部通过 |
| alpha/外部权重Mask | 4 | 4 | 全部通过 |
| 放大 | 4 | 4 | 全部通过 |
| 缩小 | 4 | 4 | 全部通过 |
| 非等比尺度 | 4 | 4 | 全部通过 |
| JPEG | 4 | 4 | 全部通过 |
| ROI | 4 | 4 | 全部通过 |

统一阈值0.96：32正例全部命中，32负例无错误有效命中；bbox和中心均与预设位置精确相同。6个歧义场景全部AMBIGUOUS、不任取竞争身份；6个双目标场景均保留两个位置。另有逐位置纯NumPy/标量oracle检查RGB/GRAY、无mask及0/64/128/255权重，map绝对误差容差2e-6，最高候选复核分数容差2e-8。

补充测试覆盖纯色/黑模板、阈值0/1和1e-9边界、平台候选上限、截断不隐藏歧义、非法输入、零权重缩放、负/非有限SSD、只读对象、缓存共享不被改写，以及DPR1/1.5/2下非等比Viewport和capture偏移的手工CSS真值。

## 真实Browser链路

实例为独立无头Edge，回环端点 `http://127.0.0.1:9341`，独立 `.test-artifacts/04.2/edge-profile-elevated`，仅创建/操作测试自己的data页面。没有使用个人页面或其他调试端口。

插件initialize创建临时Manifest/Profile及两套主题，预热AssetStore；observe借用标准CaptureProvider，经FreshnessCaptureAdapter获得真实Frame，以asyncio.to_thread执行匹配，返回含真实source_frame_id的PageState。Host保留原可信观察引用，生成带request_id的ActionBatch，经Runtime/Input执行，再观察验证页面状态变化。DOM只出现在外部测试，不进入插件业务识别。

完整性能矩阵为两主题×DPR1/1.5/2×完整/区域截图，每格1次预热、30次有效点击，共360条关联记录。JSON保存前后Frame ID、page/session、状态版本、request/batch/action ID、分数、实际截图尺寸与CSS落点。分别记录Action的浮点请求坐标和DOM MouseEvent的整数坐标，均与外部DOM矩形中心比较；不得把两种误差口径混用。360次成功，DOM与下一状态全部吻合，具体最大误差见verification.json。

9项真实视觉测试另覆盖：滚动、resize、导航、重绑导致旧引用STALE；可继续的原页面经新观察后成功点击；两位置只生成一次确定点击；注入同像素竞争模板后UNKNOWN/AMBIGUOUS且拒绝命令；取消/关闭等待真实线程释放；匹配异常不发布新状态。测试最终等待Host/Manager/Controller、关闭借用链外的实际Provider及Session，关闭自建Target并保留原Target，记录无剩余任务/请求。

原始浏览器启动在受限沙箱中遇GPU子进程权限崩溃，日志保留edge-stderr.log。自动审批后在沙箱外启动同样隔离的无头实例完成测试。首次组合试跑还发现示例缺少Catalog默认create_plugin工厂，已补齐并通过完整回归。这些失败没有作为通过样本计入360条记录。

## 工程验证与安装

实际环境：Windows 11 10.0.26200、Intel Core 5 220H、CPython3.14.7 AMD64、NumPy2.5.5、OpenCV4.14.0（wheel 4.14.0.94）、Pillow12.3.0、Edge157.0.4341.60/CDP1.3。pip实际解析并成功安装 `numpy>=2.4,<3`、`opencv-python-headless>=4.14,<5`，没有安装第二个cv2 wheel变体。其他Python/OS组合未测。

部署复现建议在应用环境锁定本次实测的 `numpy==2.5.5`、`opencv-python-headless==4.14.0.94`、`Pillow==12.3.0`；库的pyproject保留兼容范围。升级原生依赖后应重跑oracle、解码、固定标签和真实页面矩阵，不能沿用本次性能数字。

验证命令与最终结果索引见 [verification.json](evidence/BCA-04.2/verification.json)。关键命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,assets,vision]"
.\.venv\Scripts\python.exe -m pytest tests/plugin_sdk/vision -q -W error --basetemp=.test-artifacts/pytest-04.2-vision-final
.\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-artifacts/pytest-04.2-full-final
$env:BCA_CDP_ENDPOINT="http://127.0.0.1:9341"
.\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-artifacts/pytest-04.2-delivery
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe examples/vision_foundation.py
```

全量含04.1原127项Assets测试及既有上游测试。历史04.1的624/36仅是对比基线，不当作本阶段结果。当前新增视觉测试包括离线136项和显式CDP9项。

| 最终验证 | 实际结果 |
| --- | --- |
| Vision，无CDP | 136 passed / 9 skipped，11.73s |
| 全量，无CDP | 760 passed / 45 skipped，33.14s |
| 全量，显式隔离CDP | 805 passed / 0 skipped，71.19s |
| mypy strict | 88个源文件通过 |
| Ruff check / format | 通过，213个文件符合格式 |
| wheel / sdist构建、隔离安装矩阵 | 全部通过 |

所有skip均为未配置CDP时的显式浏览器测试；配置后45项全部执行。全量差异为上游624个离线+36个真实测试，新增136个离线+9个真实测试。没有测试失败，也没有跳过原有测试来取得通过数。

独立package-delivery-venv不继承开发环境：基础wheel安装后实际导入Core/Plugin接口，断言没有numpy/cv2；assets extra安装后断言没有cv2，并运行资产示例；vision extra安装后以`-I`和不同cwd运行完整视觉示例、检查导入路径确实在隔离site-packages。再从sdist构建wheel、强制重装并重复视觉示例。依赖通过本地wheelhouse安装，sdist构建使用隔离setuptools及工作区pip缓存；日志package-delivery.log、package-delivery-summary.json。另逐字节核验wheel中的Vision源码，并检查sdist包含原配置、两示例插件manifest、固定图片/标签和实测证据。

## 性能证据与边界

可审核原始数据：[offline.json](evidence/BCA-04.2/offline.json)、[browser.json](evidence/BCA-04.2/browser.json)。各阶段median/p95、完整样本和参数均在JSON，p95采用排序后ceil(n*.95)-1，不插值。decode包含Pillow完整性开销，postprocess包含float64候选复核。预解码输入decode_ms=0。

离线：640×480、32×24模板、每场景3次预热和30样本；比较全图/240×180 ROI、1/4模板、1/4尺度、mask与gray。浏览器：原图CSS640×480，实际截图尺寸按Frame记录；区域CSS240×180，DPR会改变像素数；2模板、3尺度、RGB、无mask。Capture与完整observe、Host到下次提交分别统计，不能把后两者算成纯Vision时间。

最终离线实测（毫秒，median / p95；复测时不并行运行pytest或安装）：

| 场景 | Vision total |
| --- | --- |
| 全图，1模板 | 25.88 / 27.33 |
| ROI，1模板 | 10.98 / 11.40 |
| 全图，4模板 | 96.68 / 100.58 |
| ROI，4尺度 | 31.63 / 35.24 |
| 全图，权重Mask | 31.71 / 33.59 |
| ROI，GRAY | 9.07 / 10.82 |

最终浏览器实测（毫秒，median / p95，每格30样本）：

| 主题 / DPR / 截图 | Vision total | Host到新提交 |
| --- | --- | --- |
| light / 1 / 全图 | 99.64 / 109.13 | 178.89 / 662.13 |
| light / 1 / 区域 | 19.77 / 27.23 | 89.44 / 105.46 |
| light / 1.5 / 全图 | 212.06 / 233.45 | 303.68 / 744.61 |
| light / 1.5 / 区域 | 42.29 / 56.95 | 125.92 / 650.20 |
| light / 2 / 全图 | 385.60 / 437.25 | 486.60 / 989.62 |
| light / 2 / 区域 | 65.36 / 68.74 | 156.93 / 620.13 |
| dark / 1 / 全图 | 100.88 / 113.69 | 181.99 / 649.80 |
| dark / 1 / 区域 | 20.11 / 26.47 | 92.61 / 103.55 |
| dark / 1.5 / 全图 | 215.88 / 253.39 | 311.71 / 796.78 |
| dark / 1.5 / 区域 | 43.09 / 58.43 | 112.41 / 601.13 |
| dark / 2 / 全图 | 413.43 / 607.27 | 621.98 / 1153.92 |
| dark / 2 / 区域 | 69.06 / 96.97 | 161.12 / 608.84 |

360条记录的Action浮点坐标最大中心偏差0.5 CSS px，DOM整数MouseEvent最大中心偏差1 CSS px，均经过外部真值断言。15.27秒持续观察完成53次提交，Python CPU时间4.25秒（约27.8%单核）；采样时动作pending始终0，工作集约62.97～70.14MB，最终所有在途任务关闭。采样包含不同在途阶段和采样器开销，不据此推断长期内存上界。内存采样器的ctypes结构类型固定在模块级，避免反复创建类型污染短循环分配统计。

高DPR全图多尺度明显超过默认100ms观察周期；区域截图可显著降低Vision计算，但Browser区域采集仍执行完整surface截图和裁剪，不保证减少CDP采集延迟。应在插件层预热、选明确尺度、缩小ROI、限制候选并卸载CPU工作，按实测选择业务观察频率。没有为追求表面10Hz修改已验收Scheduler语义。

另有101次离线内存循环与15秒真实持续观察，原始Python tracing、进程工作集、CPU秒数、任务数、待执行动作与Scheduler统计均保留。tracemalloc不含全部原生内存；PSAPI工作集是Python进程整体且不含Edge。短时任务/队列无遗留不代表长期无泄漏。持续观察慢于100ms时跳过tick，不积压补跑；真实截图存在尾延迟，报告不隐藏p95波动。

本地日志位于 `.test-artifacts/04.2/`：install.log、initial.log、dataset.log、vision-final.log、full-final.log、delivery-full.log、browser-tests.log、browser-campaign-delivery.log、benchmark-delivery.log、mypy.log、ruff.log、build-delivery.log、package-delivery.log、example.log。browser-smoke.log是修复后的成功试跑，GPU启动失败日志为edge-stderr.log；独立浏览器已按所有权清理，最终状态见verification.json。

## 风险与后续

当前测试是固定合成纹理和受控网页，未验证雀魂/WebGL实战素材、遮挡、动画、复杂光照、任意浏览器缩放或长时间压力。分数不可当作统计置信度。局部候选和数量限制有明确截断，不是无上限目标检测；接近阈值/歧义的业务策略须自行标注校准。

OpenCV可能使用原生线程，示例只演示单观察线程卸载及取消等待，不提供强制终止native计算。Frame ID是来源关联，不是业务页面事务锁，局部页面变化仍须遵守既有Runtime边界。没有需要修改公共Core API的架构提案；正式BCA-04验收与项目总纲更新留给架构主会话。
