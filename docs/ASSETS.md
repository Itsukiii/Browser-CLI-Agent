# Asset Foundation（BCA-04.1）

资产系统位于 `bca.plugin_sdk.assets`，用于从可信本机资源根目录加载静态模板。它不解码 Frame、不匹配图像、不发布 PageState、不执行浏览器输入。包版本仍为 0.2.0，Protocol 2 不变；Manifest/Profile v1 是独立的本地资源格式。

## 安装与文件布局

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,assets]"
.\.venv\Scripts\python.exe examples/asset_foundation.py
```

NumPy 通过 `assets = ["numpy>=2.4,<3"]` 可选依赖安装。Core 及原 SDK interfaces 不导入资产模块，未安装 NumPy 时仍可使用原 Core。直接使用 assets 模块需要安装 assets extra；Pillow 沿用基础依赖。

```text
asset-root/
  manifest.json
  profiles/dark.ini
  templates/confirm_default.png
  templates/confirm_dark.png
  templates/confirm_toolbar.png
  masks/confirm_mask.png
```

所有文件均须在 root 内。Manifest 中使用 POSIX 相对路径；Profile 参数允许 root 内绝对 Path，或相对 root 的 Path，不相对当前 cwd。

## JSON Manifest v1

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

- schema_version 必须是精确整数 1，拒绝 bool 和浮点数。
- assets 必须为数组，可以为空；每个条目只接受 id/default_variant/variants。id 唯一，variants 非空，default_variant 必须存在。
- 语义 ID 和变体 ID 使用 `^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$`。scene/theme 使用 `^[a-z][a-z0-9_]*$`。
- 每个变体必须有 path，可选 scene/theme/size/mask；显式 null 不作为省略处理。size 为 `[width,height]` 正整数对，拒绝 bool，单位为实际模板像素。
- UTF-8 严格解析，拒绝所有层级的重复 JSON 键、重复 ID、未知字段、NaN/Infinity、溢出至非有限值的浮点数和非法结构。
- 构造 Store 时检查所有路径格式、存在性、普通文件类型和规范化边界；不会在构造或 resolve 时解码图片。

图片内容损坏可以在构造时尚未发现，在 load 时才产生解码异常。Manifest 和 Profile 是构造时快照，文件更新不会自动重新解析它们；修改配置后应新建 Store。

## INI Profile v1 与选择规则

```ini
[profile]
name = dark
theme = dark
default_scene = dialog

[variants]
ui.confirm@dialog = dialog.dark
```

`profile=None` 使用内部默认配置：name=default，theme/default_scene=None，覆盖为空。提供文件时 `[profile]` 与 name 必需；theme/default_scene 可选，均为小写标识符；`[variants]` 可选。关闭插值、保留大小写后严格校验；重复段/键、未知段/字段、DEFAULT 段、空引用、无效 ID 及不存在的资源/变体引用均拒绝。

覆盖键可为 asset_id 或 asset_id@scene。场景限定覆盖在构造时校验其与变体声明的场景兼容；未限定场景的覆盖在实际 resolve/load 时按有效场景校验。Profile 不提供直接图片路径。

有效场景按以下顺序取得：显式 scene 参数 → profile.default_scene → default_variant.scene。有效主题来自 profile.theme，None 表示不限定主题。

选择顺序：

1. `asset_id@effective_scene` 显式覆盖。
2. `asset_id` 显式覆盖。
3. 自动筛选和排序。

显式覆盖只允许场景相同或未声明场景的变体，可以有意覆盖 Profile 主题。自动筛选要求场景相同或通用；指定主题时要求主题相同或通用。按“精确场景优先、精确主题次之”的二元排序选最高候选；未指定维度不给加分。并列时仅当 default_variant 位于最高候选中才用它裁决，否则报 AssetSelectionError，不依赖 JSON 顺序。

如果没有有效场景，仅允许无 scene 的通用候选。如果没有主题，所有主题均可参与，但不因 theme 更具体加分。无兼容候选或剩余歧义均明确报错。

上例 dark Profile 的 `load("ui.confirm")` 得到 dialog.dark，指定 scene="toolbar" 得到 toolbar.default。删除显式覆盖后自动选择结果相同。AssetSelection 同时记录有效 scene/theme、实际 variant_scene/variant_theme 和 selected_by（profile.scene/profile.asset/manifest），便于解释有意覆盖主题的结果。

## 公开 API 与模型

根包导出 AssetStore、AssetProfile、AssetSelection、LoadedTemplate、CacheInfo 及下表全部错误类型。模型为 frozen、kw_only、slots dataclass，不加入 Protocol codec。Profile.overrides 复制为 MappingProxyType，不与调用方字典共享可变状态。

```python
from pathlib import Path

