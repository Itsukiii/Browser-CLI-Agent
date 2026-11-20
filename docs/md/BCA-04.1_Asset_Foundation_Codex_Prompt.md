# BCA-04.1 — Asset Foundation / Codex 开发提示词

> 项目：Browser CLI Agent（BCA）  
> 任务：BCA-04.1 / Asset Foundation  
> 基线：`browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> 设计确认：场景 + 主题 + Profile 显式覆盖；只读 NumPy RGB 数组；每个 AssetStore 独立 64 MiB LRU 缓存。  
> 开发仓库：`https://github.com/Itsukiii/Browser-CLI-Agent`  
> 任务书：`BCA-04_Vision_Assets.md`（v0.1，2026-11-20）

## 0. 执行方式与基线核对

你是这个单仓库中的开发者。请在现有工作区直接实施 BCA-04.1，执行测试和质量检查，产出实际可用的 SDK 与交接文档。先检查 `git status`、当前分支和 HEAD，保留工作区已有改动。任务文件记录的开发起点为 `main / 3ac8078a5fff6506a36e61f6d3d7286f53202771`；如工作区代码更新，以当前实际源码为准并记录差异。

先阅读并核对以下来源：

- 共享上下文：`BCA_PROJECT_CONTEXT.md`（v0.5）、`BCA-00_MAIN_SYNC.md`、`BCA-01_MAIN_SYNC.md`、`BCA-02_MAIN_SYNC.md`、`BCA-03_MAIN_SYNC.md`、`BCA-04_Vision_Assets.md`。若当前工作区未包含项目共享文件，可读取仓库 `docs/` 中对应交接材料；报告实际使用的来源。
- 源码：`src/bca/plugin_sdk/{assets,vision,interfaces}/`、`src/bca/core/protocol/`、`src/bca/core/errors.py`、`src/bca/core/plugins/`、`examples/plugins/pixel_fixture/`、`tests/plugin_sdk/`、`pyproject.toml`。
- 接口文档：`docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/ARCHITECTURE.md`。

当前基础：`assets` 和 `vision` 只有预留入口；`plugin_sdk.interfaces` 重导出 Core 的 Plugin/PluginConfig/PluginContext/PluginMetadata；Frame 使用不可变 PNG/JPEG 编码 bytes；已有 Pillow 依赖。保持 Core/Browser/Runtime/Plugin System 的已验收公开接口和 Protocol 2 不变。新增资源类型属于 `bca.plugin_sdk.assets` 的本地接口。

## 1. 交付目标

完成 JSON Manifest、INI Profile、稳定语义 ID 与模板变体、根目录安全解析、图片/遮罩解码、只读 NumPy 模板对象、按需加载和 64 MiB 可配置 LRU、查询/失效/关闭 API，以及可重现的测试和文档。

04.1 的公共输出是 `LoadedTemplate`，供 04.2 的 Vision Engine 直接消费。保持资源系统独立于业务插件、页面内容、Frame 解码和匹配算法。业务插件在 `initialize()` 时可创建 AssetStore，在 `close()` 时关闭；插件观察和 `PageState` 提交仍使用现有 Plugin/Runtime 接口。

## 2. 文件布局与公开 API

推荐模块布局（可根据既有工程风格适当合并，必须保留根包稳定导出）：

```text
src/bca/plugin_sdk/assets/
  __init__.py
  models.py
  manifest.py
  profile.py
  loader.py
  cache.py
  store.py
  errors.py

tests/plugin_sdk/assets/
  test_manifest.py
  test_profile.py
  test_loader.py
  test_cache.py
  test_store.py
  fixtures/...

docs/ASSETS.md
docs/BCA-04.1_HANDOFF.md
```

要求从 `bca.plugin_sdk.assets` 统一导出：`AssetStore`、`AssetProfile`、`AssetSelection`、`LoadedTemplate`、`CacheInfo`、`AssetError` 及具体资源异常。数据模型沿用项目风格，优先使用 `@dataclass(frozen=True, kw_only=True, slots=True)`；容器字段应以不可变快照暴露。

拟定 AssetStore 稳定接口：

