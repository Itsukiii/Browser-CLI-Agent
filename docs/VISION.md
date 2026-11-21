# Vision SDK：模板匹配与坐标

安装 `pip install "browser-cli-agent[vision]"`。Vision 使用 NumPy 和 OpenCV headless；Core、Protocol、Plugin 接口不会隐式导入这些可选依赖。素材加载与主题选择见 [ASSETS.md](ASSETS.md)，实施证据见 [BCA-04.2_HANDOFF.md](BCA-04.2_HANDOFF.md)。

## 公开入口

全部从 `bca.plugin_sdk.vision` 导入：

```python
decode_frame(frame: Frame) -> DecodedFrame
match_templates(decoded: DecodedFrame, templates: Sequence[LoadedTemplate], *,
                options: MatchOptions = MatchOptions()) -> MatchResult
match_frame(frame: Frame, templates: Sequence[LoadedTemplate], *,
            options: MatchOptions = MatchOptions()) -> MatchResult
```

默认选项是不可变共享实例。`match_frame` 只解码一次；已持有 DecodedFrame 时使用 `match_templates` 复用像素。没有全局截图、分数图或模板缓存，没有后台线程池。类型均为 SDK 本地模型，不进入 Protocol 2 codec。

| 模型 | 字段及含义 |
| --- | --- |
| DecodedFrame | frame：同一来源对象；image：只读 RGB uint8 H×W×3 |
| PixelRect | x/y/width/height，原始 Frame 整数像素半开矩形 |
| MatchOptions | threshold=.96、roi=None、mode=RGB、scales=((1,1),)、nms_iou=.45、ambiguity_margin=.02、max_results=32、max_proposals_per_variant=128 |
| MatchCandidate | asset_id、variant_id、frame_id、bbox、center、score、threshold、scale_x/y、selection |
| VisionTiming | decode_ms、preprocess_ms、match_ms、postprocess_ms、total_ms |
| MatchResult | frame_id、page_id、status、matches、ambiguous、best_candidate、reason、timing、options、diagnostics |

`selection` 保留 Assets 的 AssetSelection，含规范化素材路径、manifest/profile 来源、scene/theme 与 selected_by。状态枚举 MatchStatus 为 matched / not_found / ambiguous；PreprocessMode 为 rgb / gray。

选项数值只接受内建 int/float，拒绝 bool、NaN/inf。threshold、nms_iou、ambiguity_margin 均在闭区间 [0,1]。ROI 非负、宽高正、精确 int，且必须在 Frame 内。尺度使用不可变 tuple 的 tuple，1～16 对，两轴均在 [0.25,4]。两个数量限制均为 1～4096。每次传入 1～256 个 LoadedTemplate；同一 asset_id/variant_id 重复输入报错，避免不同快照被误当成一个候选身份。

## 解码与只读缓冲

输入必须是有效 Protocol Frame。检查编码声明、Pillow verify、完整 load、图像尺寸和单帧约束，再以 OpenCV imdecode(IMREAD_UNCHANGED) 解码。Pillow 的两步完整性检查开销包含在 decode_ms 中；不是只检查文件头。

接受 8 位 PNG/JPEG，灰度转 RGB、BGR 转 RGB；RGBA/BGRA、LA、调色板透明度由解码器转换后按黑色背景合成。逐通道合成是 `(color * alpha + 127) // 255`，中间为 uint16。拒绝 16 位、CMYK、动画、异常通道、损坏/截断、编码与元数据不符。像素上限 16,777,216，编码字节上限 128 MiB。EXIF 不参与坐标旋转。

输出通过不可变 bytes 支撑 NumPy 视图，C 连续、uint8，不能写像素或重新启用 WRITEABLE。模板、mask 同样须满足 Assets 的只读与维度约束，边界会复核。消费者不得修改 ndarray 的 shape/dtype 等对象元数据；需要可写内容时自行 copy。Assets 关闭或缓存淘汰不使已取得模板失效。

## ROI、模式、缩放与坐标

ROI 只限制搜索窗口，输出 bbox 会加回 ROI 原点。GRAY 使用 OpenCV COLOR_RGB2GRAY（BT.601 权重及 OpenCV 8 位舍入），一次调用所有模板使用同一模式。

缩放只作用于模板和 mask：尺寸为 `max(1, floor(original * scale + .5))`。两轴均不放大时 INTER_AREA，否则 INTER_LINEAR。Mask 以 float32 线性插值、floor(value+.5) 舍入到 uint8，然后除以255；缩放后有效权重全零报输入错误。相同输出尺寸只算一次，按尺度字典序取第一对。比 ROI 大的尺度跳过；全部过大返回 template_larger_than_roi。

中心是 `(x+(width-1)/2, y+(height-1)/2)`，是像素中心索引。不要在 Vision 中添加 capture_x/y、scroll 或再乘除 DPR。完整截图和区域截图各自使用自己的 Frame，最终只调用该帧的 `frame.pixel_to_css(*candidate.center)`。这支持两个轴的非等比映射。

```python
from pathlib import Path
from bca.plugin_sdk.assets import AssetStore
from bca.plugin_sdk.vision import MatchOptions, MatchStatus, PixelRect, match_frame

store = AssetStore(Path("assets"), profile=Path("light.ini"))
try:
    template = store.load("ui.confirm", scene="dialog")
    # frame 来自调用方标准 CaptureProvider。
    result = match_frame(
        frame, [template], options=MatchOptions(roi=PixelRect(x=20, y=20, width=160, height=100))
    )
    if result.status is MatchStatus.MATCHED:
        css = frame.pixel_to_css(*result.matches[0].center)
finally:
    store.close()
```

