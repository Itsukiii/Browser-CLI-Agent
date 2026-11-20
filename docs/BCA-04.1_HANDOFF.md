# BCA-04.1 / Asset Foundation 实施交接

2026-11-20。04.1 已实施并完成本地验证，提交本子会话审阅；未宣称整个 BCA-04 已验收。包 `browser-cli-agent 0.2.0`、`PROTOCOL_VERSION=2` 不变，没有修改已验收 Core/Browser/Runtime/Plugin System 公共接口，未 commit/push。

## 实际基线与来源

当前分支 main，HEAD `477c443e0adfd726a9cb77b1093616ed30529ec0`。任务书记录起点为 `3ac8078a5fff6506a36e61f6d3d7286f53202771`，本轮采用更新后的实际源码。初始工作区仅有用户修改的 `docs/md/BCA_PROJECT_CONTEXT.md` 和未跟踪的 04.1 任务文件；均保留，不修改总纲、根 README 或既有阶段归档。

实际参考：

- `docs/md/BCA-04.1_Asset_Foundation_Codex_Prompt.md`，作为本阶段具体规则。
- `docs/md/BCA_PROJECT_CONTEXT.md` v0.5。
- `docs/md/BCA-00_MAIN_SYNC.md`（不在 docs 根目录）。
- `docs/BCA-01_MAIN_SYNC.md`、`BCA-02_MAIN_SYNC.md`、`BCA-03_MAIN_SYNC.md`。
- `docs/INTERFACES.md`、`PLUGIN_SPEC.md`、`ARCHITECTURE.md`，以及协议、错误、插件、SDK预留入口、pixel_fixture和既有SDK测试。

仓库和已检索本机项目位置中未找到 `BCA-04_Vision_Assets.md`，未伪称已阅读；本次详细提示词已明确04.1的数据格式、选择规则、缓存和验收范围，因此据此实施。未创建整个阶段的 BCA-04_MAIN_SYNC.md。

## 文件与依赖

新增 `src/bca/plugin_sdk/assets/{errors,models,paths,manifest,profile,loader,cache,store}.py`，更新根包 __init__.py 统一导出。paths 独立封装根目录、身份检查和读取边界，其他模块分别负责格式、选择、解码、缓存与生命周期。

新增 `tests/plugin_sdk/assets/`：Manifest、Profile、loader、路径、cache、store、回归测试共127项；fixtures保存固定RGB/RGBA/L/LA/调色板/JPEG、外部mask和独立expected.json。新增 `examples/asset_foundation.py`，自建临时资源、两Profile演示，不依赖浏览器或仓库测试夹具。

新增 [ASSETS.md](ASSETS.md) 和本交接；仅在 INTERFACES/PLUGIN_SPEC 加入SDK资产交叉链接。未修改Root README、项目总纲、Core、vision预留入口或SDK interfaces。

pyproject.toml 新增可选组 `assets = ["numpy>=2.4,<3"]`，不把NumPy加入基础依赖。实际环境：Windows 11（10.0.26200）、CPython **3.14.7** AMD64、NumPy **2.5.5**、Pillow **12.3.0**、pytest **9.2.0**。没有引入OpenCV。

## 公开接口

```text
AssetStore(root: Path, *, manifest: str="manifest.json",
           profile: Path|None=None, cache_limit_bytes: int=64*1024*1024)
  ids() -> tuple[str,...]
  variants(asset_id: str) -> tuple[str,...]
  resolve(asset_id: str, *, scene: str|None=None) -> AssetSelection
  load(asset_id: str, *, scene: str|None=None) -> LoadedTemplate
  invalidate(asset_id: str|None=None) -> None
  clear_cache() -> None
  cache_info() -> CacheInfo
  close() -> None
  profile: AssetProfile  # 只读属性
```

根包同时导出 AssetProfile、AssetSelection、LoadedTemplate、CacheInfo、AssetError及具体异常。所有模型为frozen/kw_only/slots；Profile.overrides复制成不可变映射。LoadedTemplate采用eq=False，避免NumPy逐元素比较造成含糊的相等语义。

