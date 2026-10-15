# 09 — App bundled firmware hashing

## Change and measured outcome

`BridgeFirmwareBundleService.sha256Hex` now hashes each artifact through a single
`FileHandle` in reads of at most 1 MiB. Each iteration has an autorelease pool so
Foundation read buffers are released before the next read. The previous implementation
loaded the entire artifact into `Data` before hashing it. File handles close through
`defer`, including read failures; failures continue to return `nil`.

Peak resident memory for a 256 MiB synthetic archive fell from **262.47 MiB to
8.58 MiB** in isolated validation processes, a **96.7% reduction**. Across 16,
64 and 256 MiB archives, the streamed process stayed below 10 MiB. This bounds
artifact read buffers; it is not a bound on the entire running App's memory.

| Archive size | Original peak RSS MiB, median (range) | Streamed peak RSS MiB, median (range) | Original elapsed ms, median (range) | Streamed elapsed ms, median (range) |
| --- | --- | --- | --- | --- |
| 16 MiB | 22.55 (22.50–22.56) | 8.64 (7.55–9.61) | 14.95 (13.58–16.84) | 13.23 (12.32–17.52) |
| 64 MiB | 70.52 (70.47–70.53) | 9.61 (9.58–9.64) | 57.30 (48.91–59.02) | 50.64 (45.68–60.59) |
| 256 MiB | 262.47 (262.47–262.52) | 8.58 (8.55–9.59) | 178.21 (169.50–188.50) | 146.40 (137.34–159.51) |

Memory is the primary result. Warm-cache median time improved by 11.5%, 11.6%
and 17.8%, respectively. The smaller cases' timing ranges overlap, so they do
not establish a reliable latency gain. These measurements exclude archive
extraction, upload, Bridge verification/installation and App startup.

## Reproduction and evidence

From the repository root on an Apple Silicon Mac:

```bash
python3 docs/assets/performance-audit-099/09-app-firmware-benchmark.py > /tmp/instantlink-firmware-results.json
bash scripts/test-macos.sh
```

The [benchmark](09-app-firmware-benchmark.py) compiles the production service
and a baseline restoring only the original final hash method, using
`swiftc -O -target arm64-apple-macosx15.0`. The reconstructed baseline's SHA-256
is `623ffd2452f333639bed980e087a3ce0940adb4b0bdae69e5db6f3403c98c387`, matching
the complete original production file at merged main
`f5ed2c8037511483299c56c3bc71cdaef3d661cc`. Compilation, fixture preparation and
measurements hold the exclusive `/tmp/instantlink-099-benchmark.lock`; only
the call to `package(in:)` is included in the reported elapsed duration.

Each sample launches a fresh child process. Darwin `/usr/bin/time -l` records
that child's maximum resident set size in bytes, including runtime overhead.
There is one discarded warmup per variant/size, then five paired samples with
alternating original/streamed order. All measured samples and digest values
are retained in the [results](09-app-firmware-results.json). The benchmark
checks that both implementations accept the package and return all three
SHA-256 values computed independently by Python's `hashlib`.

Fixtures are deterministic raw bytes under the archive filename, accompanied
by valid metadata, hash sidecars and placeholder signature files. This service
hashes archive bytes and checks signature-file existence; it does not decompress
the archive or authenticate signatures. The benchmark exercises that exact
existing service boundary. Fixture creation and warmups populate the filesystem
cache, so these are warm-cache measurements rather than cold-disk performance.

Environment: Apple M3 Max, arm64 macOS 27.0.1 (26A434), Apple Swift 6.4
(`swiftlang-6.4.0.34.1`), Python 3.14.6. The shared lock serializes collaborating
audit workloads; ordinary workstation background processes remain possible.

## Correctness and adversarial self-review

All production code preceding the private hash helper matches the original
file byte-for-byte. Schema/kind validation, safe artifact names, signature
presence, all three digest comparisons, package fields and validation order
remain intact. Every invocation opens and hashes the artifacts again; there
is no cache or metadata-only freshness shortcut.

The single open handle retains ordinary open-file behavior across atomic path
replacement. Neither implementation guarantees an atomic snapshot against
concurrent writes to the same inode, and returned URLs retain the existing
possibility of subsequent replacement. Read errors fail closed rather than
returning a digest of a successfully read prefix. Empty input finalizes the
standard empty SHA-256 digest. Small positive short reads continue until EOF.

Four new harness tests cover:

- Empty, 1-byte, SHA-256 block boundaries (63/64/65 bytes), 1 MiB boundaries
  (minus one/exact/plus one), and a multi-chunk archive with a partial final
  chunk, comparing against one-shot CryptoKit digests.
- Independent tampering of the archive, manifest and checksum after successful
  validation, with same-size atomic replacement and preserved modification
  time; restoration is accepted on the next call.
- Removal of each artifact and both signature files from otherwise valid
  packages; directories in place of each hashed artifact; mode-000 archive
  rejection where the executing user lacks read permission. The permission
  branch is intentionally skipped for privileged users able to read it.
- Empty, dot, dot-dot, absolute, slash and backslash artifact names for every
  name field, plus unsupported schema/kind and successful restoration.

`bash scripts/test-macos.sh` passed **165 tests, 0 failed**, including these
four tests (the harness was run by audit agent 08 after registering them).
Only the baseline `BridgePairingView` missing-Combine-import warnings remained.
The benchmark passed all 36 validation/digest checks, including six warmups.
Scoped `git diff --check`, benchmark Python syntax validation, Ruff lint and
Ruff formatting checks passed.

The local filesystem service was exercised on the Mac above, with the macOS
15.0 deployment target. No App installation, physical firmware update, Bridge,
Printer, camera or iPhone test was performed. No public API, UI, localization,
dependency or version change is involved.
