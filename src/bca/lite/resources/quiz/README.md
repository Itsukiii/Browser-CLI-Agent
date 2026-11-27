# BCA Quiz controlled assets

Original HTML/CSS/JavaScript written for this project. No external images, fonts,
CDN, analytics, storage or downloaded assets. Uses browser-installed Arial and
system Chinese fallback fonts; no font binaries are redistributed.

Open page.html locally, optionally #seed=123. Defaults to real performance.now().
Only explicit #test=1 enables quizTest and an injected monotonic clock. Production
plugins must never access that test object, DOM, or hidden round identifiers.

Layout: 960 x 640 logical board, uniformly contain-scaled and centered in the
viewport. Buttons A-D at x=60/280/500/720, y=300, size180x130. Confirm at610,510,
260x90. These labels are oracle/ROI planning metadata, never authorized click
coordinates. Scores/rounds are arbitrary-precision integers and never wrap;
very long scores remain scrollable rather than silently truncating their value.
Numbers outside a legible viewport must be rejected by future visual recognition.

Engine bounded event history (256 records) is a test oracle, not an application
event bus. Expiry is checked synchronously on every select/confirm as well as
the timer. A stale handler carries its visible round and cannot act on a new one.

04.2 adds two original 32px geometric button markers (image/neutral.png and
image/selected.png), dedicated to CC0-1.0; no third-party imagery. Runtime resource
preparation makes bilinear 8..128px variants from these originals, never from a
captured screenshot. The matching candidate, not the ROI center, locates clicks.
QuizPlugin is an unaccepted prototype: see LITE-04_DESIGN_DEVIATION.md for recorded
OCR failures. It is deliberately not registered in the executable CLI yet.
