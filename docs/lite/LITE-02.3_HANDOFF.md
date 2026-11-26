# LITE-02.3 · 真实 Edge 视觉集成与稳定性验证

日期：2026-11-26。基线 `lite@0dcb6de`；上游 LITE-02.2 P1 Accepted。
本报告提交架构主会话复核，**不自行宣布 LITE-02 Accepted**。

## 1. 范围及源码

- `src/bca/lite/fixture.py`：将已验收的纯 FixturePlugin 移入可安装包，原 example 路径保留重导出；新增显式 ROI 配置、`fixture_bundle()` / `fixture_html()`。插件仍只读 Maa 结果，不获取 DOM/CDP/native 对象。
- `src/bca/lite/resources/fixture/`：项目自制 96×64 模板、页面、最小 Bundle。原图生成器 `tests/lite/generate_fixture.py`；页面可改变可见数字、字体、字号、位置和候选数。点击回合自增，DOM 事件仅作测试 oracle。
- `examples/lite_vision.py`：显式 endpoint/model/manifest 的可运行 Edge smoke；只创建/关闭自有 Target。包内资源的 as_file 上下文保持至 native 关闭。
- `pyproject.toml`：包内素材纳入 wheel；psutil 仅加入 dev 监控依赖。`MANIFEST.in` 补入模型来源清单与许可文本，模型二进制仍不进入 wheel/sdist。
- `_native_vision.py`：stop Job 成功后，允许在原 owner worker 上最多等待 1 秒的 idle 状态收敛。仍须 `running=false` 才 Destroy；失败、异常、超时继续保留依赖。未改变 unknown/no-retry、精确 ref、单次授权或 Destroy 异常隔离语义。
- `tests/lite/test_real_vision.py`：真实矩阵、桌面缩放、故障退役、持续观察；阶段计时仅在测试子类中采集，无新增 Runtime/调度框架。
- `stability_probe.py` / `stability_workload.py` / `summarize_stability.py`：独立进程、混合顺序、逐 PID 原始采样与可再生成汇总；`wheel_probe.py` 验证安装资源与模型拒绝路径。

## 2. 真实 Edge 结果

原始目录：`docs/evidence/LITE-02/02.3/`。`environment.json` 保存版本、模型清单及素材 SHA256。

| 条件 | 实际结果 / 证据 |
| --- | --- |
| DPR 1/1.5/2 × raw/nonraw × 全图/ROI | 12 组，最终 `final-edge` 的 matrix + 4 个退役用例共 **5 passed**；每组安全点击由 Maa 唯一候选生成，并验证 DOM button 命中及 OCR 123→124 |
| 图像坐标 | 初始模板左上角相对 DOM oracle 的最大误差 0 CSS px；含 nonraw 尺寸变换，不把 DOM 坐标传入输入 API |
| 字体/字号/位置 | Arial 40、Georgia 48、Courier New 56；目标移动至 x=100；36 个字体样本中 33 MATCHED 且文本正确，3 AMBIGUOUS 且拒绝写入；覆盖 0..9、-1/-20/-305、12/345/6789 |
| 全图 OCR 限制 | 5/12 初始条件将图案额外识别为文本，安全拒绝；测试显式切换 ROI 后重新截图恢复。另 3 个字体样本全图歧义。没有选 best、改 OCR 文本或降低阈值来制造成功 |
| 正负/歧义 | 12 组均有目标消失→NOT_FOUND、双候选→AMBIGUOUS、恢复；不确定时零新增输入；每组只允许一次受控点击 |
| 来源和命令 | `?` 确认新 source；同内容不通知；旧 Batch 点击拒绝；回合变为124后旧 `click 123` 拒绝。共享门从新观察覆盖到输入后观察 |
| 真桌面页面缩放 | `zoom-02` **1 passed**：80%/100%/125%，实际 DPR 1.2/1.5/1.875，visualViewport.scale=1；最大定位偏差约0.4695 CSS px，均安全点击并核验DOM |
| 失效/取消 | 导航、关闭自有页面、受控 capture 延迟导致 bridge timeout、在途截图取消；全部拒绝旧批次，input_outcome=not_attempted，关闭 released=True |
| 收尾 | 所有成功场景仅关闭自有 Target，原有 Targets 保留；pending=0、reader=false。延迟注入是测试 Provider 延迟，**不是新增真实网络 ACK-loss 复验**；后者沿用 LITE-01 证据和 P1 离线回归 |

