# BCA-04.2 / Vision Engine & Integration — Codex 开发任务书

> **任务编号：** BCA-04.2  
> **阶段名称：** Vision Engine & Integration  
> **文档版本：** v1.0 · 2026-11-21  
> **项目：** Browser CLI Agent（BCA）  
> **仓库：** https://github.com/Itsukiii/Browser-CLI-Agent  
> **已核对 GitHub 基线：** `main` / `fe151645beaa7bfbaa4dcb19dc5499cbe48fdf01`（执行前再次确认本地工作区和最新 `main`）  
> **项目/协议：** `browser-cli-agent 0.2.0` / `PROTOCOL_VERSION=2`  
> **前置成果：** BCA-00～03 已正式验收；BCA-04.1 Asset Foundation 已本地测试并推送，待 BCA-04 整体正式验收。  
> **工作方式：** Codex 在统一仓库完成开发、测试、文档和交接材料；如遇重大公共 API 变更，先整理变更提案交由架构主会话协调。

## 0. 任务目标与原则

在现有 `bca.plugin_sdk.vision` 中提供可独立使用、可测试、可解释的视觉模板匹配 SDK，并在真实受控 Edge/Chromium 中验证从 `CaptureProvider` 的 `Frame` 到插件 `PageState`、可信 `ActionBatch`、浏览器输入及再次观察的完整链路。

开发时优先遵循以下原则：

1. 使用 BCA-04.1 的 `LoadedTemplate`、`AssetSelection`、`AssetStore`，按其已交付类型与所有权约定消费 RGB `uint8` 数组及可选 `uint8` 权重 Mask。
2. 使用 Protocol 2 的不可变 PNG/JPEG `Frame`；视觉位置以**当前 Frame 的实际图片像素坐标**表达，映射 CSS 输入位置时调用**同一个 Frame 的** `pixel_to_css()`。
3. 图像处理与候选判定由 SDK 负责；插件解释页面业务含义，并由 Runtime 按既有契约发布 `PageState`。视觉相似度不能替代 Runtime 的截图来源授权及动作新鲜度检查。
4. 保持已验收的 Core、Browser、Runtime、Plugin System 公开接口；SDK 新增类型在 `plugin_sdk.vision` 命名空间内定义，不加入 Protocol 2 codec。
5. 使用确定的评分公式和排序规则，能解释未命中、多命中与相近候选；阈值和匹配分数均为**算法指标而非统计概率**。
6. 不以早期阶段的性能数据替代 04.2 的实际测量。记录真实实验环境、采样范围和失败/跳过结果。

## 1. 必读资料、源码和开工核查

先读取：

- `docs/md/BCA_PROJECT_CONTEXT.md`（若仓库内位置有变化，按真实文件定位）；`docs/BCA-00_MAIN_SYNC.md` 或 `docs/md/BCA-00_MAIN_SYNC.md`；`docs/BCA-01_MAIN_SYNC.md`、`docs/BCA-02_MAIN_SYNC.md`、`docs/BCA-03_MAIN_SYNC.md`。
- `docs/BCA-04.1_HANDOFF.md`、`docs/ASSETS.md`、`docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/BROWSER.md`、`docs/RUNTIME.md`、`docs/ARCHITECTURE.md`。
- 04 阶段正式任务书 `BCA-04_Vision_Assets.md`（可能来自 ChatGPT Project 共享来源而不在本地仓库；若缺少，以当前提示词与已提交接口为直接开发依据，并如实记录）。
- `src/bca/plugin_sdk/assets/{__init__,models,loader,store,cache,errors}.py`、`src/bca/plugin_sdk/vision/__init__.py`、`src/bca/plugin_sdk/interfaces/__init__.py`、`src/bca/core/protocol/{__init__,models}.py`。
- `src/bca/core/plugins/`、`src/bca/core/runtime/`、`src/bca/core/browser/` 中相关装配入口、`examples/plugin_browser.py`、`examples/plugin_integration.py`、`examples/plugins/pixel_fixture/`、现有集成测试与 `pyproject.toml`。

