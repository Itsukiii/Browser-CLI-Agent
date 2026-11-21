# BCA-04 / Vision & Assets 跨模块同步

2026-11-21，供BCA-05/06/07和架构主会话接入。04.1已在提交 `fe151645beaa7bfbaa4dcb19dc5499cbe48fdf01` 中；04.2实现与证据位于其上的本地diff，待主会话正式源码验收。包0.2.0、Protocol2不变。实施事实来自 [04.1交接](BCA-04.1_HANDOFF.md)、[04.2交接](BCA-04.2_HANDOFF.md) 和实际源码；任务书不是通过证据。

## 安装与职责

基础包只需要websockets、Pillow，Core不导入NumPy/OpenCV。`[assets]` 增加numpy>=2.4,<3；`[vision]` 增加相同NumPy约束和opencv-python-headless>=4.14,<5。实际Windows/Python3.14.7验证已通过独立基础、assets、vision、wheel和sdist安装；不同时安装多个提供cv2的OpenCV发行包。其他Python/平台矩阵未测。

Assets负责可信本机素材、Manifest/Profile、选择、只读像素和缓存；Vision负责Frame解码、ROI/缩放、像素评分与候选；插件解释业务状态和命令；Runtime单独负责发布状态、来源授权及输入协调。SDK没有引入Core状态机、动作通道或Protocol序列化类型。

## Assets契约

```text
AssetStore(root: Path, *, manifest="manifest.json", profile: Path|None=None,
           cache_limit_bytes=64*1024*1024)
  ids() / variants(asset_id)
  resolve(asset_id, *, scene=None) -> AssetSelection
  load(asset_id, *, scene=None) -> LoadedTemplate
  invalidate(asset_id=None) / clear_cache() / cache_info() / close()
  profile: AssetProfile
```

Manifest v1严格JSON，assets数组中的id唯一，每项default_variant必须存在，variants包含path及可选scene/theme/size/mask。路径受root约束，拒绝绝对/穿越、Windows设备名与非法文件名、损坏文件或身份变化。Profile为严格INI，`[profile]`含name及可选theme/default_scene，`[variants]`支持`asset`和`asset@scene`覆盖。未知键、重复、非有限值、无效引用显式报错。

选择有效scene按显式参数→Profile→默认变体；覆盖优先于自动候选。自动候选按场景再主题精确度，默认变体仅打破最高分同分，剩余歧义抛AssetSelectionError。不要以Manifest排列顺序选择模板。

LoadedTemplate包含asset_id/variant_id/image/mask/width/height/source/selection。image是bytes-backed只读C连续RGB uint8；mask为None或H×W uint8权重。Alpha与外部Mask在Assets合并：`(alpha*external+127)//255`；Vision不能重新当成二值Mask。静态PNG/JPEG上限16,777,216像素，编码文件128MiB。

每Store独立64MiB LRU，RLock保护读取、身份复核、解码、缓存与close；相同key返回同对象，计费image+mask字节。文件dev/ino/size/mtime_ns变更触发失效，保留元数据的原地修改须显式invalidate。Manifest/Profile变化需新建Store。已返回模板在淘汰/关闭后仍可读；close幂等，后续操作AssetClosedError。调用方不得修改只读ndarray的元数据。完整格式与错误表见 [ASSETS.md](ASSETS.md)。

## Vision契约

`decode_frame(Frame)->DecodedFrame`；`match_templates(decoded, templates, *, options=MatchOptions())->MatchResult`；`match_frame`为一次解码包装。模型及错误统一从`bca.plugin_sdk.vision`导出。

Frame只接受完整可解码8位PNG/JPEG并复核实际尺寸；透明截图合成黑底，输出不可变RGB视图。ROI半开、非负整数且完全在Frame内。RGB/GRAY、两轴显式尺度[.25,4]、最多16尺度；结果始终是原始Frame像素，不预先转CSS。

评分是带平方权重的归一化RMSE相似度：`clip(1-sqrt(sum(((T-I)*W)^2)/(C*255²*sum(W²))),0,1)`；W=mask/255，C=3或1。支持纯色/黑模板，最高提案用float64复核。相似度不是统计概率，阈值须按业务数据校准。