```python
class AssetStore:
    def __init__(
        self,
        root: Path,
        *,
        manifest: str = "manifest.json",
        profile: Path | None = None,
        cache_limit_bytes: int = 64 * 1024 * 1024,
    ) -> None: ...

    def ids(self) -> tuple[str, ...]: ...
    def variants(self, asset_id: str) -> tuple[str, ...]: ...
    def resolve(self, asset_id: str, *, scene: str | None = None) -> AssetSelection: ...
    def load(self, asset_id: str, *, scene: str | None = None) -> LoadedTemplate: ...
    def invalidate(self, asset_id: str | None = None) -> None: ...
    def clear_cache(self) -> None: ...
    def cache_info(self) -> CacheInfo: ...
    def close(self) -> None: ...
```

`ids()`/`variants()` 返回稳定排序的元组。提供只读 `profile` 属性用于查询当前已校验 Profile 快照。`resolve` 只解析、校验选择及文件路径，不触发像素解码；`load` 按需解码并返回模板。`cache_info()` 至少包含 `hits/misses/evictions/entries/current_bytes/limit_bytes`。所有方法使用清晰的类型标注，mypy strict 通过。

具体模型最低字段：

- `AssetProfile`：`name`、`theme`、`default_scene`、不可变的显式覆盖映射。
- `AssetSelection`：`asset_id`、`variant_id`、有效 `scene/theme`、已规范化的图片/遮罩路径、可选声明尺寸；来源可追溯。
- `LoadedTemplate`：`asset_id`、`variant_id`、`image: NDArray[np.uint8]`、`mask: NDArray[np.uint8] | None`、`width/height`、`source: Path`，以及必要的变体/来源信息。
- `CacheInfo`：计数及当前缓存预算快照。

## 3. Manifest JSON v1（文件格式定稿）

资源根目录含 `manifest.json`，每项具有稳定语义 ID、默认变体和变体字典：

```json
{
  "schema_version": 1,
  "assets": [
    {
      "id": "ui.confirm",
      "default_variant": "dialog.default",
      "variants": {
        "dialog.default": {
          "path": "templates/confirm_default.png",
          "scene": "dialog",
          "theme": "default",
          "size": [64, 32]
        },
        "dialog.dark": {
          "path": "templates/confirm_dark.png",
          "scene": "dialog",
          "theme": "dark",
          "size": [64, 32],
          "mask": "masks/confirm_mask.png"
        },
        "toolbar.default": {
          "path": "templates/confirm_toolbar.png",
          "scene": "toolbar",
          "size": [32, 32]
        }
      }
    }
  ]
}
```

确定以下校验行为：

1. `schema_version` 必须为精确的整数 `1`（拒绝 bool）。`assets` 为数组，非空语义 ID 唯一；每条 `variants` 至少有一项，`default_variant` 必须指向存在的变体。
2. 语义 ID 与变体 ID 使用小写点分段命名：`^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$`。例如 `tile.man_1`、`tile.honor.east`、`ui.confirm`；变体名称如 `hand.default`、`dialog.dark`。`scene`/`theme` 为可选的小写标识符，规则 `^[a-z][a-z0-9_]*$`。
3. 变体必须包含 `path`；可选 `scene`、`theme`、`size`、`mask`。`size=[width,height]`，两个数均为正整数且拒绝 bool，表示模板图片的实际像素尺寸。
4. 使用严格 JSON 解析：拒绝重复 JSON 对象键、重复 asset ID、未知字段、非有限数值、无效结构和版本。不得依赖字典覆盖来悄悄消解冲突。
5. JSON 读取采用 UTF-8，解析失败给出具体资源异常和安全的字段位置/类别诊断。Manifest 解析阶段检查全部相对路径格式及规范化边界；图片的实际完整解码发生在 `load` 时。

这里的 Manifest 只描述视觉资产，与 Core Plugin System 的 `plugin.toml` 分开维护，版本独立于 `PROTOCOL_VERSION=2`。

## 4. Profile INI v1（选择规则定稿）

```ini
[profile]
name = dark
theme = dark
default_scene = dialog

[variants]
ui.confirm@dialog = dialog.dark
```

