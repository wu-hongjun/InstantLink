# Bridge LCD text and layout drawing

## Goal and acceptance

Reduce text/layout CPU time while preserving exact display pixels, font fallback, clipping,
language/font/theme changes, current animation clocks, button responsiveness and reliable
same-button triple unlock with 10s abandonment. Physical and virtual LCDs keep one synchronous
renderer and state machine. No image/print commands or film during hardware validation.

Subagents profile and implement bounded text reuse, audit renderer/controller lifecycle,
and independently compare original/candidate output across UI modes, themes, font sizes,
English/Chinese strings, clock phases, transitions and difficult clipping. Include cold/warm
work, bounded cache memory and concurrent virtual/physical rendering in acceptance.

Pi benchmark: actual framebuffer draw/pack/write/backlight spans at 1000 MHz, equivalent
baseline/candidate/installed frames, main-thread CPU and event-loop observations. Kernel
GPIO mockup tests exercise production button queues, actual LCD and 600/1000 MHz tiers.
Physical contacts and panel scanout are not measured. Fresh status and automatic reconnect
remain required when the Printer is available. Deploy clean reviewed source, restore normal
service, remove owned fixtures and review running logs including CRITICAL messages.

Hardware: Pi Zero 2 W Rev 1.0 / ST7789 / X306, Debian 13.2, Linux 6.12.47+rpt-rpi-v8,
Python 3.13.5, BlueZ 5.82. Instax Link Square INSTAX-52006924.
