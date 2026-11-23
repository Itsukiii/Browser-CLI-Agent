# BCA-lite / LITE-01 · MaaFramework CDP Bridge

> Branch: lite. MaaFramework baseline: v5.16.1. Initial integration commit, **not** full functional acceptance.

> Historical experiment description. Current implementation, native/Edge evidence,
> coordinate policy and remaining acceptance gaps are in
> [LITE-01_HANDOFF](lite/LITE-01_HANDOFF.md). In particular, the bridge now uses
> owner-loop serialization, explicit drain, and raw-size screenshots by default.

## Goal

Use BCA-01's already implemented, explicitly bound Chromium/Edge CDP session as the screenshot/input backend of MaaFramework's Python CustomController. MaaFramework will later own most general-purpose recognition, resources and task execution. BCA-lite retains browser Target selection, observation provenance, and interactive CLI state.

## First vertical slice

- bca.lite.bridge.CDPBridge: borrows BrowserSession, started BrowserCaptureProvider and BrowserInputProvider, plus a running owner event loop. Synchronous callback operations are submitted via asyncio.run_coroutine_threadsafe. Callbacks made on the owner event loop are rejected to prevent deadlock.
- bca.lite.maa_controller.MaaCDPController: MaaFramework CustomController implementing connect, connected, request_uuid, screencap and click. One fresh screenshot currently permits at most one click; other operations return failure.
- Screenshot returns full-resolution **BGR** numpy.ndarray. Click positions are translated using Frame.pixel_to_css to CSS viewport coordinates. Maa's optional internal screenshot scaling must be checked with non-720p real-browser tests.
- Click requires unchanged Target/session/generation, browser geometry/document fingerprint, and a recent screenshot (<2 seconds by default). Reused screenshots are rejected; uncertain results are not retried. A callback timeout blocks further bridge operations until recreated.
- The application owns Session/Provider shutdown. bridge.invalidate() prevents later callbacks and must be called only after in-flight Maa jobs are joined.

## Install and smoke

~~~powershell
python -m pip install -e ".[lite,dev]"
python examples/browser_session.py --endpoint http://127.0.0.1:9341
python examples/lite_maa_cdp_smoke.py --endpoint http://127.0.0.1:9341 --target-id YOUR_TARGET_ID
~~~

Use an isolated local CDP browser and an owned test page. The optional --click X Y emits one intentional click using raw screenshot pixels. This first smoke exercises Maa's **controller API**; Vision/OCR and Windows real-browser verification remain follow-up gates.

## Next acceptance gates

1. Install MaaFW v5.16.1 on Windows Python and run a real Edge smoke including DPR 1/1.5/2, raw images and internal Maa scaling; compare actual DOM event coordinates.
2. Drive MaaTasker.post_recognition using a real captured image, and verify Maa Resource / Vision outputs and matching coordinates.
3. Test callbacks, timeouts, cancelation, Target navigation/disconnect, native callback threads, provider cleanup and no stale click across same-document UI changes.
4. Add safe multi-action command coordination for Quiz Demo before supporting two clicks against one observation.
5. Record pytest, mypy/Ruff and live Edge logs before declaring the adapter accepted.

## Upstream reference

- [Maa CustomController](https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/controller.py)
- [Maa Tasker](https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/tasker.py)
- [Maa API](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/zh_cn/2.2-集成接口一览.md)