- `profile=None` 使用内部默认配置（无主题/场景覆盖）。提供 Profile 文件时，`[profile]` 与 `name` 必需，`theme/default_scene` 可选；`[variants]` 可选。
- 采用 `configparser.ConfigParser(interpolation=None, strict=True)`，保留大小写后严格校验、仅接受规定的小写 ID；拒绝重复键/段、未知段/键、空变体引用以及引用不存在的资源或变体。
- `[variants]` 的 key 支持 `asset_id` 或 `asset_id@scene`；同一 key 只能配置一次。Profile 只引用 Manifest 已声明的变体，不直接读取其他图片路径。
- 实际 `scene` 取值依次为：`load/resolve(scene=...)`、`profile.default_scene`、该资源 `default_variant.scene`（如果存在）。实际 `theme` 来自 `profile.theme`，缺省表示不限定主题。
- 选择优先级：① `asset_id@effective_scene` 显式覆盖；② `asset_id` 显式覆盖；③ Manifest 自动选择；④ 同等优先候选中使用 `default_variant` 作唯一平局裁决。不存在匹配或剩余歧义时明确报错。
- 显式覆盖必须引用已声明变体，且与请求场景兼容（其 `scene` 等于 effective_scene 或未声明）；可有意覆盖 Profile 主题。
- 自动选择：场景指定时只允许相同 scene 或无 scene 的通用变体；主题指定时只允许相同 theme 或无 theme 的通用变体。对保留候选按「精确场景优先、精确主题次之」排序；缺省维度不产生特异性加分。并列优先采用 `default_variant`（若在并列候选中），其余并列则报 `AssetSelectionError`，不可依赖 JSON 条目顺序。
- `scene` 不存在时允许使用默认变体所声明的场景作为匹配基准；默认变体没有声明场景时只使用无 scene 的通用候选。选择所需维度应在 `AssetSelection` 中可观察。
- 对 Profile 文件和引用关系在构造 AssetStore 时完整解析校验；资源文件变更使用缓存失效 API，切换 Profile 可新建独立 AssetStore。

示例期望：使用上述 dark Profile 时，`load("ui.confirm")` 得到 `dialog.dark`；`load("ui.confirm", scene="toolbar")` 得到 `toolbar.default`。如果删除 `[variants]` 中的覆盖，自动选择仍应得到同样结果。测试应覆盖无主题、通用变体、冲突和不可用场景。

## 5. 根目录与文件安全

- `root` 为明确存在的目录，入口使用规范化 `Path.resolve()`；Manifest、Profile、图片及 Mask 都以 root 为边界。
- Manifest 内路径使用 POSIX 风格相对路径；拒绝绝对路径、驱动器路径、反斜杠、`.`/`..` 段、空路径及非法字符。文件实际 `resolve(strict=True)` 后必须仍位于 root，支持合法的内部子目录。
- 针对缺失、目录冒充文件、越界符号链接、读权限失败、格式不合法给出稳定错误类别；不要将 OS 异常内容或图片字节直接写进日志。
- 加载前解析实际图片和遮罩文件，分别检查边界。读前/读后核对必要文件身份，避免把明显发生变化的数据提交到缓存。
- 资源来自显式可信的本机 root；上述检查提供可靠的路径边界与异常诊断，不宣称对恶意并发篡改文件系统的强隔离。

## 6. 图片解码与只读 NumPy 契约

04.1 使用项目已有的 Pillow 解码静态图片，并引入 NumPy；将 `numpy>=2.4,<3` 配置在 `pyproject.toml` 的可选依赖组 `assets` 中，保留 Core 基础依赖轻量。开发和专项测试使用 `pip install -e ".[dev,assets]"`；记录 Windows/Python 实测可用版本。