开始前执行 `git status --short`、`git rev-parse HEAD`，保留用户现有修改；核实实际 `LoadedTemplate` 字段、Frame 签名、BrowserFreshness、PluginRuntimeHost 与测试标记。以仓库源码为权威，若本任务的拟议名称与真实 API 发生冲突，优先做 SDK 层局部调整并在交接中记载。

**04.1 已确认的真实契约：**

```python
from bca.plugin_sdk.assets import AssetStore, LoadedTemplate

store = AssetStore(root, profile=profile_path)
selection = store.resolve("ui.confirm", scene="dialog")
template = store.load("ui.confirm", scene="dialog")
# template.asset_id, template.variant_id, template.selection
# template.image: RGB, uint8, contiguous, H x W x 3, bytes-backed readonly
# template.mask: None 或 uint8, contiguous, H x W, 0..255
# template.width, template.height, template.source
store.close()
```

`AssetStore` 本地独立 64 MiB LRU；已返回模板在失效/关闭后仍能读取。Alpha 与外部遮罩已在 Assets 合并为权重，公式 `(alpha*external+127)//255`。图片位置和 Mask 语义不应在 Vision 中重新解释成新的资源格式。04.1 的 NumPy 版本约束为 `numpy>=2.4,<3`，基础依赖包含 Pillow。

## 2. 技术依赖与代码落位

建议在 `pyproject.toml` 新增：

```toml
[project.optional-dependencies]
vision = ["numpy>=2.4,<3", "opencv-python-headless>=4.14,<5"]
```

保留已有 `assets` extra。理由：OpenCV 4.14 已有 PyPI 正式发行，`opencv-python-headless` 适用于无 GUI 的匹配 SDK；首次使用前由 Codex 在目标 Windows/Python 3.14.7 环境实际验证 pip 依赖解析和 wheel 安装。若遇明确的包版本冲突，优先以可复现的解析证据确定兼容版本范围，记录原因后再调整，不凭推测提升整个项目的运行时依赖。避免同时安装多个提供 `cv2` 的 OpenCV wheel 变体。

建议实现目录（可以依据职责微调）：

```text
src/bca/plugin_sdk/vision/
  __init__.py         # 稳定公开入口
  models.py           # ROI、选项、候选、结果、耗时模型
  errors.py           # Vision SDK 错误类
  decode.py           # Frame PNG/JPEG -> RGB ndarray
  preprocess.py       # ROI、灰度、模板/Mask 缩放
  matching.py         # 单模板/多模板、评分、候选判定、NMS

examples/
  vision_foundation.py
  plugins/vision_fixture/  # 可复用原 pixel_fixture 的受控页面思路
  vision_integration.py   # 如现有测试入口更适合，按工程风格落位

tests/plugin_sdk/vision/
  fixtures/              # 静态模板、截图和独立期待值
  test_decode.py
  test_preprocess.py
  test_matching.py
  test_geometry.py
  test_errors.py
  test_performance.py  # 测量入口及可复现基准，不以时钟结果断言精确值

tests/integration/ 或现有 core/plugins 集成测试目录

docs/VISION.md
docs/BCA-04.2_HANDOFF.md
docs/BCA-04_MAIN_SYNC.md
```

需更新必要的 `docs/INTERFACES.md`、`docs/PLUGIN_SPEC.md`、`docs/ASSETS.md` 中的 SDK 交叉链接。接口公开导出应保持精简，内部工具可以调整。

## 3. 统一图像模型与 Frame 解码

### 3.1 拟议公开模型

以下为目标契约，允许在不改变语义的情况下根据仓库 typing 风格细化签名：

```python
@dataclass(frozen=True, kw_only=True, slots=True, eq=False)
class DecodedFrame:
    frame: Frame  # 保留同一来源帧引用
    image: NDArray[np.uint8]  # RGB, shape=(height,width,3), readonly


@dataclass(frozen=True, kw_only=True, slots=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int


class PreprocessMode(StrEnum):
    RGB = "rgb"
    GRAY = "gray"


def decode_frame(frame: Frame) -> DecodedFrame: ...
```

