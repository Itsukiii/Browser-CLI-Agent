# LITE-02.3 原始证据索引

结论、限制、源码接口见 `docs/lite/LITE-02.3_HANDOFF.md`。

- `final-edge/`：最终 DPR/raw/ROI 矩阵和4类退役，5 passed；169个矩阵观察、7个退役观察。`data/matrix/`含受控页面及Maa返回图像/字体PNG。
- `zoom-02/`：真实桌面80/100/125%，1 passed；actual DPR与CSS定位误差可复查。
- `sustained-01/`：185.01秒/245完成/239有效/最长连续有效134次，1 passed；独立应用及隔离Edge进程树监控。
- `final-stability-{legacy,maa,legacy-maa,maa-legacy}-{1,2,3}/`：12个不同新进程；同进程混合由同一个workload脚本依次调用pytest。每个stdout记录实际工作PID（可不同于Windows venv启动器PID）、版本和各阶段资源。
- `final-offline/`：最终878 passed、57个browser_integration按标记排除；完整输出及进程采样。
- `close-regression.txt`：12 passed，包含stop失败/仍运行/异常不Destroy及暂态idle收敛。
- `stop-settlement-01/`：修订前同输入100轮无复现的探针。不是永久排除竞态的证明。
- `wheel-probe-final.txt`、`wheel-edge.txt`：全新安装，从系统Temp cwd执行，分别为原生合成图和真实Edge。
- `package-integrity.json`：wheel/sdist SHA256，最终wheel与已测安装的全部lite文件逐字节比对；source archive模型manifest/许可证存在，无模型二进制。
- `ruff.txt`、`format.txt`、`mypy.txt`、`build-final.txt`、`clean-pip-check.txt`：最终静态/构建/安装验证。
- `environment.json`、`browser-version.json`：Python3.14.7、Maa Python/native5.16.1、Edge158.0.4370.33、依赖/资源来源与哈希。
- `summary.json`由`python -m tests.lite.summarize_stability docs/evidence/LITE-02/02.3`重建，原始数据不被替代。CPU为单核100%，应用包括venv启动器及实际子进程，Edge单独scope；RSS树求和有共享页重复。

## 保留的诊断/失败尝试

`legacy-01`、`stability-*`初期monitor仅采Windows启动器，不能用于工作进程资源结论。
`stability-maa-legacy-1`是Maa阶段stop succeeded但running=true的失败，旧Vision尚未导入。
`edge-01`端口拒绝；`edge-02/03`全图OCR额外候选；`edge-04`测试rAF等待超时，完整关闭；`edge-05`改同步方式后的5 passed，后续final-edge增加坐标误差和逐帧日志。
`zoom-01/monitor-start-failure.txt`是根据工具输出保存的监控启动错误说明（没有pytest输出，不伪作测试运行日志）。
`wheel-probe.txt`首次替身漏UUID属性的ctypes警告，随后修正并保留单独final记录。
`build-preliminary.txt`、`build.txt`、`ruff-preliminary.txt`是开发中记录，不作为最终质量证明。
日志默认UTF-8；最早edge-01可能包含系统代码页异常文本，保留原字节。

## 命令与条件

所有受监控运行的 `process.json.command/start/end/exit_code/cwd` 是实测值。原始采样包含单调时钟、PID、RSS、private commit、CPU秒、线程/句柄、系统available/commit/limit。

共同显式配置：

```powershell
$env:BCA_OCR_MODEL = (Resolve-Path .maa-models/ppocr-v3-en).Path
$env:PYTHONIOENCODING = 'utf-8'
# 只有Edge测试设置：
$env:BCA_CDP_ENDPOINT = 'http://127.0.0.1:9341'
$env:BCA_REAL_VISION_EVIDENCE = '<本次新建输出目录>/data'
# 只有sustained设置：
$env:BCA_LONG_RUN = '1'
```

stop-settlement-01额外设置`BCA_STOP_ROUNDS=100`和`BCA_VISION_EVIDENCE=.../data`。默认离线回归stop探针为10轮。
OCR目录、manifest分别为工作目录下`.maa-models/ppocr-v3-en`、`docs/lite/models/ppocr-v3-en.json`，sha在environment.json。

干净安装命令：`python -m venv .test-artifacts/lite023-clean`；该环境`python -m pip install 'dist/browser_cli_agent-0.2.0-py3-none-any.whl[lite]'`，完整联网依赖安装日志`clean-install.txt`；更新本包用`--no-deps --force-reinstall`，日志`clean-reinstall-final.txt`。

异cwd探针使用绝对解释器`D:/Project/BCA-lite/.test-artifacts/lite023-clean/Scripts/python.exe`，cwd=`C:/Users/wutong/AppData/Local/Temp`：

```text
D:/Project/BCA-lite/tests/lite/wheel_probe.py D:/Project/BCA-lite/.maa-models/ppocr-v3-en D:/Project/BCA-lite/docs/lite/models/ppocr-v3-en.json
D:/Project/BCA-lite/examples/lite_vision.py --endpoint http://127.0.0.1:9341 --model D:/Project/BCA-lite/.maa-models/ppocr-v3-en --manifest D:/Project/BCA-lite/docs/lite/models/ppocr-v3-en.json
```

这两个文件是执行入口；实际bca代码与fixture只从site-packages加载，输出包含解析路径。没有导入仓库tests helpers或开发环境依赖。模型/manifest为显式外部文件，不属于wheel内容。