- 图片支持 PNG/JPEG，至少覆盖 RGB、RGBA、L/LA 灰度和 PNG 调色板透明度；实际读完整图片并验证格式、尺寸和像素内容。拒绝空尺寸、损坏/截断数据和不支持的颜色模式；限制过大解码输入（例如默认最大 `16_777_216` 像素），明示限制及异常类别。
- `LoadedTemplate.image` 标准为连续 `H×W×3`、`dtype=uint8`、RGB 通道顺序。颜色转换是明确操作；不向外暴露 Pillow 对象作为稳定输入。
- `LoadedTemplate.mask` 为可选 `H×W`、`uint8` 权重，0 表示忽略，255 表示完全有效。Alpha 通道可作为 mask；独立 `mask` 文件要求 8 位灰度、尺寸严格相同。两者同时存在时按 `(alpha * external + 127) // 255`（使用足够宽的整数中间值）合并。全不透明且无外部 mask 时设为 None；全零权重报 `AssetValidationError`。
- 对外图像和遮罩必须不可修改：建议用独立的不可变 `bytes` 作为实际数据后端，再以 `np.frombuffer(...).reshape(...)` 建立只读数组。要求直接赋值和尝试 `setflags(write=True)` 均不能改变共享缓存像素；LoadedTemplate 本身冻结。需要可写缓冲的调用方显式 `copy()`。
- `width/height` 与 `image.shape` 一致；Manifest 若声明 `size`，按实际图片尺寸检查。mask 大小也与图片一致。后续 04.2 可直接读取 `image/mask` 输入 OpenCV 匹配算法；OpenCV 的预处理/缩放、结果判定由 04.2 确定。

## 7. LRU 缓存与所有权

- 每个 `AssetStore` 拥有独立的缓存和同步锁；默认容量 `64 * 1024 * 1024` bytes，可传入非负整数，拒绝 bool，0 表示关闭缓存。缓存以解码后长期持有的图像/遮罩 `bytes` 实际容量计费。
- 索引至少体现 root、asset_id、variant_id、规范化图片/Mask 来源路径和当前文件身份（例如 `st_dev/st_ino/st_size/st_mtime_ns`）；由于 Store 已按 root 隔离，可在内部简化键的冗余字段，但必须保证不同 root、变体、已更改文件不会复用旧对象。
- 每次 load 都核验资源及遮罩文件身份，命中时复用同一个 `LoadedTemplate` 对象；身份变化时移除旧项、重新读取、解码并缓存新项。对元数据完全不变的原位内容替换，明确由调用方通过 `invalidate()`/`clear_cache()` 显式失效。
- 内存超限时按 LRU 淘汰；单个模板超过预算仍可按需返回，但不驻留缓存。`hits/misses/evictions/entries/current_bytes/limit_bytes` 可稳定查询。
- `invalidate(asset_id)` 只失效指定语义 ID 的所有变体；`invalidate(None)` 等效清除整个缓存；`clear_cache()` 显式清空；`close()` 幂等、清空 Store 引用且关闭后访问新操作报明确生命周期异常。保留已交给调用方的 LoadedTemplate 仍可继续读取，不受清理影响。
- 同一 Store 的并发同步调用使用线程锁实现一致行为（例如同资源竞争只解码一次）；锁保护缓存状态和关闭转移，资源加载中的失败不保留半成品。异步插件应考虑在初始化期预热频繁使用的资源，不把磁盘 I/O 误当作无成本的同步操作。

## 8. 异常契约

所有资源异常继承现有 `bca.core.errors.BCAError`，增加 `AssetError` 基类、唯一稳定 `asset.*` code 和以下具体异常：

- `AssetManifestError`：JSON 版本、结构、重复/未知字段与非法 ID。
- `AssetProfileError`：INI 解析、字段、覆盖引用和配置冲突。
- `AssetNotFoundError`：查询不存在的语义 ID/变体。
- `AssetSelectionError`：无兼容候选、变体歧义或选择冲突。
- `AssetPathError`：路径非法、越界、缺失、非文件或读取权限问题。
- `AssetDecodeError`：图片无法完整解码或格式不支持。
- `AssetValidationError`：尺寸、mask、数据完整性不匹配。
- `AssetClosedError`：Store 关闭后的生命周期访问。

边界处理保留 Python 异常 `__cause__` 以利调试，但默认日志和诊断只记录安全的类别、资源 ID、变体 ID、字段/路径标识，不输出原始图像字节、敏感内容或长堆栈。公共错误类型与方法异常语义必须在文档写清楚。

## 9. 测试要求

使用 pytest 编写可重复、独立于真实浏览器的资产系统测试，包含确定性的 PNG/JPEG/透明图/灰度/Mask 固定资源，另保存不依赖被测算法计算的预期映射和像素结果。

重点覆盖：