`PixelRect` 使用整数像素、左上角原点、`[x, x+width) × [y, y+height)` 半开矩形。验证所有整数为精确 `int`、非 bool，width/height > 0，x/y >= 0，矩形严格在 Frame 内；非法 ROI 明确抛 Vision 输入/几何错误。没有传 ROI 时表示全图。`DecodedFrame.image` 同样通过不可变 `bytes` 支撑只读 NumPy 视图，保持与 Assets 的数据共享规则一致。

### 3.2 Frame 解码要求

1. 输入必须是 Protocol 2 `Frame`，使用其 `format`、`data`、`width/height`，同时验证编码与完整解码一致；只检查 PNG/JPEG 文件头不够。按实际 decode 得到的宽高必须等于 Frame 元数据。
2. 优先使用 `cv2.imdecode` 解码 PNG/JPEG，再转换为统一 `RGB uint8`。显式处理灰度、三通道 BGR、四通道 BGRA；对于带透明度的截图，采用**确定的黑色背景 alpha 合成**后转 RGB，并在文档中写明规则（Browser 实测截图通常是不透明的）。拒绝 16 位、异常通道、空数据、超限尺寸和解码不完整/损坏的内容。必要时用 Pillow 的完整性检查补足 OpenCV 对截断数据的行为，并测量这一步开销。
3. 与 04.1 一样限制像素总数为 16,777,216；若选择其他与已有 SDK 一致的上限，统一文档和测试。
4. 输出图片矩阵为 C-contiguous，shape `(H,W,3)`，`uint8`，只读像素缓冲；同一解码图片可复用给多个模板，不为每个候选重复解码。
5. 测试 PNG/JPEG、RGB/RGBA/灰度、含透明像素 PNG、错误编码声明、尺寸不符、坏 CRC/截断、无效 Frame 参数、已编码数据内容损坏和边界尺寸。

## 4. ROI、预处理与尺度

### 4.1 ROI

- 匹配输入以 `DecodedFrame` 或由其解码的图像为基础；ROI 仅限制搜索窗口。ROI 里的局部坐标在结果中还原为**原始 Frame 像素坐标**。
- ROI 只裁剪图像视图或必要的紧凑处理缓冲，不修改 `DecodedFrame.image`。
- 结果矩形及中心均是 Frame 像素空间，而不是 ROI 局部空间、CSS 空间或模板原始空间。
- 全图/区域截图作为不同 Frame 分别对待：`Frame.viewport.capture_x/y` 的偏移仅由最终 `frame.pixel_to_css()` 处理；Vision 自身不重新加偏移、不重复缩放 DPR。

### 4.2 预处理

- 支持 `RGB` 和 `GRAY` 两种模式；`GRAY` 用固定、文档明确的 OpenCV RGB→GRAY 转换，所有候选在同一次调用中使用同一模式。
- 适当检查 dtype、shape、连续性、有限数值、Mask 形状及非空有效权重；原始模板必须来自 `LoadedTemplate` 的已校验对象，SDK 自身仍在边界做防御式输入验证。
- 输出及中间数组可以在函数内部复制或转换，但不能原地修改调用方 Frame/模板的只读缓冲。

### 4.3 显式模板缩放

- 支持固定尺度列表，元素是 `(scale_x, scale_y)`，默认 `((1.0, 1.0),)`；两轴可不同以适应非等比图像尺度。
- 缩放作用于**模板与其 Mask**，而不是对 Frame 的页面 CSS 几何进行猜测；缩放后的目标位置仍以截图原始像素返回。
- 因子必须有限且 > 0；首版建议限定在 `[0.25, 4.0]`、最多 16 种尺度。结果尺寸使用 `max(1, floor(source_size * scale + 0.5))`，以避免平台相关的舍入歧义。
- 缩小时可用 `INTER_AREA`，放大时 `INTER_LINEAR`，Mask 用明确的线性插值和四舍五入权重规则；缩放后零有效权重拒绝。
- 缩放模板大于 ROI 时该候选尺度跳过，若全部候选都过大，返回带明确原因的 NOT_FOUND 结果。

