# 07 — Bridge hue postprocessing

The accepted optimization processes RGB hue adjustments in **512 × 256 pixel tiles**, preserving exact pixel arithmetic while bounding NumPy intermediates. At 8 MP, the final local comparison reduced traced peak allocation from **762.8 to 10.8 MiB** and process CPU median from **403.9 to 365.0 ms**. Fresh child process peak RSS fell from **1109.8 to 223.2 MiB** on the macOS test host. Source and result images remain full resolution; these measurements do not establish total Bridge memory use or Raspberry Pi latency.

## Audit and accepted change

Owned production file: `bridge/src/instantlink_bridge/imaging/postprocess.py`.

Hue is pointwise: it has no neighboring-pixel or frame-geometry dependence. `_apply_hue` crops one bounded RGB tile, runs the exact NumPy transform, and pastes the RGB result at its original coordinates. Bounding both axes also limits the intermediates for very wide panoramas. Small images use the helper directly, avoiding crop/paste overhead. Non-RGB inputs and empty dimensions retain the preexisting helper boundary; this change introduces no mode conversion or new support for previously unsupported channel layouts.

Within each tile, the selected initial optimization also reduces full-image selections. Each output channel has only four distinct values across six hue sectors:

| Channel | Sector 0 | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- | --- |
| R | v | q | p | p | t | v |
| G | t | v | v | q | p | p |
| B | p | p | t | v | v | q |

Grouping repeated choices reduces five nested `np.where` operations to three per channel. Clipping, multiplication by 255, and addition of 0.5 reuse the private output buffer, retaining float32 precision and operation order before the uint8 cast. The RGB-to-HSV math, adjustment order, JPEG quality, input ownership, lazy NumPy import, dependency versions, and APIs remain unchanged. Output metadata remains empty, as with the original `Image.fromarray` return.

## Alternatives and refinement history

- The first accepted candidate grouped hue sectors and reused quantization buffers without tiling. Its initial 8 MP traced peak was still 656 MiB, too large to treat as a satisfactory working set for a 512 MiB Bridge. The coordinating agent requested the bounded refinement before integration. Its original measurements remain in [07-bridge-postprocess-initial-results.json](07-bridge-postprocess-initial-results.json).
- A `np.copyto` loop with sector masks was slower in initial exploration (approximately 292 ms versus 203 ms for the old 1.92 MP implementation).
- Reusing `np.floor(h6)` without freeing its result retained another full image plane. Floor calculations remain unchanged.
- Algebraically simplifying vignette radius math could change rounding, particularly because `np.sqrt(2.0)` affects promotion. Vignette remains unchanged.
- Fonts already have a bounded LRU cache. No additional cache was added.

The six-sample tile-size exploration used the same 8 MP pixels, +17 degrees, and reversed variant order on alternate samples. Exact pixels matched the untiled candidate for every tile size. Raw samples are in [07-bridge-postprocess-tile-exploration.json](07-bridge-postprocess-tile-exploration.json).

| Variant | CPU median (ms) | Traced peak (MiB) |
| --- | --- | --- |
| Untiled first candidate | 349.5 | 656.0 |
| 256 × 256 | 332.5 | 5.4 |
| **512 × 256, selected** | **327.0** | **10.8** |
| 512 × 512 | 340.8 | 21.5 |
| 1024 × 256 | 336.7 | 21.5 |

The first complete three-way run is retained in [07-bridge-postprocess-tiled-first-results.json](07-bridge-postprocess-tiled-first-results.json). It showed an intermediate-size CPU slowdown versus the untiled candidate, so the final run used twelve samples with rotated and reversed orders to balance each of three variants across all sample positions. Both runs are retained rather than discarding the less favorable sample. The final run resolved that intermediate-size concern; small differences versus the untiled candidate remain visible below.

## Reproduction and final results

From the repository root using the Bridge development Python environment:

```bash
PYTHONPATH=bridge/src python docs/assets/performance-audit-099/07-bridge-postprocess-benchmark.py
PYTHONPATH=bridge/src python docs/assets/performance-audit-099/07-bridge-postprocess-benchmark.py --tile-sweep
```

The runner loads the frozen reference from `bridge/tests/test_postprocess_hue_equivalence.py`; its function AST was checked against `_apply_hue` at base commit `f5ed2c8037511483299c56c3bc71cdaef3d661cc` and matches after renaming. It creates seeded RGB inputs, checks exact output, warms each variant twice, then runs twelve timed samples in rotating/reversing order. The sweep option now uses the same final twelve-sample method; the retained initial exploration used six. Imports and fixture generation are outside timing. An exclusive `flock` on `/tmp/instantlink-099-benchmark.lock` serializes participating audit jobs. Fresh subprocesses separately measure each variant's 8 MP RSS without another variant's previous allocation peak.

