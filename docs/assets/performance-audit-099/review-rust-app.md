# Independent review — Rust image/protocol and App Curves + Levels

Reviewer: audit agent 09, separate from implementers 01, 02 and 08. Reviewed the
working diff against `f5ed2c8037511483299c56c3bc71cdaef3d661cc`, including new
tests, reference implementations, benchmark helpers and harness registration.
The reviewer's own firmware change 09 is excluded.

**Result: no actionable correctness or safety regression found.** No production
or test changes were made during this review.

## Rust image containment

Reviewed `crates/instantlink-core/src/image.rs`, lines 48–86, and
`tests/image_contain_performance.rs`. Checked the pinned image 0.25.9 source
locally: resize fits the requested bounds; DynamicImage RGB8 pixels become
opaque RGBA8; overlay's fully opaque blend replaces the destination pixel
without arithmetic. Thus direct RGB byte copying reproduces the old opaque
composition, while other formats still take the original conversion/blend path.

All model dimensions are positive and bounded (maximum width 1260, height 840),
so row-byte arithmetic is bounded. Center offsets retain integer-floor behavior.
The source loop limits itself to logical height even when ImageBuffer contains
excess backing storage; destination rows have the full target stride. The
zero-row-width guard avoids zero-size chunking. White fill and output color
metadata still come from the same newly created RGB canvas. Crop, Stretch,
JPEG quality search, EXIF loading, vertical flip and chunking remain unchanged.

The independent legacy oracle retains the former resize/fill/overlay operation.
Tests compare full bytes and metadata, cover every model and padding orientation,
empty/thin dimensions, extra storage, alternate pixel/alpha formats, and complete
JPEG/chunk output including model flip and EXIF input.

## Rust packet extraction

Reviewed `crates/instantlink-core/src/protocol.rs`, especially lines 236–268,
and the new benchmark example. Before the changed extraction, the assembler
enforces exactly the parser's header, minimum length, available length and
checksum requirements. `expected_total` is at least 7 and at most 65535, making
opcode access and the empty-or-larger payload slice valid. The checksum sum over
at most 65534 bytes is below the u32 bound.

Payload ownership is established before draining. Dropping the unused Drain
removes exactly the declared bytes and retains the remaining stream, matching
the previous consumed Drain. Invalid-header, invalid-length and bad-checksum
branches are unchanged. No async point, cancellation check, serialization or
fragmentation behavior was moved. Tests compare against the unchanged public
parser and exercise fragmentation, concatenated packets, retained partial tails,
maximum lengths and precise failure/resynchronization behavior. The allocator
instrumentation is confined to the standalone benchmark example.

## App Curves + Levels

Reviewed the complete pipeline diff, all three new test/support files, and
`scripts/test-macos.sh`/`TestMain.swift`. Preparation hoists only expressions of
immutable channel parameters. Subtraction/division, clamp order, gamma direction,
sample-dependent multiplication order and Float conversion remain the same.
The interleaved buffer keeps the original 256 × RGB ordering. Data copies the
buffer before its local storage expires. Prepared values and spline arrays are
local to each call, with no shared cache or mutable state.

Compared the frozen reference mechanically against the baseline after undoing
its type renames: the only differences are extracting LUT construction into
`curvesData`, returning nil instead of the original image at inactive guards,
and moving the unchanged filter setup into `apply`. Its transfer arithmetic
and entire spline implementation match the baseline. Independently inspected
the extraction for preservation of identity return, filter settings/fallback,
color space and output extent. This avoids relying only on two implementations
sharing the same extraction.

The 305 fixtures include non-finite Levels parameters, missing channels, muted
sections and irregular curve points. Exact LUT bytes and finite Double bit
patterns provide direct arithmetic checks beyond rendered-pixel comparisons;
rendered RGB/alpha and extent comparisons plus concurrent construction cover
the surrounding paths. All five tests are registered and the production source
is included in the native harness.

## Review limits

This was source and evidence review; no additional compilation, benchmark or
hardware operation was performed. The coordinator reported 349 Rust tests and
165 App tests green; the implementers' detailed evidence records their commands
and limits. No physical Printer, BLE session, Bridge or macOS 15 host was tested.
The local performance evidence is bounded to the measured CPU/composition paths;
the image report's noisy complete-preparation results do not establish a whole
printing speedup, and the protocol allocator counter adds measurement overhead.