## 5. 模板匹配算法与分数契约

首版统一使用 OpenCV `cv2.matchTemplate(..., cv2.TM_SQDIFF)` 计算**非归一化平方误差**，再自行做范围明确的归一化，得到越大越相似的 `[0,1]` 分数。选择该方案的原因是：零方差/纯色/全黑模板也能正确计算，且能统一定义 Mask 的权重公式；相较直接使用 `TM_CCOEFF_NORMED`，不依赖模板方差非零。OpenCV 对 `TM_SQDIFF` 的 Mask 公式使用平方权重，可参考官方文档：https://docs.opencv.org/4.x/df/dfb/group__imgproc__object.html 。

### 5.1 精确定义

对每个有效模板位置，设颜色通道数为 `C`（RGB=3，GRAY=1），模板位置的权重 `W(u,v)` 由 `LoadedTemplate.mask / 255` 给出，无 Mask 时恒为 1。误差：

```text
SSD(x,y) = Σ_(u,v,c) [ (T(u,v,c) - I(x+u,y+v,c)) * W(u,v) ]²
D = C * 255² * Σ_(u,v) W(u,v)²
score(x,y) = clip(1 - sqrt(max(SSD(x,y),0) / D), 0, 1)
```

使用 OpenCV `TM_SQDIFF` 与浮点权重 Mask，或数学上等价、速度更好的实现；重要的是公式一致，不能把二值化 Mask 冒充灰度权重。无 Mask 可走更快路径。分母使用至少 float64 汇总，保证正数；对 OpenCV 的微小负误差、非有限输出作确定处理和显式诊断。使用固定随机种子和纯 NumPy/小尺寸穷举 oracle 验证以上公式，测试权重 `0/64/128/255`、纯色模板、黑模板、遮罩与无遮罩。

**分数解释：** `1.0` 为完全相同的有效像素，`0.0` 为按定义达到最大可能均方差的极端情况；分数是像素相似度，不是概率/模型置信度。RGB 与灰度在不同调用间可能分数不同，业务方应按真实测试数据选择阈值。

### 5.2 匹配选项

建议提供单一配置模型（名称可统一为 `MatchOptions`）：

```python
@dataclass(frozen=True, kw_only=True, slots=True)
class MatchOptions:
    threshold: float = 0.96  # [0,1]，边界包含
    roi: PixelRect | None = None
    mode: PreprocessMode = PreprocessMode.RGB
    scales: tuple[tuple[float, float], ...] = ((1.0, 1.0),)
    nms_iou: float = 0.45
    ambiguity_margin: float = 0.02
    max_results: int = 32
    max_proposals_per_variant: int = 128
```

精确检验类型与取值范围；`0` 和 `1` 均为合法阈值，`bool` 不属于有效数值。所有候选与诊断记录实际 score、threshold、scales、模板来源。

## 6. 候选、多位置、去重与歧义

### 6.1 公开结果模型

建议由 `bca.plugin_sdk.vision` 导出：

```python
class MatchStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, kw_only=True, slots=True)
class MatchCandidate:
    asset_id: str
    variant_id: str
    frame_id: str
    bbox: PixelRect  # 原始 Frame 像素矩形
    center: tuple[float, float]  # x+(width-1)/2, y+(height-1)/2
    score: float
    threshold: float
    scale_x: float
    scale_y: float
    # 可增补 selected_by、算法名等可解释字段


@dataclass(frozen=True, kw_only=True, slots=True)
class MatchResult:
    frame_id: str
    page_id: str
    status: MatchStatus
    matches: tuple[MatchCandidate, ...]
    ambiguous: tuple[tuple[MatchCandidate, ...], ...]
    best_candidate: MatchCandidate | None
    reason: str  # 稳定的简短原因类别
    # 耗时诊断可用单独 VisionTiming 模型


def match_templates(
    decoded: DecodedFrame,
    templates: Sequence[LoadedTemplate],
    *,
    options: MatchOptions = MatchOptions(),
) -> MatchResult: ...


def match_frame(
    frame: Frame,
    templates: Sequence[LoadedTemplate],
    *,
    options: MatchOptions = MatchOptions(),
) -> MatchResult: ...
```

