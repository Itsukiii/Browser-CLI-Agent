# BCA-lite CLI 使用与边界

安装构建的 wheel：`python -m pip install 'browser_cli_agent-0.2.0-py3-none-any.whl[lite]'`。
入口为 `bca-lite` 或 `python -m bca.lite`；Windows PowerShell / Python3.14 为本阶段实测平台。
无终端环境可使用 `--check`、`--list-targets`、`--once`，交互模式明确拒绝重定向输入输出。

## 启动

先由用户启动独立 Edge/CDP，CLI不会自动启动或关闭浏览器进程。模型按
`docs/lite/models/README.md`显式准备，模型不含于wheel，不自动联网下载。

```powershell
bca-lite --help
bca-lite --endpoint http://127.0.0.1:9341 --list-targets
bca-lite --config configs/lite.example.toml --check
bca-lite --config configs/lite.example.toml --target EXACT_ID
# 或不传target，在终端列出ID后输入完整ID；空输入取消。
bca-lite --config configs/lite.example.toml
# 显式创建受控页面，退出只关闭这张自建页：
bca-lite --config configs/lite.example.toml --create-fixture
```

仅支持已安装内置`--plugin fixture`，不扫描插件目录、不导入任意模块；后续业务插件按审查扩展。
其包内模板是固定尺寸测试素材，只适合对应fixture页面。CLI对自建fixture设置640×400/DPR1；
选择已有页面不改DPR、缩放或尺寸，因此尺度不符可NOT_FOUND，不会猜测坐标。

TOML为单层，字段：endpoint、target、plugin、model、manifest、interval、callback_timeout、
max_frame_age、log_level、roi。未知字段/类型、NaN/无穷、非正时间拒绝；模型与清单成对给出。
model/manifest相对配置文件目录；命令行路径相对当前目录；CLI显式参数优先，`--no-roi`关闭ROI。
ROI默认开启，用fixture上半图定位按钮、下半图OCR。使用全图时可能将图案识别为额外文本，歧义拒绝点击。
Endpoint仅允许loopback HTTP origin，不接收凭据或query。目标列表仅显示ID/type/host，不打印页面标题或完整URL。

## 交互

| 输入 | 行为 |
| --- | --- |
| help | 显示命令 |
| ? | 等待Coordinator串行门，拍摄真实新截图，显示本次Frame ID与状态 |
| click 123 | 新观察必须仍是可见回合123、唯一视觉目标，才授权一次点击；随后再观察 |
| stop / resume | 排空并暂停周期工作 / 显式恢复同一有效组合；不在断线后重建 |
| quit / exit / EOF / Ctrl+C | 停止接收，取消在途命令并等待native排空，再完整关闭 |

输入行可编辑，状态只在内容变化时显示；latest变化提示有界合并，不无限保存截图。
最多1条在途命令，忙时新提交直接提示Busy并拒绝，**不排队**；help/退出仍响应。
粘贴多行也逐次遵循该规则，不能当作动作批处理。单次提交限1024字符；输出转义终端控制字符并截断超长内容。
EOF/退出不会保证完成之前的命令；若已发出输入则可能生效，不能据退出自行重发。

MATCHED/NOT_FOUND/AMBIGUOUS/ERROR、expired、当前视觉revision、Frame与诊断分别显示。
confirmed仅表示native和CDP确认一致，不等于一般网页业务结算成功。
unknown即退役组合，禁自动重试/重连/换Target。过期、失效或旧回合输入显示Rejected。

## 关闭和诊断

CLI只借助Coordinator运行；关停核对CloseReport，stop失败最多追加2次close尝试，不重发输入。
无法确认native释放或Destroy不确定时，以退出码3终止这个CLI进程，保留依赖至进程结束，不让析构重试未知指针。
此情况可能留下CLI创建的浏览器页，需要用户显式处置；不会关闭别的页面。
正常释放后按Input→Capture→自有Target→Session顺序关闭；打印released/pending/reader。
退出码0为正常；配置、连接、清理诊断等错误2；未确认native释放3；外部SIGINT取消130。
prompt内部Ctrl+C按正常安全退出处理。重复外部SIGINT不会绕过排空；native永久卡死时仍可能无法退出，线程不能强杀。

Python日志等级由log_level控制，交互期间最多保留16条待显示诊断，满时丢最旧诊断（不影响命令结果）。
Maa原生stdout会绕过编辑器，CLI启动时用固定5.16.1的`Tasker.set_stdout_level(Off)`关闭；
业务/资源错误、unknown和CloseReport仍显式输出。没有默认持久日志/命令历史；受控测试的transcript仅保存自有fixture。

LITE-02实测约3.26逻辑核的CPU成本、全图OCR歧义、旧OpenCV access violation未归因继续保留。
本CLI不导入旧Vision；不声称这样就修复了历史崩溃。进一步性能治理留待LITE-06。
