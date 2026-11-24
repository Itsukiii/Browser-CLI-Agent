# LITE-02.1 OCR 资源

本阶段选用 MaaCommonAssets 的英文 PP-OCRv3 ONNX 转换物，固定 commit `dabcd4681ac990dc4361de26416d986abd80e4aa`，路径 `OCR/ppocr_v3/en_us`。模型不提交 Git、不打入 wheel；import/start/pytest 均不会自动联网下载。

来源：[固定版本目录](https://github.com/MaaXYZ/MaaCommonAssets/tree/dabcd4681ac990dc4361de26416d986abd80e4aa/OCR/ppocr_v3/en_us)。上游 README 指向 PaddleOCR `795c81f1835725dbf9bf9f5a13e0c793dfd5f243` 的英文 PP-OCRv3 det/rec 模型。保留 `ppocr-v3-en-UPSTREAM.md`、MaaCommonAssets MIT 许可和 PaddleOCR Apache-2.0 许可原文。许可证标识描述来源仓库；本阶段仅显式本地加载这些校验过的转换物，未增加模型再分发渠道。

`ppocr-v3-en.json` 记录来源、版本、许可证、大小、SHA256；OCRModelSpec 在 native worker 读取并逐文件校验，然后 `Resource.post_ocr_model(directory)` 加载。模板 Bundle 不得带隐藏 `model/ocr`，模型路径通过独立参数提供。

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| det.onnx | 2423224 | 8fe4bf6abfb20402357827f2efc964c8b28cf980e29fe09a99b742ae29725fa9 |
| rec.onnx | 8956702 | da12c6e863761d774b07d3bd40fbaaa55516f90570e0b1dd9dc112e457301cc9 |
| keys.txt | 190 | 5662df9d2d03f0e8ca0d3b0649d6acbab904b6a14b3d3521463c71c37c668ce3 |

明确执行以下命令可准备本地模型；这是人工 provisioning，不是测试隐含步骤：

```powershell
New-Item -ItemType Directory -Force .maa-models/ppocr-v3-en | Out-Null
$modelBase = 'https://raw.githubusercontent.com/MaaXYZ/MaaCommonAssets/dabcd4681ac990dc4361de26416d986abd80e4aa/OCR/ppocr_v3/en_us'
foreach ($modelFile in @('det.onnx', 'rec.onnx', 'keys.txt')) {
    Invoke-WebRequest "$modelBase/$modelFile" -OutFile ".maa-models/ppocr-v3-en/$modelFile"
}
$env:BCA_OCR_MODEL = (Resolve-Path .maa-models/ppocr-v3-en).Path
```

离线机器可复制这三个文件并设置 BCA_OCR_MODEL；哈希一致才加载。未设置环境变量时 22 个使用该真实模型的测试明确 skip；缺模型诊断、hash 错误和 native 无模型探针仍执行。

## 测试图像来源

`tests/lite/vision_fixture.py` 用 NumPy seed=20261124 生成 36×28 彩色模板，页面为 480×240 白底，标签和位置由测试参数给定。不存在第三方网页或私人截图。

数字由 Pillow 12.3.0 的 `ImageFont.load_default(48)`（Aileron Regular）渲染。字体作者 Sora Sagano / dot colon 的[官方发布页](https://dotcolon.net/fonts/aileron/)声明 No Rights Reserved、允许修改和再分发；本仓库只保存生成的 PNG，不复制字体二进制。Pillow 自身遵循 [MIT-CMU 许可](https://github.com/python-pillow/Pillow/blob/12.3.0/LICENSE)。模型和字体不应被混称为项目原创素材。