模型字段：

- AssetProfile：name/theme/default_scene/overrides/source。
- AssetSelection：asset_id/variant_id/scene/theme/source/mask_source/size/variant_scene/variant_theme/selected_by/manifest_source/profile_source。
- LoadedTemplate：asset_id/variant_id/image/mask/width/height/source/selection。
- CacheInfo：hits/misses/evictions/entries/current_bytes/limit_bytes。

模型是SDK本地输出，不进入Protocol codec。数组数据保证以Store输出为准；自行构造LoadedTemplate不会自动校验调用方任意数组。

## Manifest、Profile与选择

完整JSON/INI示例见 [ASSETS.md](ASSETS.md)。Manifest v1必有schema_version=1和assets数组；每项id唯一、default_variant存在、variants非空。变体必须path，可选scene/theme/size/mask。ID为小写点分段，scene/theme为单段小写标识符；size为正整数像素对，拒绝bool。

UTF-8严格JSON拒绝重复键/ID、未知字段、非有限数值、非法结构；构造时核验全部路径，无像素解码。INI关闭插值、保留大小写后校验，拒绝重复/未知段键、DEFAULT、无效引用。profile=None使用内部default快照。Manifest/Profile后续变更须新建Store，不热重载。

有效scene：显式参数 → Profile.default_scene → 默认变体scene；有效theme来自Profile。选择顺序：asset_id@scene覆盖 → asset_id覆盖 → 自动候选。覆盖必须场景相同或通用，可以有意覆盖主题。自动候选先过滤不兼容场景/主题，再按精确场景、精确主题排序；无指定维度不给加分。同分仅用位于最高候选中的default_variant裁决，剩余歧义或无候选报AssetSelectionError。

无有效scene时仅允许通用scene；无theme时不限定主题，也不给主题特异性加分。AssetSelection记录有效维度和实际变体维度，避免有意覆盖主题时丢失解释信息。

固定测试中，同一 `ui.confirm`：无Profile得到dialog.default像素 `[[[10,20,30],[200,100,50]]]`；dark Profile得到dialog.dark像素 `[[[1,2,3],[4,5,6]]]`；scene=toolbar得到toolbar.default。移除显式覆盖后自动选择结果相同。示例另外用light/dark两个显式Profile完整运行。

## 数组、遮罩与所有权

PNG/JPEG先完整验证再解码，支持RGB/RGBA/L/LA/P及调色板透明度；拒绝动画、多帧、非支持格式/模式、损坏/截断数据。实际像素数上限16,777,216；读取文件编码字节上限128MiB，分别报告AssetValidationError和AssetPathError。

image为连续H×W×3、uint8、RGB。mask为None或连续H×W、uint8权重。外部mask必须8位L灰度、同尺寸；以其灰度值作为权重。alpha与外部mask使用uint16中间值计算 `(alpha*external+127)//255`。无外部mask且全不透明时None；显式全255外部mask保留；全零权重拒绝。

通过独立不可变bytes建立np.frombuffer/reshape数组。测试直接赋值、setflags(write=True)、沿base链设置可写均失败；调用方copy可独立写入。冻结模型及只读像素不冻结NumPy对象所有元数据，消费者不得修改shape/dtype。淘汰或关闭后，已取得的模板仍有效。

Store只拥有自身缓存，不关闭插件其他资源。插件可在initialize创建并预热，在close关闭。同步I/O和解码不是无成本操作，异步调用方自行选择线程或预热；本阶段未加入后台线程池、Frame解码、匹配算法或业务动作。

## 根目录、缓存与并发

root规范化为存在目录；Manifest、Profile、图片和mask全部受root边界约束。Manifest路径为POSIX相对路径，拒绝绝对路径、驱动器、反斜杠、点段、空段、非法字符及Windows设备名/尾点空格。Profile允许root内绝对Path。实际resolve(strict=True)后必须仍在root且为普通文件。