MatchOptions默认threshold=.96、roi=None、mode=RGB、scales=((1,1),)、nms_iou=.45、ambiguity_margin=.02、max_results=32、max_proposals_per_variant=128。同模板NMS，异身份同位置竞争；多个不重叠对象允许多命中，相近竞争输出AMBIGUOUS。固定排序、1e-9比较容差、提案与输出截断诊断见 [VISION.md](VISION.md)。不能在AMBIGUOUS时使用best_candidate自动点击。

结果含Frame/page ID、status、matches、ambiguous、best_candidate、reason、timing、options和diagnostics。候选含ID/变体、bbox/center、score/threshold、尺度及完整AssetSelection来源。reason为matched/below_threshold/template_larger_than_roi/ambiguous_candidates。非法输入、解码失败、执行失败分别为vision.input/vision.decode/vision.match；正常未命中和歧义不是异常。

## Frame、插件与Runtime接入

```text
initialize: AssetStore + Profile → 预热LoadedTemplate
observe: 标准CaptureProvider → FreshnessCaptureAdapter → 可信Frame
       → Vision → 插件业务PageState(source_frame_id=frame.frame_id)
       → Runtime唯一publish/commit → 可信ActionObservationRef
execute_text: Host保存原引用 → 插件在同一Frame上pixel_to_css(center)
       → Action(request_id) → ActionBatch → Runtime/Input → BatchResult
       → 新观察/业务状态核验
```

Frame中心为x+(width-1)/2、y+(height-1)/2。`pixel_to_css`已经处理capture偏移及两轴比例，不能再乘除DPR或叠加scroll。区域截图也必须使用自己的Frame，不借用之前全图坐标。SDK模型不授权动作，分数不能替代BrowserFreshness；旧引用STALE时不能换新引用重试旧动作。

插件observe不自行发布，handle_command不执行Input。示例vision_fixture在initialize预热、observe用to_thread卸载；取消后等待native工作，之后关闭自身Store/临时资源。Host/Manager/Controller、Provider、Session、Store/Bus分别按既有所有权关闭；插件不关闭外部BrowserSession。Composition示例不是新Core公共接口。

## 实测与性能边界

04.1原127项资源测试保留。04.2固定数据集32正、32负、6歧义、6双位置：统一阈值.96，正例全部命中、负例无错误有效命中、合成位置零误差。真实独立Edge两主题、DPR1/1.5/2、全图/区域共360次点击，Frame→state→request/action/batch→下一状态可追溯；分别核验Action浮点坐标与DOM整数事件坐标，相对目标中心误差均不超过1 CSS px，具体数值见verification.json。生命周期、STALE、歧义拒绝与取消等待另有真实测试。

最终测试数、日志、安装、清理及源码摘要见 [verification.json](evidence/BCA-04.2/verification.json)。离线与浏览器原始30样本/场景性能数据分别见 [offline.json](evidence/BCA-04.2/offline.json)、[browser.json](evidence/BCA-04.2/browser.json)。分开报告decode/preprocess/match/postprocess/Vision total、capture、observe、Host到新提交的median/p95，不把它们混为算法耗时。

DPR升高、多模板/多尺度全图可明显超过Runtime默认100ms；ROI和明确尺度有直接收益，但区域截图仍有完整capture开销。Scheduler跳过过期tick，不积压补跑；不要为了宣称10Hz改变调度语义。CPU卸载保持事件循环可响应，不代表计算更快。每次调用结束释放大临时数组，无长寿命Frame/map缓存。

内存证据仅101次离线循环和15秒真实持续观察；tracemalloc为Python、PSAPI为Python进程工作集，不等于所有Edge/OpenCV内存的分项。真实游戏/WebGL、复杂动画/遮挡、长期稳定性、其他OS/Python版本未验。后续模块需按实际素材建立独立标签并校准阈值，正式BCA-04状态与总纲由主会话审核后更新。
