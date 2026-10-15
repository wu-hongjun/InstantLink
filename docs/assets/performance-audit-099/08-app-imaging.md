# 08 — App Curves + Levels LUT construction

## Change and scope

The App now prepares each active channel's invariant Levels coefficients once per LUT construction and writes the 256 RGB Float samples directly into the final interleaved buffer. Previously, channel input/output ranges, clamped shadows/highlights, and reciprocal gamma were recomputed for every sample/transfer, and three temporary 256-element arrays were copied into the final buffer.

This removes three temporary Float arrays (3,072 bytes of element storage per active LUT, excluding allocation overhead). The five small prepared channel values are local to each call. There is no cache, shared mutable state, new dependency, change in LUT resolution, interpolation, filter, color space, geometry, or GPU work. The arithmetic retains division rather than replacing it with reciprocal multiplication and retains the original operation order. The existing individual-sample `applyLevels` entry point delegates to the same prepared transfer.

The measured scope is CPU construction of the LUT `Data`, including section guards, spline setup, transfer evaluation, packing and copying into Data. It excludes Core Image filter construction/rendering, editor interaction, JPEG export, transport and printing. Whole-App frame time, GPU performance, and Printer throughput are not claimed.

## Reproduction

From the repository root on an Apple Silicon Mac:

```bash
python3 docs/assets/performance-audit-099/08-app-imaging-benchmark.py
bash scripts/test-macos.sh
bash -n scripts/test-macos.sh
```

The benchmark compiles with `swiftc -O -target arm64-apple-macosx15.0`, then runs under the exclusive audit lock `/tmp/instantlink-099-benchmark.lock`. Compilation also holds the lock to avoid contaminating other audits, but is excluded from all measurements. Each final scenario warms each implementation for 1,000 calls, then runs nine alternating AB/BA pairs of 5,000 calls per implementation. Both wall time and thread CPU time are reported; a checksum consumes the produced Data. The neutral case exercises the existing nil/identity fast path.

The baseline oracle in `macos/Tests/CurvesLevelsReference.swift` freezes the original implementation from commit `f5ed2c8037511483299c56c3bc71cdaef3d661cc`, including its independent spline implementation. Original source SHA-256: `e4bbef17efec6be3b69c238ff216960761dd5d62a4011a77e7f77b02ebcf21bb`. For comparison and byte-level testing, the original LUT-building body was extracted into `curvesData`; the original arithmetic, arrays, packing and guards are preserved. The same extraction is used in production.

Environment: Apple M3 Max, macOS 27.0.1 (26A434), Apple Swift 6.4 (`swiftlang-6.4.0.34.1`). This is a developer workstation with ordinary background applications and Simulator services. The lock serializes collaborating audit workloads, but does not make the workstation idle. The initial 9 × 2,000-call wall-only run had broad timing variation; its full results are retained in `08-app-imaging-initial.csv`. The longer confirmation adds thread CPU time to distinguish scheduling delays; all samples are retained without trimming.

## Measurements

Confirmation results are in `08-app-imaging-results.csv`; checksum: `883476000`. Values below are microseconds per call, median [minimum–maximum] across nine rounds. Percentages compare the medians, without removing outliers.

| Scenario | Baseline wall µs | Optimized wall µs | Wall reduction | Thread CPU median µs, baseline → optimized |
| --- | ---: | ---: | ---: | ---: |
| Levels | 43.981 [41.852–111.340] | 39.764 [32.150–72.311] | 9.6% | 43.871 → 39.497 (10.0% less) |
| Curves | 10.133 [9.961–10.563] | 9.903 [9.785–10.292] | 2.3% | 10.110 → 9.880 (2.3% less) |
| Combined | 56.010 [53.306–62.915] | 44.993 [43.972–73.920] | 19.7% | 55.001 → 44.925 (18.3% less) |
| Neutral | 0.01651 [0.01629–0.01769] | 0.01734 [0.01628–0.01885] | −5.0% | 0.01653 → 0.01736 |

The bounded improvement is reduced active Levels LUT construction CPU work. The neutral fast path differs by less than one nanosecond in the median; the small Curves-only change and neutral variation are not claimed as meaningful improvements. Broad active-case wall ranges and the differing first-run absolute timings preclude a precise workstation-independent speedup claim. Thread CPU time supports the active Levels/combined reduction despite scheduling variation. No whole-render or whole-print speedup is inferred.

## Validation and self-review

`bash scripts/test-macos.sh`: **165 tests passed, 0 failed**, including five new imaging tests and four firmware tests registered for audit 09. The existing `BridgePairingView.swift` missing-Combine-import warnings remain. `bash -n scripts/test-macos.sh` and scoped `git diff --check` passed.

The imaging tests cover:

- **305 fixtures** with byte-for-byte LUT `Data` equality against the frozen original: normal Levels/Curves/combined values, deterministic random curves and channel parameters, muted sections, missing/empty channel dictionaries, out-of-range handles, non-finite channel parameters, empty/single/duplicate curve points.
- Individual Levels outputs compared as exact Double bit patterns (NaN compared as NaN) over a grid and out-of-domain/non-finite inputs.
- Exact RGBA8 rendered pixel equality and unchanged extent for neutral, Levels, Curves and combined pipelines, using a non-square RGB/alpha input at a nonzero origin.
- Identity preservation for disabled/neutral input and 128 concurrent LUT constructions against the reference.

Self-review checked that only value-independent calculations move outside the loop, clamp order and gamma direction are unchanged, the native Float data layout and RGB ordering remain identical, missing channels remain absent, and Core Image failure fallbacks are unchanged. The implementation introduces no per-image state retention or synchronization. The original existing luminance approximation is preserved.

Software rendering was verified on the Mac listed above with a macOS 15.0 deployment target. No physical Printer, print/film smoke test, App installation, or actual macOS 15 host test was performed. No UI layout or user-facing strings changed.