`match_frame` 是解码一次并调用 `match_templates` 的便利函数。可提供 `match_template` 单模板便利包装，但结果语义须保持一致。若模型默认值使用实例，须保证实例真正不可变且无共享可变成员。

### 6.2 候选处理规则

1. 先从每个模板×尺度的完整 score map 产生有界的高分局部提案；使用确定性的局部峰值扫描/抑制，避免对整张纯色大图枚举海量等分位置。每变体候选数及总输出上限明确。
2. 只将 `score >= threshold` 的候选视为达到阈值。未达阈值时仍可记录全局最佳候选供诊断，`matches` 为空。
3. 对同一模板在同一对象区域的高度重叠提案按 `nms_iou` 做 IoU 抑制；不同位置的相同对象可以输出多个 `matches`，并按可重现的顺序排列。
4. 对不同变体/不同语义 ID 的空间重叠候选进行竞争判定。如果它们满足同一位置的重叠条件，且最高分与次高分差值 `<= ambiguity_margin`，把该竞争组放入 `ambiguous`，不把任意一个变体判作已确定目标。
5. 若竞争组得分差明显，则保留最高分候选并抑制同位置其余候选。空间不重叠的重复目标应分别保留。只要出现未解决的歧义组，整体结果 `AMBIGUOUS`；无歧义且有有效命中为 `MATCHED`；没有有效候选为 `NOT_FOUND`。
6. 同分和接近阈值比较要有文档化的浮点容差约定，排序以 `(score 降序, asset_id, variant_id, y, x, scale_x, scale_y)` 为稳定规则。结果 `matches` 与 `ambiguous` 均有固定顺序，与 Manifest 资源排列顺序无关。
7. `best_candidate` 可以在 NOT_FOUND 时保存低于阈值的最高候选；在歧义时保留最高分候选用于诊断，但不能通过它自动生成可信操作。
8. `reason` 使用稳定代码或枚举（如 `below_threshold`、`template_larger_than_roi`、`ambiguous_candidates`、`matched`），并在文档中列举；避免把原始异常信息当成可机器解析的理由。

**注意：** 该规则要兼顾“同一对象在页面上出现多次”与“同一位置存在相似模板”，不能简单地把任意多个有效命中都算成歧义。测试使用手工定义的外部期望，不以被测算法自身产生的坐标/类别充当 oracle。

## 7. 异常、诊断与性能边界

在 `vision/errors.py` 定义继承 `BCAError` 的 `VisionError` 以及至少 `VisionDecodeError`、`VisionInputError`、`VisionMatchError`，使用稳定 `vision.*` 错误码。无法解码、非法 ROI/选项、OpenCV 执行失败应区分；未命中和正常候选歧义通过 `MatchResult` 表示。错误不得默认打印 Frame 原始 bytes、图片内容或无界堆栈。Assets 的既有异常保持来源和类型，不包装成无意义的通用异常。

`VisionTiming` 或等价快照建议至少涵盖：`decode_ms`、`preprocess_ms`、`match_ms`、`postprocess_ms`、`total_ms`；统一使用 `time.perf_counter()`。对于已解码输入，`decode_ms=0` 并注明测量边界。需要明确 OpenCV 内部可能采用原生工作线程，`asyncio` 观察协程仍会被同步调用占用；真实插件应在 `initialize` 预热素材，并根据实测在调用侧使用 `asyncio.to_thread` 或受控 executor 进行 CPU 工作，同时保证对象/Frame 来源不被误用、取消后等待在途清理。无需为 SDK 创建新的 Core 调度或线程池接口。

