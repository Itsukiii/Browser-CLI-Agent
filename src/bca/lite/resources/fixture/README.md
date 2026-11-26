# Owned visual fixture

marker.png is an original 96 x 64 RGB geometric drawing created for BCA-lite,
distributed under this repository's license. No external image/font binaries.
page.html uses installed browser fonts (Arial / Georgia / Courier New in tests).
The marker's default CSS box is (60,50,96,64); optional competitor (250,50,96,64).
Visible revision starts at 123; a click increments it and appends a DOM oracle event.
The DOM controls are test stimulus/oracle only, never available to FixturePlugin.
Scale-specific templates must be derived from this original, never target screenshots.
OCR files are separately supplied and hash-checked by OCRModelSpec; none are bundled.