from bca.plugin_sdk.assets import AssetStore

store = AssetStore(
    Path("asset-root"),
    manifest="manifest.json",
    profile=Path("profiles/dark.ini"),
    cache_limit_bytes=64 * 1024 * 1024,
)
try:
    selection = store.resolve("ui.confirm")
    template = store.load("ui.confirm")
    assert store.load("ui.confirm") is template
    writable = template.image.copy()
    stats = store.cache_info()
finally:
    store.close()
# 调用方仍可读取已经取得的 template。
```

| 方法/属性 | 返回和语义 |
| --- | --- |
| ids() | 稳定排序 tuple[str,...] |
| variants(asset_id) | 此语义 ID 的稳定排序变体元组，不存在则 AssetNotFoundError |
| profile | 只读的已校验 AssetProfile 快照 |
| resolve(asset_id, *, scene=None) | AssetSelection，只选择、检查路径，不解码像素 |
| load(asset_id, *, scene=None) | LoadedTemplate，按需完整解码或复用缓存对象 |
| invalidate(asset_id=None) | 指定 ID 所有变体和上下文失效；None 清空；未知 ID 报 AssetNotFoundError |
| clear_cache() | 等价 invalidate(None)，不重置统计 |
| cache_info() | CacheInfo 不可变快照 |
| close() | 幂等清空缓存和目录引用；此后除重复 close 外，以上操作及 profile 均报 AssetClosedError |

AssetProfile 字段：name/theme/default_scene/overrides/source。AssetSelection 字段：asset_id/variant_id/scene/theme/source/mask_source/size/variant_scene/variant_theme/selected_by/manifest_source/profile_source。source 为规范化图片 Path，size 为可选声明 `(width,height)`。

LoadedTemplate 字段：asset_id、variant_id、image、mask、width、height、source、selection。LoadedTemplate 不做数组逐元素相等比较（eq=False），缓存复用以对象身份 `is` 判断。这些是 Store 的输出模型；需要契约保证时从 Store 获得实例，不应自行构造未经校验的数组载荷。

CacheInfo 字段：hits/misses/evictions/entries/current_bytes/limit_bytes。

## 解码、遮罩与只读数组

支持静态 PNG/JPEG，图片模式 RGB、RGBA、L、LA、P。P 的透明色表先转换为 RGBA，再分别提取 RGB/alpha；灰度明确转换为 RGB。拒绝多帧/动画、CMYK、16 位灰度等不支持模式，以及损坏/截断或非 PNG/JPEG 数据。先检查头部、尺寸和完整性，再完整加载像素；不修改 Pillow 全局截断策略。

默认最多 **16,777,216 像素**；任何被读取文件最多 **128 MiB 编码字节**。像素超限为 AssetValidationError，编码文件超限为 AssetPathError；限值在本阶段为实现常量，不是新增构造参数。

- image：连续 `H×W×3`，`NDArray[np.uint8]`，RGB 顺序。
- mask：None 或连续 `H×W`、uint8 权重，0 忽略、255 完全有效。
- 外部 mask 必须是 8 位 L 灰度 PNG/JPEG，尺寸严格等于图片。其灰度采样即权重，不再应用外部文件透明标记。
- alpha 与外部 mask 同时存在时，使用 uint16 中间值计算 `(alpha * external + 127) // 255`。
- 无外部 mask 且 alpha 全255时 mask=None；显式全255外部 mask 保留。合并结果全0时报 AssetValidationError。
- Manifest.size 与实际尺寸不符、mask尺寸不符均报 AssetValidationError。

数组实际后端为独立不可变 bytes，经 np.frombuffer/reshape 建立。直接赋值、setflags(write=True)、经 ndarray.base 取得视图后设置可写都不能修改像素；需要可写缓冲时显式 copy()。冻结模型不等于 NumPy 对象的所有元数据也被冻结，消费者应把整个输出按只读约定使用，不修改 shape/dtype 等元数据。

