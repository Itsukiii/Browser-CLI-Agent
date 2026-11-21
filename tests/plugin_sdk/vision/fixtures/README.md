# 固定视觉测试集

expected.json 的标签来自预设画布粘贴位置，不读取 matcher 的输出。generate.py 只用 NumPy/Pillow 重建输入图片和布局标签，不导入 Vision。修改标签需审查粘贴位置与样本语义，不能根据测试失败反向改为算法输出。

共有 32 个正例、32 个负例，按 RGB、GRAY、权重 Mask、放大、缩小、非等比、JPEG、ROI 八组各4正4负。统一阈值0.96；负例包含左右反转的非对称纹理干扰。另有6个同位置不同语义 ID 的歧义场景、6个重复目标场景。坐标和中心均按原始 Frame 像素，合成布局要求零定位误差。

texture.png 是固定种子7042生成的非对称彩色纹理。alpha.png 的第一块alpha=128，其余255；外部mask权重按四块0/64/128/255排列，合并后期待值见 expected.json。此集首块外部mask=0，另有独立 Assets 和评分 oracle 测试验证非零 alpha 组合及灰度权重，不把全零位置作为唯一遮罩证据。

截图输入由Pillow生成，放大用BILINEAR、缩小用BOX，与OpenCV实现分离。JPEG质量98、subsampling=0；测试会再次编码，覆盖实际有损解码，结论仅针对该测试质量。PNG保持精确像素。区域像素到CSS、DPR和非等比Viewport另由 test_geometry.py 验证。
