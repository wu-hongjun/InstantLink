# Bridge outbox index serialization

The Bridge rewrites its JSON outbox index after each successful add or ACK, and
when repairing missing spool entries during startup. Each rewrite previously
called `dataclasses.asdict` for every queued item. `OutboxItem` is frozen and
contains six immutable scalar fields, so recursive dataclass conversion is
unnecessary. The writer now projects those six fields directly into the same
ordered JSON object. This is the only production optimization in this audit.

## Measurement

Measured on arm64 macOS 27.0.1 with Python 3.13.9. The checked-in benchmark
compares the original writer implementation against the current production
writer. Both perform `json.dumps(indent=2)`, UTF-8 file writing, and `os.replace`
on a temporary local filesystem directory. There is no `fsync` in either
implementation. Fixture construction and imports happen before acquiring the
shared exclusive `fcntl.flock` at `/tmp/instantlink-099-benchmark.lock`.

Each queue size uses three untimed warmups and 15 timed samples per variant,
alternating which variant runs first. A sample averages 100 publications at
depth 1, 30 at depth 64, or 5 at depth 1024. All serialized bytes are compared
before timing. See the [raw samples](04-bridge-outbox-results.json) and
[reproduction script](04-bridge-outbox-benchmark.py).

| Queue depth | Index bytes | Baseline median (range), ms | Candidate median (range), ms | Median reduction |
| --- | --- | --- | --- | --- |
| 1 | 311 | 0.2586 (0.2295–0.4757) | 0.2521 (0.2282–0.2932) | 2.5%, within noise |
| 64 | 17,699 | 0.4252 (0.3876–0.5477) | 0.3521 (0.3219–0.3782) | 17.2% |
| 1024 | 282,659 | 3.1691 (2.8953–6.0165) | 1.8169 (1.6795–3.2377) | 42.7% |

Reproduce from the repository root using the Bridge development environment:

```bash
bridge/.venv/bin/python docs/assets/performance-audit-099/04-bridge-outbox-benchmark.py
```

The run recorded here used the existing environment at
`/Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python`, with the benchmark
loading source from the managed worktree. The benchmark uses prebuilt metadata
with representative filenames, timestamps, hashes, and camera addresses.
It measures index publication only; it excludes photo copy/checksum work,
eviction, dictionary snapshot creation, and lock contention. Depth 1024 is a
stress case, not a claim about typical queue size or the default budget. These
results establish a host-local serialization benefit, not a measured Raspberry
Pi upload or battery improvement. Physical Bridge hardware was not used.

## Compatibility and adversarial review

- Exact JSON keys, field order, values, indenting, index version, and queue
  ordering are unchanged. A regression compares persisted bytes with
  `json.dumps` over `dataclasses.asdict` after add and ACK, including the empty
  queue, and verifies restart recovery. A future dataclass field addition will
  fail this check if the writer is not updated.
- Regression fixtures cover zero-byte originals, empty remote address, Unicode
  and JSON-escaped filenames, IPv6, epoch zero, fractional timestamps, and a
  large timestamp. All remain ordinary JSON scalar values.
- Existing mutation, reader, and arrival locks are untouched. The index is
  still published before the in-memory snapshot changes or evicted/ACKed
  originals are deleted. Existing tests exercise concurrent readers/ACK,
  failed copy/hash, failed writes/replaces, source independence, eviction,
  reload repair, and migration of legacy hard links.
- No index cache was added: every write projects the proposed current snapshot.
  No source ownership, persistence durability, or failure-cleanup changes were
  made. Copying scalar references is safe because the supported item fields
  are immutable strings, integers, and floats.
- Reviewed `docs/reference/sync-api.md`, iOS `Models/SyncModels.swift`, and
  `Services/SyncClient.swift`. The sync payload/schema and iOS interpretation
  are unchanged; no paired contract edit is necessary.

## Validation

- Focused outbox tests: **24 passed**.
- Ruff check and formatting on the production file, new test, and benchmark:
  passed.
- Strict mypy on `src/instantlink_bridge/sync/outbox.py`: passed.
- Broader sync tests (`python -m pytest -q tests/test_sync*.py`): **64 passed**.

Residual maintenance cost: the persisted field projection is now explicit and
must be updated if `OutboxItem` gains fields. The schema-equivalence regression
guards against silently omitting such fields. No unresolved correctness issue
was found in the self-review.