淘汰、invalidate 或 close 只释放 Store 引用，不会破坏调用方仍持有的模板。缓存预算只覆盖 Store 驻留的像素/遮罩后端，不覆盖调用方保留对象、临时解码内存、Pillow 原生内存或 Python 元数据开销。

## 路径和文件身份

root 必须为存在目录，resolve 后作为边界。相对资源路径拒绝绝对路径、盘符、反斜杠、空路径、空段、`.`/`..`、控制字符、Windows 非法字符/保留设备名及尾点/尾空格。实际文件 resolve(strict=True) 后仍须位于 root，且是普通文件。

每次 load 都检查图片和 mask 的规范化来源与身份：device/inode/size/mtime_ns。读取时比较路径 stat 与打开句柄 fstat，并在读后和解码后复核。Windows 当前 Python 的路径 stat 与 fstat 对 ctime 语义不同，因此不把 ctime 用于两者比较。文件缺失、越界、权限失败和明显变更均报 AssetPathError，保留异常 cause，不把 OS 异常消息写入公开诊断。

可信本机 root 是前提；此机制不是抵抗恶意并发文件系统篡改的强隔离。若原位修改保持全部身份字段不变，缓存不能自动感知，调用方必须 invalidate/clear_cache。

## LRU、统计和线程所有权

每个 Store 拥有独立 RLock 和 LRU，默认64MiB；非负整数预算，拒绝bool，0禁用缓存。锁覆盖选择、检查、解码、缓存和关闭，同资源的竞争 load 只解码一次。同步 I/O 会占用调用线程，异步插件宜在 initialize 预热或显式安排工作线程。

内部键包含选择上下文、规范化图片/mask路径及身份。有效场景不同但选到相同通用变体时，缓存保留独立上下文对象，以避免返回错误的 selection.scene；各对象按实际持有的独立后端计费。

命中返回同一个 LoadedTemplate，更新LRU位置。身份改变则移除该变体旧上下文项，再重新解码；缺失/变更或解码失败不会提交半成品，相关ID的缓存被清除。单对象超预算仍返回但不驻留，也不为它淘汰已有项。

hits/misses 在完成路径身份检查、执行缓存查询时计数；解码失败算一次miss，查询前路径/选择失败不算。evictions 仅统计容量淘汰，不包含显式失效、文件身份刷新或关闭。clear/invalidate不清零历史计数；关闭后不再访问cache_info。

## 错误契约

所有错误继承 BCAError → AssetError，默认信息只含安全字段位置或类别。保留底层 cause 供明确调试，不默认输出图像、用户内容或长堆栈。

| 类型 | code | 场景 |
| --- | --- | --- |
| AssetError | asset.error | 资源异常基类 |
| AssetManifestError | asset.manifest | JSON版本、结构、重复/未知字段、ID/尺寸声明 |
| AssetProfileError | asset.profile | INI、字段、引用、场景限定配置冲突 |
| AssetNotFoundError | asset.not_found | 未声明语义ID；变体由Profile引用时使用ProfileError |
| AssetSelectionError | asset.selection | 请求场景不合法、不兼容、无候选或歧义 |
| AssetPathError | asset.path | 非法/越界/缺失/非文件/权限/身份变更/编码字节超限 |
| AssetDecodeError | asset.decode | 不支持格式/模式、动画、无法完整解码 |
| AssetValidationError | asset.validation | 缓存预算、像素限值、实际尺寸、mask约定 |
| AssetClosedError | asset.closed | 已关闭Store的新操作 |

## 04.2 接入

04.2可直接读取 LoadedTemplate.image/mask 作为RGB模板及权重。OpenCV默认BGR、缩放/预处理、匹配函数支持的mask语义、结果阈值都由04.2显式处理；04.1没有引入OpenCV或匹配算法。资源ID和变体上下文可用于结果溯源，不代替Frame来源或BrowserFreshness授权。

插件可在 initialize 创建Store，在close关闭；这不改变Plugin/Runtime独占发布及输入所有权。完整测试和平台限制见 [04.1交接](BCA-04.1_HANDOFF.md)。
