# Rust image preparation: opaque RGB contain composition

## Change

`resize_image(..., FitMode::Contain)` now copies resized RGB8 rows onto the same white RGB canvas. The old path called `DynamicImage` pixel access and RGBA compositing for every opaque pixel. RGB8 has no alpha, so the old compositing operation is an exact replacement of the destination RGB channels; copying each row preserves those bytes.

The optimization applies only when the resized buffer is actually `ImageRgb8`. Other variants use the original overlay implementation, preserving alpha blending and 16-bit/float conversion. Lanczos3 resizing, centered floor-divided padding, JPEG encoding and quality search, source EXIF handling, model flips, and chunk padding are unchanged. The loop is bounded by logical image height, and guards an empty row width. No unsafe code, dependencies, ABI changes, or global caches were added.

## Correctness

`crates/instantlink-core/tests/image_contain_performance.rs` retains the literal previous contain implementation as an independent oracle. Five normal tests compare:

- Exact pixels, dimensions, color type, and color-space metadata for all four models, exact target dimensions, odd landscape/portrait dimensions, 1x1, 37x1, 1x37, and empty-axis inputs.
- All nine other DynamicImage variants, including transparent, semitransparent, opaque, 16-bit, and float inputs.
- Oversized backing storage, which must not become image content or padding.
- Complete JPEG bytes and padded chunks for all models at quality 1 and 97.
- Complete JPEG bytes and chunks for an orientation-6 EXIF JPEG for all models, preserving existing source-loading and transport-flip behavior.

Targeted release result: **5 passed, 0 failed, 1 ignored benchmark**, 3.04 seconds. This run used the existing Homebrew static TurboJPEG build workaround:

```bash
TURBOJPEG_SOURCE=explicit \
TURBOJPEG_LIB_DIR=/opt/homebrew/opt/jpeg-turbo/lib \
TURBOJPEG_INCLUDE_DIR=/opt/homebrew/opt/jpeg-turbo/include \
TURBOJPEG_STATIC=1 \
cargo test -p instantlink-core --locked --release --test image_contain_performance -- --test-threads=1
```

`rustfmt --edition 2024` was limited to the two owned Rust files. Root performs the final workspace gates.

## Measurement method

Apple M3 Max, arm64, macOS 27.0.1 (26A434), Rust 1.96.0, repository release profile. Deterministic RGB inputs contain gradients, diagonal detail, and repeated high-frequency patterns; JPEG input is produced at quality 92. The complete preparation workload includes decoding, contain resizing/composition, model flip, quality-97 encoding with the existing size-limit search, and chunk generation.

The ignored benchmark runs both the literal legacy path and the new public path in the same precompiled test executable. It checks exact results before timing, warms both paths, alternates measurement order, and reports the median of nine batches. Resize batches contain 10 operations; complete preparation batches contain five. Each operation includes allocation and drop. Timing uses `black_box`, with no timing assertions in CI.

The precompiled executable was run while holding an exclusive `fcntl.flock` on `/tmp/instantlink-099-benchmark.lock`, shared by the audit agents. Other compilation was observed during measurement, so wall-clock numbers describe this local run and do not establish hardware or power improvements.

## Measured results

The reliable result is **native-size RGB8 contain composition: 4.258 ms to 0.130 ms, a 96.9% reduction (32.8x faster)**. All measured legacy batches took 3.963–5.761 ms, and all optimized batches took 0.125–0.170 ms. This isolates the avoided per-pixel overlay cost when resize itself is a copy.

The larger workloads showed extreme scheduling variance. Their full preparation results are **inconclusive**; no end-to-end preparation, print-time, or power improvement is established. Apparent gains or regressions below must not be interpreted as reliable changes.

| Workload | Legacy median ms | Optimized median ms | Legacy batch range ms | Optimized batch range ms |
| --- | ---: | ---: | ---: | ---: |
| Contain RGB 600x800, Mini | 4.258 | 0.130 | 3.963–5.761 | 0.125–0.170 |
| Full JPEG preparation 600x800, Mini | 67.687 | 67.257 | 54.152–108.919 | 53.405–168.830 |
| Contain RGB 1200x800, Mini Link 3 | 39.125 | 39.021 | 19.351–76.834 | 18.648–61.817 |
| Full JPEG preparation 1200x800, Mini Link 3 | 212.729 | 272.511 | 84.100–507.066 | 135.927–335.451 |
| Contain RGB 4000x3000, Wide | 427.844 | 278.114 | 138.025–546.751 | 136.202–485.083 |
| Full JPEG preparation 4000x3000, Wide | 414.936 | 472.408 | 354.187–1381.410 | 375.306–1301.217 |

The opt-in benchmark completed successfully in 158.31 seconds, including its exact-output checks. Reproduce by building the release test above and running its executable with `--ignored --nocapture --test-threads=1` under the shared exclusive lock. A direct convenience command, when the machine is otherwise idle, is:

```bash
# Use the same TurboJPEG environment variables listed above if needed.
cargo test -p instantlink-core --locked --release --test image_contain_performance -- --ignored --nocapture --test-threads=1
```

## Limits

This removes per-pixel composition work only for Contain + RGB8. Crop, Stretch, alternative pixel formats, BLE transfer, and Printer mechanics receive no claimed speedup. The larger input's decode and resize work and repeated JPEG encodes can dominate total preparation. No Printer, Bridge, camera, SSH, or film was used. Physical printing and power consumption were not measured; byte equality provides the relevant software regression check for this change.
