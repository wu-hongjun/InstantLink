# Bridge event-driven GPIO input

## Goal and boundaries

Reduce the lgpio input alert thread's idle CPU cost while preserving button responsiveness,
physical button identities, 50 ms stable debounce, held-press behavior and lock/unlock rules.
The previous live audit measured 3.1 process CPU seconds in 30 seconds at 600 MHz; a native
GPIO thread was the largest observed cost. Its alert loop uses a hard-coded 500 µs ppoll.
There is no supported alert-period configuration; lgpio MIN_DELAY controls transmit timing.

Use a GPIO character-device v2 group request with kernel debounce and asyncio fd readiness.
Keep the legacy gpiozero/lgpio path as a safe fallback. Do not modify installed dependencies
or the LCD backlight in this change. Any lgpio backlight transmit activity remains a separate
cost. Keep source, hardware verification and performance claims distinct.

## Implementation and validation

- Independently verify GPIO v2 ABI, flags, event semantics and chip identity against primary
  documentation and the actual Pi headers. Preserve all eight BCM mappings and queue IDs.
- Own and close request descriptors on every setup/read failure; remove readers before closing.
  Bound batch draining, detect lost/out-of-order records, and avoid ambiguous synthetic presses.
- Run kernel GPIO-mockup tests for edge/debounce/burst/held timing and lock/unlock integration.
  Use only a newly created simulated chip and its debugfs values; never drive physical inputs.
  Remove only test-owned resources. Electrical switch contacts are outside this automation.
- Measure paired actual-runtime dark CPU samples at 600 MHz with matched background activity,
  including per-thread and child CPU and whole-system counters. Exclude tracing overhead from
  timing samples; do not infer energy/battery runtime from CPU counters.
- Run an independent adversarial review, local affected tests, Ruff/strict mypy/full Bridge
  gates and strict docs. Deploy the clean validated source, verify the actual input backend,
  lock/unlock and normal runtime health, then remove temporary observers and test resources.

## Candidate results, 2026-10-12

- Default input owns one GPIO v2 request for all eight lines, using both edges, pull-ups,
  kernel debounce and bounded asyncio readiness reads. Held startup levels are suppressed
  until release. Overflow resynchronizes and discards uncertain buffered presses. Setup,
  read failure and shutdown release owned descriptors before fallback/reopen.
- An actual legacy close/reopen failure exposed a retained native pin callback. Public
  callback detachment before Button.close fixes persistent registration; no private
  dependency patch or installed-package change is needed. Independent review has no
  blocking findings; an already executing legacy callback is an inherited teardown limit.
- Three 30-second actual-runtime samples per condition, dark/600 MHz/Printer offline:
  baseline mean **10.012%**, candidate **1.710%**, forced legacy repeat **10.900%** of one core.
  Child CPU is separate; whole-system counters are recorded. This measures process CPU,
  not energy, battery runtime or performance with the Printer connected.
- Paired kernel mockup input tests passed 21 assertions/28 actions for each backend.
  Candidate stimulus-to-queue p95 **56.38 ms**, legacy **52.47 ms**: about **3.91 ms** extra
  including 50 ms debounce and kernel scheduling. Candidate stable-event-to-queue p95
  **0.583 ms**. Short bounce/35 ms presses ignored; stable75 ms, held, triple and eight-line
  burst accepted. A simulated pull-up resets startup level, so physical held-at-claim is
  covered by unit policy tests rather than claimed from mockup hardware.
- Kernel edges into the production UI queue passed 11 cases with the real LCD/CPU: nonblank
  wake, key/joystick identity reset, triple unlock, held press, rapid75 ms presses, 10-second
  abandonment returning dark/600 MHz, and detached mock callbacks remaining inactive.
  Physical switch contacts were not actuated. Printer offline/film0; no film consumed.
- Bridge **1571** tests, Ruff, strict mypy **66** files and touched format passed; independent
  reviewer separately passed **68** focused tests and descriptor checks. Sanitized evidence:
  `docs/assets/bridge-audit-077/`. Raw journals and temporary tooling remain outside Git.
- One CPU setup sample was rejected during unlock warmup; one UI assertion needed to await
  the asynchronous wake. A recreated root-only mock device needed test-owned permissions.
  Harness corrections are recorded; these are not accepted timings or production failures.

## Primary references

- [GPIO v2 request ABI](https://docs.kernel.org/userspace-api/gpio/gpio-v2-get-line-ioctl.html)
- [GPIO event read semantics](https://docs.kernel.org/userspace-api/gpio/gpio-v2-line-event-read.html)
- [Linux6.12 UAPI layouts](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/uapi/linux/gpio.h)
- [lgpio alert implementation](https://raw.githubusercontent.com/joan2937/lg/master/lgPthAlerts.c)
- [GPIO mockup testing](https://docs.kernel.org/admin-guide/gpio/gpio-mockup.html)

## Installed acceptance

Clean **2ccdfa6** is installed and pushed. Installed source hashes match the independent
review. Native FFI SHA-256 remains
`5622ca8d2cce25f9437ddaad97771a3c4e29fee42e226cfb9444b73fcb9de3b8`.
The same 11 kernel-to-production-UI cases passed after deployment. Three further dark
30-second samples averaged **1.898%** of one core, **81.0% less** than the original
**10.012%** baseline and **82.6% less** than the matched forced-legacy repeat. These are
idle process CPU savings. Debounce, mappings and CPU tier settings are unchanged.

Normal service is restored with kernel GPIO input, no fallback/read failures, both services
active/NRestarts0, dark600MHz, hotspot/USB up, unchanged native hash and no working caches.
FTP220/200 passed through the Pi hotspot address. Localhost/USB probes were rejected by the
existing receive policy; those two warnings are controlled test events, not new faults.
All owned mockup/observer/drop-in/socket/source/scripts are removed; physical switch contacts
and camera Wi-Fi airtime remain outside the automated test boundary.
