# Bridge RGB565 packing

## Goal and acceptance

Reduce changed-frame framebuffer packing CPU while preserving exact little-endian RGB565
quantization, pixel order and input conversion. Synchronous frames, pixels-before-backlight,
button responsiveness, same-button triple unlock and 10s timeout/600MHz idle remain intact.
No image/print commands or film during validation.

Subagents implement/profile, audit runtime/dependency/lifecycle, and independently review
all RGB colours, Pillow modes/dimensions/concurrency/memory/fallback. Compare Pi baseline,
candidate and installed equivalent actual framebuffer frames at 1000 MHz, and first-frame
backend initialization. Existing NumPy supplied by RAW dependencies is optional; its import
must not block first framebuffer paints or lock blanking. Retain the exact Pillow path while
an owned background preload, scheduled after the first successful paint, prepares the backend and in minimal/no-event-loop runtimes.

Pi alternatives measured separately: Pillow 9.859 ms, byte-output 4.722 ms, word-expression
4.222 ms and word-output 3.160 ms per 240×240 frame, identical bytes (100 rounds). Chosen
word-output uses explicit little-endian uint16 output plus local scratch. Fresh NumPy import
531.424 ms wall/858.105 ms CPU and ~15.4 MiB peak RSS increase with filesystem pagecache
already warm; production first-paint behavior requires a separate gate.

Validate owned preload completion/failure/close/cancellation, kernel GPIO mockup through
production input/controller and real LCD/CPU, fresh status and automatic reconnect. Deploy
clean reviewed source, restore normal entrypoint, remove owned fixtures and review full
running logs including native severity labels and journald priority errors.

Hardware: Pi Zero 2 W Rev1.0 / ST7789 / X306, Debian13.2/Linux6.12.47+rpt-rpi-v8,
Python3.13.5/BlueZ5.82/NumPy2.4.6, Instax Link Square INSTAX-52006924.
Measurements do not claim contact-to-photon latency, physical scanout or battery lifetime.