原始 `report.json`/`observations.jsonl` 保存每次 source frame ID、binding、Maa 图像尺寸、原生 job/reco/status/hit、候选框/分数/文本和原始详情。输入 PNG 与 Maa resized PNG、字体 PNG 均为自有 fixture。尺度模板从固定原图及测得的图像/viewport **尺寸**生成，绝不裁取待识别截图当模板。

## 3. 持续观察

`sustained-01`：真实 Edge，DPR1/raw/ROI，周期0.75s，max_frame_age=5s，独立进程；未导入 Python cv2 或旧 Vision。

- 实测 **185.0128 秒，245 次完成，239 次有效，1.2918 有效 Hz**；6 次 NOT_FOUND 均在计划的80–85秒目标消失期间。没有 ERROR/歧义/过期；最长连续有效134次，有效率97.55%包含主动负例。
- 在40秒变为456；80秒目标消失；85秒恢复789；120秒 `click 789` confirmed，DOM唯一button事件，视觉后置790。
- 5 条内容变化通知，0 丢通知、0 skipped tick；3063 次独立 asyncio 心跳。245个不同 frame ID；结果始终绑定本次图像。
- 总耗时 median/p95 **139.71/187.32 ms**；capture **76.93/95.39 ms**；两项原生识别 **61.75/104.95 ms**；纯业务解析 **0.0173/0.0310 ms**。
- 完成间隔 median/p95 **761.26/805.44 ms**。此间隔含一次命令的前/后观察，不把它称为纯周期调度间隔。
- 结束 Tasker/Controller/Resource 句柄均为空，Destroy 顺序正确；专用 `bca-maa-vision` worker 数0，released=True；Target/pending/reader检查通过。

`process.json` 每约0.25秒保存进程树 RSS、PrivateBytes、CPU累计秒、线程/句柄、系统可用物理内存和 commit/limit。Windows venv 启动器与实际 Python 子进程分开记录，隔离 Edge 另标 scope。RSS 按树求和含共享页重复计数，不等于独占物理内存。

| 整个测量进程窗口（约185.97s） | 应用进程树 | 隔离 Edge 进程树 |
| --- | ---: | ---: |
| 平均 CPU（单逻辑核=100%） | 325.63% | 5.64% |
| 峰值 RSS | 164.60 MiB | 619.72 MiB |
| 峰值 PrivateBytes | 619.14 MiB | 338.15 MiB |

系统可用物理内存最低约2703.95 MiB，峰值提交约26.57 GiB，提交限制约34.50 GiB。原始精确字节和其他运行结果见 `summary.json`，可从原始记录重算。

**性能限制：** 当前 CPU 成本约3.26个逻辑核，不宣称已达成低CPU目标，也未证明成本来自某一个 native 组件；本阶段不擅改 Maa/ONNX 线程配置。Maa/DLL 全局线程或分配器可在包装对象关闭后留存至进程退出；不将进程 RSS 未回到导入前解释为对象未释放，也不把句柄清空当作无泄漏的无限期证明。

## 4. 历史 access violation 与本次关闭发现

原始历史 `02.1/offline-diagnostic.txt` 中旧 `cv2.imdecode` 4096×4096边界崩溃仍未归因。此次分别在 **3轮×4种独立进程配置**中运行：

| 每轮配置 | 实际执行 |
| --- | --- |
| legacy | 旧 dataset/decode 92 passed（含 exact_limit） |
| maa | 新 Maa native/业务链70 passed；cv2/旧Vision均未导入 |
| legacy-maa | 同进程先92后70 passed |
| maa-legacy | 同进程先70后92 passed |

12个 `final-stability-*` 进程 exit_code=0；每个保留完整命令、PID、起止时间、包/native版本、stdout/stderr和运行前/后及期间采样。旧路径峰值RSS约199–201MiB，新Maa约174–176MiB，混合次序约193–259MiB。本次最小可用内存约1669MiB，高于历史约449MiB快照；没有通过关闭用户程序、删除测试或降阈值制造通过。结论仅为**这些条件下未复现**，不能称历史崩溃已修复/已证明OOM。

