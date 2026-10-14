# LCD text and layout evidence

Plan 087 validates clean source `06bbe86` on Pi Zero 2 W/ST7789 with no film.

- `source-validation.json`, `host-text-benchmark.json`, `baseline-pi-profile.log`: source gates
  and profiling. Host timings are not Pi timings.
- `independent-source-review.json`, `independent-cache-probes.json`: frozen original renderer
  comparisons, clipping/font/cache cases and concurrent rendering acceptance.
- `live-render-benchmark.json`: actual framebuffer spans and exact accepted frame hashes;
  the mixed-clock initial trial is excluded explicitly.
- `cold-warm-drawing.json`: original RGB oracle and glyph-cache-cold/immediate-warm spans
  with fonts already loaded, separate from actual framebuffer timing.
- `pi-pixel-matrix.json`: all modes, both themes/languages and three font sizes, using Pi font
  files; preview immutability and RGB equality against original source.
- `gpio-validation.json`, `status-reconnect-validation.json`: production input/controller/LCD
  through kernel mockup, same-button unlock/timeout/CPU tiers and status-only reconnect.
- `independent-hardware-review.json`, `independent-installed-review.json`,
  `independent-final-review.json`: independent acceptance at each stage.
- `final-health.json`, `cleanup.json`, `running-log-review.json`: restored production state,
  exact source/native provenance, removed fixtures and retained historical faults.

Raw observer traces and full journals are retained privately under `/tmp/instantlink-lcd-text-*087*`.
No image/print commands, film, panel scanout/contact latency or battery-runtime measurement.
Mask pixel storage is capped below 3 MiB; metadata, strings and font overhead are additional.
