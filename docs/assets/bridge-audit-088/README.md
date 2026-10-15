# RGB565 packing evidence

Plan 088 validates `398dde5` on Pi Zero 2 W/ST7789 without film.

- `packing-options-pi.json` / `packing-options-host.json`: exact strategy comparisons;
  Pi measurements select uint16 output/scratch. Host timings are not Pi timings.
- `numpy-import-cost.json`: fresh subprocess import and peak RSS with pagecache already warm;
  module import dominates retained-memory tradeoff, separate from local per-frame buffers.
- `source-validation.json` / `independent-source-review.json`: gates, exhaustive scalar oracle,
  fallback/concurrency/memory and owned-loader lifecycle checks. Arithmetic exhaustive run
  preceded the final scheduling-only delta; report records both hashes.
- `live-render-benchmark.json` / `first-paint-validation.json`: settled actual framebuffer
  spans/hash equality and explicit paint-before-loader-start order in warm service restarts.
- `gpio-validation.json`: production queue/controller/actual LCD via kernel mockup edges;
  physical contacts and scanout not measured.
- `status-reconnect-validation.json`: fresh status and locked automatic recovery, no images.
- `independent-hardware-review.json`, `independent-installed-review.json`,
  `independent-final-review.json`: independent staged acceptance.
- `cleanup.json` / `final-health.json` / `running-log-review.json`: normal state, exact provenance,
  fixture removal and retained historical faults. Raw journals are private.

Preliminary/unsettled measurements and a fixture call before Booting completed were excluded
from accepted results and retained privately under `/tmp/instantlink-rgb565-*088*`.
No image/print commands, film, battery-runtime or contact-to-photon measurement.