## 分数与候选

OpenCV TM_SQDIFF 产生完整 float32 SSD map。Mask 为 `W=mask/255` 浮点权重，缺省 W=1，遵循 [OpenCV 官方平方权重公式](https://docs.opencv.org/4.x/df/dfb/group__imgproc__object.html)：

```text
SSD = sum(((T-I)*W)^2)
D = C * 255^2 * sum(W^2)       # C=3 RGB，C=1 GRAY；float64 汇总
score = clip(1-sqrt(max(SSD,0)/D), 0, 1)
```

纯色、全黑模板也能匹配。微小负 SSD 截为0并记录 negative_ssd_clamped；非有限输出抛 VisionMatchError。局部提案再以 float64 对原始像素块重新计算分数，修正 OpenCV float32 消减误差，完全相同的有效像素得到1。权重沿用 float32 mask，不二值化。**分数和阈值是像素相似度指标，不是统计概率。**

每个模板×尺度先保留3×3局部最大值，使用确定性 minMaxLoc 扫描及空间 IoU 抑制生成有界提案，不枚举纯色图的全部平台位置。等分峰值按 y、x 扫描。每尺度临时提案最多 max_proposals_per_variant；跨尺度排序、同变体 NMS 后，每变体保留至多此数量。峰值搜索基于 OpenCV float32 map，候选排序使用复核后的分数；资源上限意味着这不是无限目标的穷举定位器。诊断 proposal_limit_reached 表示扫描达到限制，应缩小 ROI 或调整上限。

稳定排序键：`(-score, asset_id, variant_id, y, x, scale_x, scale_y)`；不依赖 manifest 或输入模板排列顺序。分数精确排序，只有阈值、IoU 和歧义边界比较采用绝对容差 1e-9：score+eps >= threshold、IoU > nms_iou+eps、分差 <= ambiguity_margin+eps。

先同变体跨尺度 NMS，再以排序后的最高候选为锚点，将与它重叠超过 nms_iou 的不同身份候选作为同位置竞争组。按锚点比较，不按重叠传递闭包连接远处对象。分差在 ambiguity_margin 内的竞争者形成 ambiguous 组，该区域不输出确定 matches；差距明显则只保留最高者。多个不重叠位置可各有命中，不因此判歧义。nms_iou=1 会关闭重叠抑制与竞争分组，调用方通常应保留默认值。

只要有未解决竞争，整体 AMBIGUOUS。状态在输出截断前确定，不能因限制输出而隐藏歧义状态。matches 最多 max_results 个；ambiguous 总候选最多 max(2,max_results) 个，以保证至少能表达一对竞争者，后续组可截断或省略，记录 result_limit_reached。结果中的候选和竞争组保持上述稳定顺序。

因此两类输出合计最多 `max_results + max(2,max_results)` 个候选，best_candidate另持有一个诊断引用。需要更小响应的调用方应同时缩小候选/结果上限并保留整体status判断。

best_candidate 在未命中时仍可提供最高提案作为诊断；NOT_FOUND 的 matches 为空。歧义时 best_candidate 也不能被当作确定目标。业务插件必须检查 status，再按自身策略处理多位置目标。

| reason | 含义 |
| --- | --- |
| matched | 至少一个确定候选，无歧义 |
| below_threshold | 有可比较提案，但都未达阈值 |
| template_larger_than_roi | 所有模板尺度均无法放进窗口 |
| ambiguous_candidates | 存在无法确定身份的空间竞争 |

## 异常、耗时与异步边界

VisionError 继承 BCAError；VisionInputError / VisionDecodeError / VisionMatchError 的 code 分别为 vision.input / vision.decode / vision.match，基类为 vision.error。输入/选项、完整性/解码、OpenCV执行失败有独立错误类型。普通未命中、歧义不是异常。错误默认消息不包含图像数据；底层 cause 保留用于受控调试。AssetStore 自身的错误保持 Assets 原类型。

perf_counter 测量：decode 含完整性验证与 RGB 转换；preprocess 含输入校验、ROI、模板/Mask缩放和灰度；match 含 OpenCV SSD 与 map 分数归一化；postprocess 含峰值/NMS、候选 float64 复核、竞争判定和结果限制。total 含包装与未单列开销，不要求分项相加严格相等。预解码调用 decode_ms=0。

SDK 同步执行，OpenCV 自身可能启用原生线程；直接在 observe 协程调用仍会占用事件循环。示例插件在 initialize 预热 AssetStore，在 observe 中用 asyncio.to_thread；取消不会强杀原生任务，必须 shield 并等待在途工作结束后才能释放自身资源。结果只供业务解释，不会自动发布状态、创建可信引用或执行动作。

`examples/vision_foundation.py` 展示离线 MATCHED/AMBIGUOUS。`examples/vision_integration.py` 通过 Catalog/Manager/Host 接入真实 Browser，插件只看像素，DOM 仅由外部测试作为真值。旧来源引用仍由 Runtime 判 STALE；分数高不能覆盖来源授权。示例页面是已知尺度与纹理的受控测试页，不能据此推断真实游戏识别准确率。

性能复现：`python examples/vision_benchmark.py --samples 30`；浏览器：`python examples/vision_integration.py --endpoint http://127.0.0.1:9341 --samples 30`。报告保存原始数组，p95 为排序后 ceil(n*.95)-1，分别统计 capture、observe、Vision 与命令到新提交。tracemalloc 仅代表 Python 分配；Windows PSAPI WorkingSetSize 是整个 Python 进程工作集，包含但不单独分离 OpenCV 原生内存，均不包含 Edge 进程。短循环没有单调增长不能证明长期无泄漏。