每次load核验规范化图片/mask路径和device/inode/size/mtime_ns。读取前、打开句柄fstat、读取后、解码后复核，拒绝明显变更；读权限和OS错误保留cause，默认异常消息仅安全类别，不输出原始消息。可信本机root不是强沙箱，无法消除恶意并发篡改的所有TOCTOU。

每Store独立RLock和LRU，锁覆盖检查、解码、缓存与关闭。同资源并发只解码一次；close等待正在持锁load结束。预算默认64MiB，拒绝bool/负数，0禁缓存。计费为实际长期持有的image/mask bytes，不含临时解码、元数据、调用方保留对象或原生RSS。

键含选择上下文、规范化来源和身份。同一通用变体用于不同scene时独立缓存并计费，保证selection.scene准确。同键命中返回同对象。文件身份变更移除旧变体各上下文，缺失/读取/解码失败清理相关ID，不缓存半成品。超预算对象可返回但不驻留，不为它淘汰旧项。

hits/misses在路径检查完成后的缓存查询计数，解码失败计miss，查询前错误不计；evictions仅容量淘汰，显式invalidate/clear、身份更新和close不计。统计不因clear重置。invalidate(id)清除此ID全部变体；None清全缓存。close幂等，此后包括profile/cache_info在内的新操作均AssetClosedError。

原位内容替换若device/inode/size/mtime都不变，需调用方显式invalidate/clear；测试实际保持文件大小和mtime后确认旧缓存命中，失效后返回新像素。

## 错误契约

全部继承BCAError → AssetError，唯一code如下：

| 类型 | code | 典型触发 |
| --- | --- | --- |
| AssetError | asset.error | 基类 |
| AssetManifestError | asset.manifest | JSON、版本、结构、ID、声明尺寸 |
| AssetProfileError | asset.profile | INI、字段、覆盖引用/配置冲突 |
| AssetNotFoundError | asset.not_found | 未声明语义ID；Profile未知变体引用归ProfileError |
| AssetSelectionError | asset.selection | 请求场景、无候选、歧义、覆盖场景不兼容 |
| AssetPathError | asset.path | 路径、越界、缺失、权限、身份变更、文件字节上限 |
| AssetDecodeError | asset.decode | 不支持格式/模式或无法完整解码 |
| AssetValidationError | asset.validation | 预算、像素数、实际尺寸或mask |
| AssetClosedError | asset.closed | 关闭后的操作 |

## 测试中发现并修复的问题

首轮127项中的早期112项执行时，81失败、31通过，集中在新文件身份实现。当前Windows/Python环境的Path.stat与os.fstat对ctime返回不同语义，正常文件被误判变更。实际探针确认device/inode/size/mtime一致，仅ctime不同；改为任务书建议的四字段身份，并新增Windows路径/句柄一致性回归，未放宽其他读前/读后检查。

随后111通过、1失败：Pillow将带透明表的P图片直接转RGB会警告。改为先RGBA再提取RGB/alpha，不压制警告。基础112项通过后，补充15项读途中变更、保持元数据替换、跨资源边界、删除缓存失效和上下文等回归，最终127项通过。

测试覆盖排序/严格JSON、完整选择优先级、独立固定像素/权重、只读及base链、路径/权限、图片和mask变更、LRU计数/容量/隔离、竞争加载/关闭和异常缓存一致性。真实symlink创建因WinError1314受限，记录not_verified，已有确定注入边界测试保留；没有将其冒充真实链接验证通过。

## 实际命令与结果

以下python均为项目 `.venv/Scripts/python.exe`；测试使用PowerShell，未配置BCA_CDP_ENDPOINT。完整原始输出保存于 `.test-artifacts/04.1/`，不删除早期失败日志。