1. Manifest：合法版本、对象/变体查询排序、重复 JSON key、重复 ID、未知字段、非法 token、默认变体引用和尺寸声明。
2. Profile：读取/覆盖、theme/scene 优先级、显式 ID 与 ID@scene 覆盖、通用变体回退、default_variant 同分裁决、歧义和无匹配、重复 INI key 与无效引用。
3. 路径：相对路径、绝对路径、盘符、`..`、越界链接、缺失文件、目录、不可读和不同 cwd；Windows 符号链接权限受限时记录真实限制并保留可复现替代测试。
4. 解码：RGB/RGBA/L/LA、JPEG、Alpha/外部 Mask/组合权重、尺寸与通道、全零 Mask、损坏/截断/过大文件；直接验证 RGB 值和权重结果。
5. 不可变性：`image/mask` 尝试赋值、`setflags(write=True)`，以及其他引用无法改动已缓存像素；淘汰后的旧模板仍可读取。
6. 缓存：相同对象命中身份复用、不同变体/root 隔离、文件与 Mask 的 stat 变化、显式失效、LRU 淘汰、超预算对象、0 容量和统计一致性。
7. 并发/生命周期：竞争加载、重复 close、close 与 load 的合理同步、资源异常时缓存保持一致。使用独立 `tmp_path`，测试不要依赖具体机器已有资源。
8. 公共接口：`bca.plugin_sdk.assets` 可导入、mypy strict 注解完整；现有 Core/Plugin SDK 示例与全量旧测试回归。

建议提供一个 `examples/asset_foundation.py` 使用独立 fixture 演示 `AssetStore → ids/variants → resolve → load → cache_info → close`。示例应能在 Windows/Python 环境直接运行，无浏览器要求。

## 10. 文档与交接

完善 `docs/ASSETS.md`，包含：v1 JSON/INI 完整规范、目录布局、稳定 ID 命名、选择优先级与异常案例、公开 API、RGB/Mask 数组格式、只读和调用方所有权、缓存身份/失效与统计、使用示例、04.2 的直接输入契约。按需要更新 `docs/INTERFACES.md`/`docs/PLUGIN_SPEC.md` 中 SDK 本地入口的交叉链接，保持原 Core 契约不变。

生成 UTF-8 Markdown `docs/BCA-04.1_HANDOFF.md`，至少报告：

- 实际 Git HEAD/工作区状态、修改文件、依赖版本；
- Manifest/Profile 示例与完整选择逻辑；
- 已实现公开类型/函数签名、数组/遮罩约定和缓存模型；
- 错误类别、路径安全边界、并发与资源所有权；
- pytest 专项/全量、mypy strict、Ruff check/format、wheel/sdist 构建的**实际命令与完整结果**（区分通过/跳过/失败）；
- Python/OS 实测信息、04.2 接入说明及待架构主会话协调的事项。

保留仓库现有文档和用户改动；04.1 交付材料先供本子会话审阅，整个 BCA-04 的正式 `BCA-04_MAIN_SYNC.md`、项目总纲和根 README 的验收归档由整体阶段结束后的架构主会话统一完成。

## 11. 质量检查与完成判据

至少在当前可用环境执行并记录结果：

```text
python -m pip install -e ".[dev,assets]"
python -m pytest tests/plugin_sdk/assets -q
python -m pytest -q
python -m mypy
python -m ruff check .
python -m ruff format --check .
python -m build
```

以仓库已有工具命令与 Python 环境进行必要适配；若当前机器无法运行某一检查，准确说明原因，不将未执行结果记为通过。额外关注 wheel/sdist 安装后的 `bca.plugin_sdk.assets` 导入、缺少 assets extra 时 Core 常规模块可导入、Windows 路径处理、`numpy>=2.4` 对当前 Python 的安装兼容性。

最终应能通过两个不同 Profile 从相同的 `ui.confirm` 语义 ID 得到不同且准确的模板；可以直接使用只读 RGB NumPy 数组及可选遮罩；文件身份变化触发重载，LRU 计费/失效/关闭可验证，测试及文档与实际源码一致。

完成后先输出简短实施报告（文件变更、关键 API、测试实际数字、风险与待协调项），并提供 `docs/BCA-04.1_HANDOFF.md` 的内容或路径，便于本会话进行 04.1 阶段审查。若发现确需调整已验收 Core 公共接口，请先整理变更理由和影响，提交主架构会话协调。
