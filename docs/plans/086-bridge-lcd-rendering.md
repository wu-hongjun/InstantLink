# Bridge LCD rendering

## Goal

Reduce display work while preserving exact pixels, button responsiveness, lock/unlock,
backlight ordering and the shared physical/virtual LCD state machine. Hardware benchmarks
use display/status operations only; no film.

## Approach and acceptance

Subagents optimize framebuffer RGB565 packing with existing Pillow operations and audit
controller/render lifecycle. Keep synchronous frame ordering, existing deduplication and
pixel restore before backlight activation. Independent review checks byte order, channel
quantization, input modes/sizes, every UI state, image immutability, and failure paths.

Profile actual Pi frames by layout drawing, RGB565 packing, kernel framebuffer writes and
backlight control, including main-thread CPU and event-loop stalls. Compare baseline,
candidate and installed equivalent frames at1000MHz. Validate Linux GPIO mockup input through
production code, same-button triple unlock, mixed-button reset, debounce,10s abandonment,
dark600MHz and awake1000MHz, framebuffer equality against the original scalar oracle, fresh
status and reconnect. Preserve actual panel-scanout/contact/energy measurement limitations.
Run all path-scoped gates, deploy clean source and restore normal service/remove owned fixtures.

Hardware: Pi Zero2W Rev1.0/ST7789/X306, Debian13.2/Linux6.12.47+rpt-rpi-v8/Python3.13.5/BlueZ5.82.
Instax Link Square INSTAX-52006924. No image/print commands or physical film-quality retest.