预处理/匹配中大型临时数组按调用结束释放，不把每帧截图或分数图放进长寿命全局缓存。对重复测试记录 Python 分配、系统进程 RSS 或可得的指标，明确采样工具和数据边界，不将 tracemalloc 数值称作全部 native 内存。

## 8. 示例、素材与集成

### 8.1 离线可运行示例

添加 `examples/vision_foundation.py`：在临时目录创建 Manifest/Profile 和确定性模板、构造一帧有效 PNG/JPEG Frame，`AssetStore.load` → `decode_frame` → 多模板匹配 → 输出 `asset_id/variant_id/score/bbox/center` → `Frame.pixel_to_css()`；不依赖 CDP、真实账号或固定 cwd。示例完成后释放自身 Store；展示 `MATCHED`、`NOT_FOUND`、`AMBIGUOUS` 中至少两种结果，便于使用者理解阈值与歧义。

### 8.2 测试素材

新增小型独立、可重现的 fixture：非纯色非对称纹理模板、带 alpha/外部灰度 Mask 的模板、相近候选、多处重复目标、明确负样本，以及全图/区域、JPEG 有损和已知尺度变化的截图。所有期望类别、位置、尺寸、mask 权重和适用条件记录在人工维护的 `expected.json`；可由脚本生成输入图片，但期望数据独立于实际 matcher 输出。保留 04.1 原有 fixture 和测试不受影响。

### 8.3 真实 Browser → Plugin → Runtime 闭环

沿用 `examples/plugin_browser.py`、`examples/plugin_integration.py` 的现有组合模式以及 03 阶段 `pixel_fixture` 的独立受控页面思路。优先新增 `vision_fixture` 示例插件，使其在 `initialize` 时创建/预热 AssetStore，在 `observe` 时从注入的标准 `CaptureProvider` 获取可信 Frame，经 Vision 匹配生成 `PageState`（填真实 `source_frame_id`），在 `handle_command` 中使用**该 Frame** 将已确定的像素中心转换为 CSS 并生成 Action；由现有 `PluginRuntimeHost.execute_text()` 提交并读取 `BatchResult`，再观察页面状态变化。必要时可以重用 pixel_fixture 页面和测试工具，但需保持 BCA-03 既有示例回归正常。

受控测试页面应显示具有独特纹理、位置可计算的视觉目标，并在接收点击后以可观测方式改变状态。页面 DOM 只可供外部集成测试作为真值 oracle，插件自身通过像素识别得出业务状态。

真实测试至少覆盖：

- Edge / Chromium CDP 独立测试实例，显式 Target/Session、Provider 启停、所有权清理；不接触个人正在使用的页面。
- DPR 1 / 1.5 / 2，全图与 Browser 区域截图；已知非等比 Frame/Viewport 映射另用可复现构造测试。
- 含滚动/resize 的页面、旧观察引用 STALE、模板场景/主题选择、多位置候选与单点击确定性。
- 成功的 Frame → MatchResult → `PageState.source_frame_id` → Action/Request ID → `BatchResult` → DOM/下一次页面状态的完整对应关系。
- 导航/重绑/取消/异常退出后的关闭及任务等待；来源过期或候选歧义时插件不产生冒进操作，实际输入授权仍交由 Runtime。

真实浏览器测试沿用项目已有 `browser_integration` pytest marker，并通过显式本机 CDP endpoint 启动。未配置 CDP 时正常 skip，交接中区分模拟与真机结果。

## 9. 量化测试与验收门槛

### 9.1 功能矩阵

