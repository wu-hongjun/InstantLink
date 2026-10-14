# LCD rendering evidence

Plan 086 records the source, hardware and independent acceptance for `cac3318`.

- `host-packing.json`: producer host conversion samples (host timing is not Pi timing).
- `independent-source-review.json`: exhaustive RGB and input/UI frame oracle results.
- `source-validation.json`: normal source and independent affected test gates.
- `live-render-benchmark.json`: per-frame Pi spans, CPU clocks and exact framebuffer hashes.
- `gpio-validation.json`: 11 cases per variant through owned kernel mockup edges, production
  input/controller and actual LCD. Queue durations exclude contact latency and include CPU wake.
- `status-reconnect-validation.json`: no-film startup, subsequent fresh polling and locked recovery.
- `independent-hardware-review.json` / `independent-installed-review.json`: fresh reviewer acceptance.
- `cleanup.json` / `final-health.json` / `running-log-review.json`: restored production state and logs.
- `independent-final-review.json`: independent restored-device, log and documentation signoff.

Full raw journals and observer traces are retained privately under `/tmp/instantlink-lcd-*086*`.
No image/print commands, battery lifetime measurement, panel scanout timing or physical button
actuation occurred. Framebuffer byte equivalence is the display quality gate.