初次 `stability-maa-legacy-1` 在**尚未导入旧 Vision**的 Maa 阶段出现：stop succeeded，但紧接着 running=true，旧保护正确返回 released=False，未Destroy。后续同输入100轮关闭探针无复现（`stop-settlement-01`）；因此不武断认定具体调度竞态根因。新增 bounded idle 等待允许状态收敛，保持无法证实 idle 就保留句柄的规则。新增暂态 fake状态回归与原有持久running/failed/exception回归均通过；三轮矩阵重跑正常。

## 5. 分发、质量与原始失败

- 全新 venv 完整安装 wheel[lite]（未使用 system-site-packages/开发环境依赖），pip check；从系统 Temp cwd 导入 site-packages。
- `wheel-probe-final.txt`：包内Resource真实加载，Template框(60,50,96,64)、OCR123；无模型→ERROR、缺目录拒绝、同长度篡改keys触发SHA256拒绝；所有原生对象释放。
- `wheel-edge.txt`：同一干净安装从系统Temp目录执行example，真实视觉点击confirmed、OCR124、DOMbutton；关闭released=True。模型与来源manifest通过显式绝对路径提供，无隐式下载。
- 最终全量离线 **878 passed / 57 deselected / 91.06s**（浏览器用例按标记排除）；Ruff通过、266文件格式检查通过、mypy strict 101文件通过；wheel/sdist构建通过。`package-integrity.json`核对最终wheel全部lite包内容与已测试安装逐字节相同，sdist包含来源manifest与许可证且无模型二进制。

失败原件全部保留：edge-01端口参数被复制换行导致拒绝连接；edge-02/03暴露全图OCR图案歧义，测试调整为明确拒绝及显式ROI恢复而非掩盖；edge-04测试同步依赖rAF，隐藏窗口时超时，改为布局刷新后截图；wheel-probe首次替身缺bound_page_id导致ctypes诊断，修正后独立final日志无此异常。初期监控仅采到Windows启动器的记录不用于工作进程资源结论。zoom-01监控误把renderer也当browser root，在实际测试启动前拒绝，修正为排除--type子进程。

## 6. 复现

先按现有模型说明显式准备模型，用户启动隔离 Edge 9341；桌面缩放期间保持自有测试窗口可见，helper只在核对唯一标题/前台HWND后发快捷键。

```powershell
$env:BCA_OCR_MODEL = (Resolve-Path .maa-models/ppocr-v3-en).Path
$env:BCA_CDP_ENDPOINT = 'http://127.0.0.1:9341'
$env:BCA_REAL_VISION_EVIDENCE = 'NEW_OUTPUT/data'
$env:BCA_LONG_RUN = '1'
$env:PYTHONIOENCODING = 'utf-8'
.venv/Scripts/python.exe -m tests.lite.stability_probe NEW_OUTPUT -- .venv/Scripts/python.exe -X faulthandler -m pytest tests/lite/test_real_vision.py -q
# 为隔离频率测量，交付时 sustained 与矩阵/zoom 分进程运行，详见各process.json.command。
.venv/Scripts/python.exe -m tests.lite.stability_probe NEW_STABILITY_OUTPUT -- .venv/Scripts/python.exe -X faulthandler -m tests.lite.stability_workload maa-legacy
.venv/Scripts/python.exe -m tests.lite.summarize_stability docs/evidence/LITE-02/02.3
```

监控输出目录必须不存在，避免覆盖失败现场。其他顺序用legacy、maa、legacy-maa。正式离线回归移除BCA_CDP_ENDPOINT并使用`pytest -m 'not browser_integration' -q`。

## 7. Git 与审查边界

源码、测试及原始证据提交：`5b107e4`（`test(lite): verify Edge visual integration and native stability`）。本报告与执行计划另行文档提交，准确文档SHA见`git log`。仅在lite开发，未push、未改main。新增的上游验收书保持原样，未混入本阶段源码提交。

请求架构主会话审核：真实视觉与安全语义、bounded idle等待、性能成本与全图OCR限制、历史崩溃未归因这一证据边界。README及BCA_PROJECT_CONTEXT的LITE-02整体状态保持不变，等待正式验收。
