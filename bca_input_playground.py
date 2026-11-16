"""BCA screenshot-gated click playground (Protocol 2, Edge CDP).

The gate decision is made exclusively from decoded screenshot PNG pixels.
The page is queried only for initial readiness, never for gate state.

Run from the BCA repository root:
    python bca_input_playground.py
"""

import asyncio
import io
import sys
import time
from urllib.parse import quote

from PIL import Image

from bca.core.browser import BrowserCaptureProvider, BrowserInputProvider, BrowserSession
from bca.core.protocol import Action, ActionStatus, ActionType, Frame, MouseButton

ENDPOINT = "http://127.0.0.1:9222"
INTERVAL_SECONDS = 1.0
# Both coordinates refer to the visible page's CSS viewport, not document pixels.
SIGNAL_CSS = (105.0, 195.0)
COUNTER_BUTTON_CSS = (320.0, 203.0)

HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>BCA · 截图判断与视觉门控</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f6fc;color:#23314d;
font:16px system-ui,'Microsoft YaHei',sans-serif}
main{max-width:760px;margin:24px auto;padding:24px 30px 36px;background:#fff;
border-radius:18px;box-shadow:0 8px 32px #1e35531b}
h1{font-size:24px;margin:0 0 12px}p{color:#53647f;line-height:1.6}
#signal{position:fixed;left:45px;top:135px;width:120px;height:120px;background:rgb(220,38,38);
border:5px solid #f9fbff;border-radius:16px;box-shadow:0 0 0 2px #a7b4c8;transition:background .12s}
#toggle{position:fixed;left:210px;top:145px;width:220px;height:44px;border:0;border-radius:10px;background:#355cbd;color:#fff;font-size:16px;cursor:pointer}
#target{position:fixed;left:210px;top:194px;width:220px;height:48px;border:0;border-radius:10px;background:#efe6fe;color:#53299a;font-size:17px;font-weight:bold;cursor:pointer}
#count{position:fixed;left:210px;top:251px;font-size:19px;font-weight:bold}
#status{position:fixed;left:45px;top:265px;width:390px;color:#41516d;font-size:14px}
#log{margin-top:350px;white-space:pre-wrap;font:13px ui-monospace,Consolas,monospace;color:#596b85}
</style></head><body>
<main><h1>🌸 BCA 视觉门控实验</h1>
<p>手动点击“切换信号颜色”。BCA 每秒重新截图，只根据图像中的色块决定是否点击右侧计数按钮。</p>
<div id="signal" aria-label="视觉信号色块"></div>
<button id="toggle">切换信号颜色（红 ⇄ 绿）</button>
<button id="target">由 BCA 自动点击</button>
<div id="count">自动点击次数：0</div>
<div id="status">当前：红色。BCA 应该停止点击。</div>
<div id="log">网页点击记录：\n</div>
</main>
<script>
let isGreen=false, count=0;
document.getElementById('toggle').addEventListener('click',()=>{
  isGreen=!isGreen;
  document.getElementById('signal').style.backgroundColor=
    isGreen?'rgb(22, 172, 74)':'rgb(220, 38, 38)';
  document.getElementById('status').textContent=isGreen?
    '当前：绿色。BCA 应该每秒点击一次。':'当前：红色。BCA 应该停止点击。';
});
document.getElementById('target').addEventListener('click',()=>{
  count++;
  document.getElementById('count').textContent='自动点击次数：'+count;
  document.getElementById('log').textContent+='✔ '+new Date().toLocaleTimeString()+' 收到 click\n';
});
</script></body></html>"""


def classify_signal(frame: Frame) -> tuple[str, tuple[int, int, int]]:
    """Sample the middle of the signal block from actual screenshot pixels."""
    v = frame.viewport
    css_x, css_y = SIGNAL_CSS
    if not (v.capture_x <= css_x < v.capture_x + v.capture_width):
        raise RuntimeError("信号色块超出了截图水平范围，请扩大 Edge 窗口")
    if not (v.capture_y <= css_y < v.capture_y + v.capture_height):
        raise RuntimeError("信号色块超出了截图垂直范围，请扩大 Edge 窗口")

    px = int((css_x - v.capture_x) * frame.width / v.capture_width)
    py = int((css_y - v.capture_y) * frame.height / v.capture_height)
    with Image.open(io.BytesIO(frame.data)) as raw:
        rgb = raw.convert("RGB")
        # Small neighborhood median: robust against single-pixel noise and DPR variations.
        samples = []
        for yy in range(max(0, py - 2), min(rgb.height, py + 3)):
            for xx in range(max(0, px - 2), min(rgb.width, px + 3)):
                samples.append(rgb.getpixel((xx, yy)))
    color = tuple(sorted(c[i] for c in samples)[len(samples) // 2] for i in range(3))
    r, g, b = color
    if g > 110 and g > r * 1.6 and g > b * 1.3:
        return "GREEN", color
    if r > 110 and r > g * 1.6 and r > b * 1.5:
        return "RED", color
    return "UNKNOWN", color


async def main(endpoint: str) -> None:
    session = BrowserSession(endpoint)
    capture = BrowserCaptureProvider(session)
    input_provider = BrowserInputProvider(session)
    try:
        await session.connect()
        url = "data:text/html;charset=utf-8," + quote(HTML)
        created = await session.connection.send("Target.createTarget", {"url": url})
        page_id = created["targetId"]
        await session.bind(page_id)
        await session.connection.send("Target.activateTarget", {"targetId": page_id})
        await capture.start()
        await input_provider.start()

        # Only setup readiness uses JavaScript; never read the gate status via DOM/JS.
        for _ in range(50):
            response = await session.send(
                "Runtime.evaluate",
                {
                    "expression": (
                        "document.readyState === 'complete' && !!document.getElementById('signal')"
                    ),
                    "returnByValue": True,
                },
            )
            if response.get("result", {}).get("value") is True:
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("实验页面加载超时")

        print("\n🌸 视觉门控实验已打开：请保持测试标签页在前台。", flush=True)
        print("用鼠标点击网页里的【切换信号颜色】按钮，观察计数变化。", flush=True)
        print("判定只读取 BrowserCaptureProvider.capture() 返回的 PNG 像素。", flush=True)
        print("按 Ctrl+C 停止脚本，网页标签页会保留。\n", flush=True)
        number = 0
        while True:
            start = time.monotonic()
            frame = await capture.capture(page_id)
            status, rgb = classify_signal(frame)
            number += 1
            if status == "GREEN":
                result = await input_provider.execute(
                    Action(
                        page_id=page_id,
                        type=ActionType.MOUSE_CLICK,
                        x=COUNTER_BUTTON_CSS[0],
                        y=COUNTER_BUTTON_CSS[1],
                        button=MouseButton.LEFT,
                    )
                )
                if result.status is not ActionStatus.SUCCEEDED:
                    raise RuntimeError(f"点击失败：{result.error}")
                result_text = "已发送点击 ✓"
            elif status == "RED":
                result_text = "红灯，跳过点击"
            else:
                result_text = "颜色不明确，安全跳过"
            print(f"[{number:04d}] PNG像素 RGB={rgb} | {status:<7} | {result_text}", flush=True)
            await asyncio.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - start)))
    finally:
        await input_provider.close()
        await capture.close()
        await session.close()


if __name__ == "__main__":
    endpoint = sys.argv[1] if len(sys.argv) > 1 else ENDPOINT
    try:
        asyncio.run(main(endpoint))
    except KeyboardInterrupt:
        print("\n实验已结束，页面仍保留在 Edge 中。")