| 范围 | 需要覆盖 |
| --- | --- |
| 解码 | PNG/JPEG、灰度/RGB/RGBA、含 alpha、损坏与截断、尺寸不符、只读缓冲、像素上限 |
| ROI/变换 | 完整图与内部 ROI，边界、非整数、超界、结果回到 Frame 全图坐标 |
| 模板尺度 | 原尺寸、放大/缩小、非等比 `scale_x/scale_y`、模板超出 ROI、Mask 缩放 |
| 评分 | 纯色/全黑、RGB/GRAY、完美匹配、可控噪声、灰度权重 Mask、阈值边界、Oracle 对照 |
| 多候选 | 单目标、多位置、不同变体、近似分数歧义、不同候选排序、IoU/NMS、限制候选数量 |
| Assets 集成 | 不同 Profile 选择同一语义 ID 的不同模板；缓存对象共享而不被 Vision 修改 |
| Protocol/几何 | Frame ID 关联、截图像素中心、`pixel_to_css()`、DPR 和区域截图，无双重坐标换算 |
| 生命周期 | 插件初始化/关闭、取消等待、资源无悬挂与外部 Browser Session 所有权 |
| 工程 | pytest、mypy strict、Ruff、包构建、额外依赖隔离安装、完整示例 |

### 9.2 准确度标准

先构造有**独立真实标签**的固定测试集，再测量：

1. 至少 20 个明确正例，包含不同位置、ROI、RGB/Gray、Mask 和缩放；在测试集明示的场景/阈值下，正例目标命中率 **100%**。
2. 至少 20 个明确负例与干扰场景，使用同一配置时 **0 个错误有效命中**。
3. 对无歧义正例，模板定位的 bbox 左上角与人工标注相差**不超过 1 个原始 Frame 像素**，中心点误差不超过 1 px（更严格的精确合成样本应零误差）。
4. 歧义集至少 5 例，必须输出 `AMBIGUOUS`，验证不会任意选择竞争变体；多位置正确集至少 5 例，必须分别保留多个目标。
5. 将 RGB/Gray、Mask、缩放等分组独立报告，不因总计分达标掩盖某类样本失败。真实受控浏览器的点击应经 DOM 真值核验，目标落点误差按实际报告，建议最大误差 ≤1 CSS px。

如果固定数据暴露阈值与算法局限，应修复实现、调整**有独立依据**的 fixture/阈值并保留前后日志；不能从算法输出反向生成期望值。区分合成图可靠性与真实游戏图像适用性。

### 9.3 性能测量

完成可重复的本机 microbenchmark 和真实受控 Browser 集成测量，至少输出：

- 运行环境：Windows/Python、NumPy、OpenCV、Edge、CPU、DPR、截图尺寸、ROI 大小、模板数量与尺寸、尺度数、是否使用 Mask、颜色模式。
- 独立 `decode`、`preprocess`、`matching`、`postprocess`、`Vision total` 的 median/p95；Browser capture、完整 observe、Host 命令到再次状态提交的 median/p95 应分别统计，不能混算为单一算法耗时。
- 每个典型场景至少 30 个有效样本，标注 warm-up 与采样大小。提供 JSON 原始数据/统计规则及复现命令。
- 至少比较全图和 ROI、1/多模板、单/多尺度、无 Mask/带 Mask；记录循环观察时是否积压、CPU 占用及可测内存变化，重压测试需标明执行时长。
- 如某一场景耗时显著高于 Runtime 默认 100ms 观察周期，明确插件侧的 ROI、候选数、预热、CPU 卸载等建议及实测收益；不以改变已验收 Runtime 调度语义解决识别耗时。

性能验收以**可复现且有解释的统计报告**为基本门槛，按固定数据集正确性判定功能是否合格。报告可以附建议性能预算，不把跨机器的未经验证毫秒值作为硬性通过标准。

## 10. 工程验证命令