Environment: Apple M3 Max, 64 GB, macOS 27.0.1 (26A434), arm64, Python 3.13.9, NumPy 2.4.6, Pillow 11.3.0. The run used `/Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python` with the managed worktree's `bridge/src` on `PYTHONPATH`. Hue was +17 degrees for timing. Full samples and RSS values are in [07-bridge-postprocess-results.json](07-bridge-postprocess-results.json).

| RGB image | Original CPU median (ms) | Untiled candidate (ms) | Accepted tiled (ms) | CPU reduction vs original | Traced peak original → tiled (MiB) |
| --- | --- | --- | --- | --- | --- |
| 88 × 88 | 0.260 | 0.240 | 0.245 | 5.8% | 0.741 → 0.639 |
| 600 × 800 | 23.154 | 20.321 | 20.991 | 9.3% | 45.779 → 10.755 |
| 1600 × 1200 | 98.880 | 90.926 | 85.970 | 13.1% | 183.108 → 10.756 |
| 3464 × 2309 | 403.871 | 358.441 | 364.988 | 9.6% | 762.787 → 10.755 |

Compared with the initial untiled candidate, the accepted version uses 3.3% more measured CPU at 0.48 MP and 1.8% more at 8 MP, while using 5.5% less at 1.92 MP. This small measured tradeoff buys a bounded working set and approximately **752 MiB less traced peak allocation** than the original at 8 MP. The original, untiled, and tiled fresh-child RSS peaks were **1109.8, 878.7, and 223.2 MiB**, respectively; setup peaks were approximately 107–109 MiB.

Wall time still contains host scheduling outliers despite the lock. At 8 MP the original median was 406.1 ms (range 393.9–1348.9), untiled 359.8 ms (352.3–455.3), and tiled 368.9 ms (349.7–1160.8). CPU and allocation measurements support the conclusion; these wall medians are not an estimate of idle Bridge latency. `tracemalloc` excludes prebuilt input fixtures and native Pillow allocations; RSS includes imports, input, native result storage, and allocator retention. Neither proves that the entire Bridge application will fit in a particular RAM budget.

## Correctness and validation

The frozen independent pixel oracle compares every integer degree from −180 through +180 over seeded random pixels, every grayscale level, and tied channel extrema. Additional tests cover:

- Both tile boundaries, partial final tiles, odd portrait/landscape dimensions, and very wide/tall thin images.
- 1-pixel and empty axes, rotations outside ±360, and input immutability.
- Combined hue/saturation/exposure/sharpness/vignette/datestamp/watermark profiles spanning multiple tiles, including identical quality-95 JPEG bytes.
- RGB input decoded from JPEG, PNG, BMP, and TIFF, and unchanged metadata behavior.
- The existing non-RGB helper boundary and LA exception. Legacy grayscale/palette and RGBA/CMYK outputs contain unwritten columns/channels, so those tests assert unchanged fallback routing rather than comparing undefined bytes or expanding format support.

From `bridge/`, with the development Python environment and `PYTHONPATH=src`:

```bash
python -m pytest -q tests/test_postprocess_hue_equivalence.py tests/test_postprocess.py tests/test_imaging_import_boundaries.py tests/test_image_pipeline.py
python -m mypy src/instantlink_bridge/imaging/postprocess.py
```

Results after tiling: **533 tests passed in 4.13 seconds**, strict mypy passed. From the repository root, Ruff lint and formatting both pass with the repository's Bridge configuration:

```bash
python -m ruff check --config bridge/pyproject.toml bridge/src/instantlink_bridge/imaging/postprocess.py bridge/tests/test_postprocess_hue_equivalence.py docs/assets/performance-audit-099/07-bridge-postprocess-benchmark.py
python -m ruff format --check --config bridge/pyproject.toml bridge/src/instantlink_bridge/imaging/postprocess.py bridge/tests/test_postprocess_hue_equivalence.py docs/assets/performance-audit-099/07-bridge-postprocess-benchmark.py
```

`git diff --check` passed for the production change. Self-review confirmed exact sector choices, quantization order, complete crop/paste coverage, bounded dimensions, and no source mutation. The coordinating agent independently reviewed the initial sector/quantization mapping and requested the memory refinement.

No real Bridge, Printer, camera, or physical printing was exercised. This measures hue on a macOS host; Raspberry Pi latency, total application memory, power savings, and end-to-end printing improvements remain unmeasured. Identity and profiles without hue do not enter this optimized path.