| 命令 | 实际结果 | 日志 |
| --- | --- | --- |
| `python -m pip install -e ".[dev,assets]"` | 成功安装browser-cli-agent0.2.0、numpy2.5.5 | install.log |
| `python -m pytest tests/plugin_sdk/assets -q -W error --basetemp=.test-artifacts/pytest-04.1-assets` | **127 passed，18.57s，0 failed/0 skipped** | assets.log |
| `python -m pytest -q -W error --basetemp=.test-artifacts/pytest-04.1-full` | **624 passed、36 skipped，32.82s，0 failed** | full.log |
| `python -m mypy` | **Success: no issues found in 75 source files** | mypy.log |
| `python -m ruff check .` | **All checks passed** | quality.log |
| `python -m ruff format --check .` | 通过；最终文档加入后文件数见quality.log | quality.log |
| `python -m build` | 成功生成0.2.0 wheel/sdist | build.log |
| `python examples/asset_foundation.py` | light/dark均选中正确变体；数组不可写；每Store hits1/misses1/entries1/current_bytes6 | example.log |

624=原有497项非真机+新增127项资产测试。36跳过全部为原有Browser/Runtime/Plugin真机opt-in，本轮没有新增skip/xfail，也没有重跑或声称取得新的浏览器证据。Python3.12/3.13未运行，不用mypy目标配置代替实机矩阵。

### wheel/sdist和可选依赖验证

在 `.test-artifacts/04.1/package-venv` 新建不继承系统包的venv，使用本地wheelhouse安装构建wheel及Pillow/websockets：

```text
package-python -m pip install --no-index --find-links <wheelhouse> <dist-wheel>
package-python -I -c "...import Core/Browser/Runtime/Plugins/SDK interfaces..."
package-python -m pip install --no-index --find-links <wheelhouse> "browser-cli-agent[assets]"
package-python -I examples/asset_foundation.py
```

未安装NumPy时 `find_spec('numpy') is None` 且Core/Browser/Runtime/Plugin/SDK interfaces导入通过；安装extra后两Profile示例通过。模块路径确认来自隔离环境site-packages，不是源码editable目录。日志为package-install.log/package-example.log及package-smoke.json。

另从sdist重建wheel并强制安装到该环境，再运行示例成功。初次 `--no-build-isolation` 因当前venv无setuptools构建后端失败；改为隔离构建后又遇用户pip缓存目录写权限不足。最终将缓存明确放在工作区，成功命令为：

```text
python -m pip --disable-pip-version-check --cache-dir .test-artifacts/04.1/pip-cache wheel --no-deps --wheel-dir .test-artifacts/04.1/sdist-wheel dist/browser_cli_agent-0.2.0.tar.gz
package-python -m pip install --force-reinstall --no-deps <sdist-rebuilt-wheel>
package-python -I examples/asset_foundation.py
```

最终结果为Successfully built browser-cli-agent，两个Profile输出均正确。以sdist-wheel-workspace.log、sdist-install-workspace.log、sdist-example-workspace.log为最终证据；此前失败后的旧安装示例不计作sdist安装成功。

## 编码、工作区与剩余边界

中文文档使用直接UTF-8文件写入，避免PowerShell文本管道损坏非ASCII字符；最终严格解码并检查中文、问号替换字符。既有用户PROJECT_CONTEXT未改，未批量格式化旧文档。git diff --check对本轮文件通过，用户总纲的既有尾空格单独排除。既有03阶段其他文档中的历史乱码不作为本轮新增问题，也未在此阶段批量重写。

04.2可直接消费LoadedTemplate的RGB图像和可选uint8权重；BGR转换、OpenCV函数支持、缩放/预处理、匹配阈值及结果模型由04.2定义。AssetStore不代替Frame来源、BrowserFreshness、Plugin生命周期或Runtime单次发布。

待验证或限定：Python3.12/3.13、真实Windows symlink权限环境；可信文件系统边界不是恶意篡改沙箱；同步加载需由异步调用方调度；预算不覆盖调用方保留对象或临时/native内存；像素不可写不等于NumPy元数据强冻结。当前无需调整已验收Core公共接口，没有阻塞04.1交付的架构变更提案。
