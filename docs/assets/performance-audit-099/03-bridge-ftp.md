# Bridge FTP retention comparison cost

## Accepted change

`prune_incoming_dir` keeps canonical filename strings in its metadata records and
protected/newest sets. This avoids parsing and hashing `Path` components for each
retained photo. Deleted filenames still return as `Path` objects. The existing
directory scan, file classification, fresh metadata reads, exception handling,
stable ordering, age/budget/grace rules, and ownership snapshot remain in place.
There is no persistent metadata cache or delayed housekeeping.

This reduces work in the synchronous housekeeping step before completed camera
uploads enter the queue. Upload admission, reservations, source policy, filename
collision handling, partial transfers, overflow cleanup, cancellation and print
dispatch are unchanged. No configuration, contract, dependency or version changes.

## Measurement

Baseline: `f5ed2c8`, loading the original function from Git into the same process
as the candidate. Host: Apple arm64 Mac, macOS 27.0.1, Python 3.13.9. These are
local software measurements, not Raspberry Pi or battery-runtime measurements.

[Benchmark source](03-bridge-ftp-benchmark.py) and
[raw final samples](03-bridge-ftp-results.json) are included. Each workload has
20 measured paired rounds of 30 operations per variant, after two warm-up rounds.
The order alternates AB/BA. All benchmark agents share an exclusive
`/tmp/instantlink-099-benchmark.lock`; unrelated host/build activity cannot be
excluded, so process CPU is reported alongside wall time.

Fixtures contain 8 × 4 MiB, 100 × 2 MiB, or 1,000 × 256 KiB regular files. Files
are sparse because only metadata is inspected; their contents are never read by
this path. Their timestamps are about a day old, totals stay within the existing
512 MiB budget, and three sources are protected. The 8/100-file cases represent
small/accumulated caches; 1,000 files is a scaling case, not a claim about a typical
Bridge. All sweeps assert no deletion. Receive-to-queue runs the actual completed
upload handler, yields to the asyncio handoff, verifies the queued path, and
releases its ownership. Network address discovery uses a fixed empty peer list;
no FTP transfer, decoding or printing is timed.

Median milliseconds per operation:

| Workload | Files | Wall before → after | CPU before → after | CPU reduction |
| --- | ---: | ---: | ---: | ---: |
| Retention sweep | 8 | 0.460 → 0.280 | 0.265 → 0.224 | 15.6% |
| Receive to queue | 8 | 0.885 → 0.871 | 0.728 → 0.719 | 1.2% |
| Retention sweep | 100 | 1.926 → 1.757 | 1.103 → 0.955 | 13.4% |
| Receive to queue | 100 | 2.861 → 2.555 | 1.682 → 1.567 | 6.8% |
| Retention sweep | 1,000 | 8.573 → 7.437 | 8.474 → 7.265 | 14.3% |
| Receive to queue | 1,000 | 9.184 → 7.092 | 9.038 → 7.022 | 22.3% |

The 100-file receive case saves approximately **0.115 ms CPU** and **0.306 ms
wall time** per completion in this run. The small 8-file receive difference is
too small to treat as a dependable end-to-end improvement. Absolute savings are
bounded to this bookkeeping phase. Both accepted variants perform **2N file
metadata queries** per sweep: 16, 200 and 2,000 in these fixtures. The accepted
optimization does not claim fewer syscalls.

Reproduce from the managed repository's `bridge/` directory:

```bash
PYTHONPATH=src /Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python \
  ../docs/assets/performance-audit-099/03-bridge-ftp-benchmark.py
```

## Rejected experiments

1. `scandir` classification plus `Path(entry.path)` reduced explicit stat calls
   but increased CPU cost: at 100 files, sweep 1.113 → 1.232 ms and receive
   1.731 → 1.845 ms. Rejected; wall samples also had substantial host contention.
2. Constructing `resolved_directory / entry.name` also failed: at 100 files,
   sweep CPU 1.075 → 1.189 ms and receive CPU 1.644 → 1.747 ms. Rejected.
3. `scandir` plus string retention records improved 100-file CPU by 47.0% for
   pruning and 33.6% for receive, but changed error-phase semantics. A permission
   failure in the original initial `Path.is_file` scan aborts the sweep; reducing
   two lookups to one shifts that failure to the per-file metadata stage. Also,
   `DirEntry.is_file` raises on a looping symlink where `Path.is_file` returns
   false. A symlink fallback fixed the latter, but the accepted version retains
   the entire original scan to preserve both error phases. No rejected source
   variant is retained in the production tree.

## Validation and limits

**136 affected tests passed**, including 12 new adversarial tests. They cover:

- Canonical protection through a directory symlink, relative `..` spelling and
  case-sensitive filename equality; returned deleted paths remain absolute.
- Symlink target metadata, dangling and looping links, directory links, and a
  target refreshed between file classification and the final metadata read.
- Stable scan order for identical mtimes, vanished files, interrupted scans,
  distinct first-lookup/second-lookup permission failures, unlink failures, and
  fresh size/mtime on later sweeps.
- Exact surviving bytes and mode `0640`.
- Existing real local FTP overlap, disconnect/retry, same-name overflow cleanup,
  pending Sync originals and legacy hard-link detach regressions, plus source
  admission, queue ownership, stop/closed-loop cancellation and Sync gating.

Commands run from `bridge/` with the managed source selected:

```bash
PYTHONPATH=src /Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python -m pytest -q \
  tests/test_incoming_prune.py tests/test_incoming_prune_scan.py \
  tests/test_ftp_receive.py tests/test_ftp_retention.py \
  tests/test_ftp_upload_ownership.py tests/test_ftp_upload_concurrency.py \
  tests/test_ftp_signal.py tests/test_ftp_sync_gate.py
/Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python -m ruff check \
  src/instantlink_bridge/camera/ftp.py tests/test_incoming_prune_scan.py
/Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python -m ruff format --check \
  src/instantlink_bridge/camera/ftp.py tests/test_incoming_prune_scan.py
PYTHONPATH=src /Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python -m mypy \
  src/instantlink_bridge/camera/ftp.py
```

The final affected test run is clean. An initial experimental run emitted one
session-final `BaseEventLoop.__del__` invalid-descriptor warning; it did not recur
in the baseline 124-test check or subsequent candidate runs. No loop or socket
lifecycle implementation was changed.

Independent review found that two new scan-injection tests mocked `os.scandir`,
an implementation detail used by `Path.iterdir` on Python 3.13 but not 3.11/3.12.
They now mock the public `Path.iterdir` boundary directly, preserving ordered
iteration and a failure after the first yielded path across supported versions.
All 12 new tests pass after this correction on Python 3.13. Python 3.11/3.12 were
not separately executed on this host.

Manual camera/Printer/Bridge hardware smoke testing was **not performed**, as
hardware, SSH, deployment and film use were excluded from this audit. Local
pyftpdlib loopback tests ran on the Mac host above. The behavior change is wholly
internal to retention comparisons; hardware transfer latency and battery savings
remain unmeasured.