结合仓库实际 Windows venv 路径执行（具体输出和 skip 数由 Codex 实测记录）：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,assets,vision]"
.\.venv\Scripts\python.exe -m pytest tests/plugin_sdk/vision -q -W error --basetemp=.test-artifacts/pytest-04.2-vision
.\.venv\Scripts\python.exe -m pytest -q -W error --basetemp=.test-artifacts/pytest-04.2-full
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe examples/vision_foundation.py
```

真实 Edge 测试由专用脚本/pytest 入口显式传入 `$env:BCA_CDP_ENDPOINT` 并记录 CDP 端口、所有权与清理状态。重新跑完上游专项及全量回归，保留已有测试通过数的差异解释；04.1 报告基线为 Assets `127 passed`、全量 `624 passed / 36 skipped`（无真实 CDP），**这是此前本地证据，不是 04.2 结果**。

在隔离 venv 中测试基础安装只导入 Core/Plugin 接口、`assets` 安装、`vision` extra 安装与 wheel/sdist 安装；确认资源与 Vision 文件都已打包、示例可从不同 cwd 运行。根据实际安装结果更新依赖锁定建议、导入边界及源文件检查数。

## 11. 交付文档与源码审查要求

### `docs/VISION.md`

准确描述公开入口与签名、RGB/GRAY、DecodedFrame/ROI、遮罩/尺度/评分公式、NMS、歧义、匹配结果/错误类型、坐标空间及 Frame 生命周期、独立使用代码、性能测量口径、CPU/async 边界，以及与 `docs/ASSETS.md` 的关系。

### `docs/BCA-04.2_HANDOFF.md`

至少包括：

1. 实际 HEAD/工作区来源，新增和修改文件，代码入口与调用示例。
2. 已定稿接口、阈值与算法设计、候选排序/歧义规则、Mask/缩放/ROI 语义、异常类别。
3. 固定测试集规模、分组正负/歧义结果、定位误差及真实浏览器证据。
4. 运行命令、测试数、失败与跳过数量、mypy/Ruff/构建安装结果，明确独立本机验证的范围。
5. 性能 JSON 与原始日志路径、统计定义、内存/线程/资源清理结论。
6. 已知风险、依赖版本、平台未测项、需要架构主会话协调的问题。

### `docs/BCA-04_MAIN_SYNC.md`

形成可供 BCA-05/06/07 读取的完整 04 阶段跨模块同步：04.1 资源 API 与格式、04.2 视觉 API 与分数、Manifest/Profile、缓存所有权、Frame/坐标、Plugin/Runtime 集成、安装 extras、实际验收测试和性能、限制与后续建议。准确引用 `docs/BCA-04.1_HANDOFF.md` 与 `docs/BCA-04.2_HANDOFF.md`，不要把任务书当作实现证据。

中文 Markdown 均以 UTF-8 保存，生成后严格解码校验中文正文无替换字符，避免此前 PowerShell 文本管道产生的编码损坏。所有文档要与真实源码相符；`git diff --check` 检查当前修改。项目总纲与仓库根 README 的正式验收状态更新由架构主会话在审核 BCA-04 全阶段后协调。

## 12. 交付条件与最终报告

完成后应能展示一条可追溯完整链路：

```text
AssetStore (semantic ID, profile, variant)
    → readonly LoadedTemplate (RGB / mask)
CaptureProvider.capture() → Frame
    → decode_frame / ROI / match_templates
    → MatchResult (frame_id, pixel bbox/center, score, ambiguity)
    → Plugin.observe() / PageState.source_frame_id
    → Runtime StateStore commit / trusted ActionObservationRef
    → PluginRuntimeHost.execute_text()
    → ActionBatch / Browser Input
    → next observation + external DOM test oracle
```

最终向本子会话交付：**源码及测试结果、`docs/VISION.md`、`docs/BCA-04.2_HANDOFF.md`、`docs/BCA-04_MAIN_SYNC.md`、原始性能 JSON/日志索引、可供主会话审核的 commit/diff 状态**。首次完成实现与本地测试后先提供清晰交接证据，再由架构主会话做 BCA-04 的正式源码验收。

---

**执行说明：** 以此文件作为本阶段 Codex 唯一实施任务书；先核对仓库并分小批提交，实现顺序建议为 `Frame/ROI/评分` → `候选/NMS/多尺度` → `离线示例与单测` → `真实插件链路` → `性能/质量/交接`。各批次保留测试结果，实际公开签名发生调整时同时更新文档。不要在未执行的环境上宣称测试通过。
