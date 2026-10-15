# Bridge diagnostics: bounded support-bundle hashing

The completed support ZIP previously passed through `Path.read_bytes()` before
SHA-256 calculation. Hashing therefore temporarily allocated another copy of the
entire compressed archive. The new private `_file_sha256` helper opens that same
completed regular file and calls `hashlib.file_digest`, available throughout the
supported Python 3.11–3.13 range. On the measured Python 3.13 runtime, its reusable
buffer is 256 KiB. The archive has already closed, including its ZIP directory,
before either implementation starts hashing.

This is a **bounded-memory improvement in the hashing phase**. It does not establish
a speed improvement or lower peak memory for the entire support-bundle operation.
Source reads, redaction, compression, metadata, file naming and HTTP contracts are
unchanged. Source redaction and log-stream materialization were also inspected;
their allocation costs require separate changes and are outside this optimization.

## Measurement

Host: Apple M3 Max, macOS 27.0.1 arm64, Python 3.13.9. Baseline is the exact former
`hashlib.sha256(path.read_bytes()).hexdigest()` expression from merged main
`f5ed2c8037511483299c56c3bc71cdaef3d661cc`; candidate calls the production helper.

The helper builds closed, DEFLATED ZIPs containing deterministic synthetic event
logs of 64 KiB, 4 MiB and 128 MiB. Their repetition and random transfer identifiers
represent log-shaped input, but these sizes are scenarios, not measured production
bundle distributions. Fixture construction is outside the timing lock and excluded
from measurements. Hash equality is checked before measurement.

Three warmups precede seven paired samples, alternating baseline/candidate order.
Each sample repeats the hash 1,544, 547 or 3 times respectively. Wall and process
CPU times are collected together without allocation tracing. Separate passes record
seven single-operation `tracemalloc` peaks per variant. All measurement passes hold
the exclusive `/tmp/instantlink-099-benchmark.lock`; actual measurement interval was
2026-10-15 05:42:22–05:42:48 UTC, after the root's compilation completed.

| Log input | ZIP bytes | Baseline peak traced bytes | Candidate peak traced bytes | Memory result |
| --- | ---: | ---: | ---: | --- |
| 64 KiB | 16,741 | 21,727 | 267,949 | 246,222 bytes more |
| 4 MiB | 1,042,860 | 1,047,846 | 267,977 | 74.4% less |
| 128 MiB | 33,357,123 | 33,362,109 | 267,977 | 99.2% less |

All seven allocation samples were identical within each case and variant. These
are peak traced Python allocations during hashing, not process RSS, file cache,
ZIP construction memory, or total operation memory. The fixed buffer adds about
240 KiB for the smallest ZIP. This small-file tradeoff is accepted to keep hashing
memory bounded when archives are large; the implementation does not add a file-size
threshold, a second read strategy, or private standard-library tuning arguments.

Timing medians and min–max ranges in milliseconds per hash:

| ZIP bytes | Baseline wall | Candidate wall | Baseline process CPU | Candidate process CPU |
| ---: | --- | --- | --- | --- |
| 16,741 | 0.112 (0.055–0.275) | 0.093 (0.051–0.165) | 0.043 (0.040–0.047) | 0.047 (0.043–0.050) |
| 1,042,860 | 2.602 (1.446–3.590) | 2.238 (1.757–2.954) | 0.767 (0.755–0.817) | 0.759 (0.748–0.766) |
| 33,357,123 | 55.177 (41.873–96.324) | 49.988 (29.352–75.220) | 25.278 (24.440–25.567) | 23.493 (22.937–23.921) |

Wall ranges overlap substantially and the small-input CPU result regresses slightly.
No speedup, Pi performance, energy saving or printing-latency claim is made. These
are warm-cache host measurements of hashing alone.

## Reproduction and validation

From the repository root, select a Python environment containing the Bridge's
existing development dependencies:

```bash
python docs/assets/performance-audit-099/05-bridge-diagnostics-benchmark.py > /tmp/05-bridge-diagnostics-results.json
```

The committed helper imports production code from this checkout. Full sample
arrays, environment and timing timestamps are in
[05-bridge-diagnostics-results.json](05-bridge-diagnostics-results.json).

Commands run from `bridge/` with
`/Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python`:

```bash
python -m pytest -q tests/test_manager_diagnostics.py
python -m ruff check src/instantlink_bridge/manager/diagnostics.py tests/test_manager_diagnostics.py ../docs/assets/performance-audit-099/05-bridge-diagnostics-benchmark.py
python -m ruff format --check src/instantlink_bridge/manager/diagnostics.py tests/test_manager_diagnostics.py ../docs/assets/performance-audit-099/05-bridge-diagnostics-benchmark.py
python -m mypy src/instantlink_bridge/manager/diagnostics.py
git diff --check
```

Results: **19 tests passed**, Ruff lint and format passed, focused strict mypy
passed, and diff whitespace check passed. Root owns broader integration gates.

## Adversarial review

- Empty input, one byte, 256 KiB minus/at/plus one byte and a multi-buffer file
  produce the same digest as hashing the entire byte sequence.
- A reader rejecting unbounded reads verifies reusable reads never exceed 256 KiB
  on the supported runtime and the descriptor closes after success.
- An injected `readinto` failure propagates its `OSError` and closes the descriptor.
  Failure handling is not changed into a successful response or partial digest.
- An integration test prohibits `Path.read_bytes()` during bundle creation, checks
  the returned hash against all bytes of the completed ZIP, verifies ZIP integrity,
  and checks the larger payload. Existing tests retain redaction, manifest, size
  metadata and signed HTTP coverage.
- Hashing remains after ZIP closure and the existing size stat. The pre-existing
  behavior if another actor concurrently replaces an archive is not modified.
- Python 3.11 and 3.12 were not separately executed; `file_digest` is part of their
  supported standard library. No dependency or public API changed.
- No Bridge, Printer or camera hardware was accessed, and no deployment occurred.
