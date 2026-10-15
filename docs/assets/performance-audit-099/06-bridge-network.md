# Bridge network snapshot parsing

The Linux snapshot parser already receives IPv4 addresses as four packed bytes
and a validated integer prefix. It previously constructed an `IPv4Address`,
formatted that address and prefix as text, then reparsed the text through
`IPv4Interface`. It now passes `(packed_address, prefix)` directly to the public
`IPv4Interface` constructor. This is the only production change in this audit.

## Measurement

Measured with Python 3.13.9 on arm64 macOS 27.0.1. The
[benchmark](06-bridge-network-benchmark.py) loads the production parser from this
checkout and reconstructs the baseline by restoring only the old constructor
expression. Both variants run the actual `_messages`, `_parse_links`, and
`_parse_addresses` functions over prebuilt rtnetlink bytes. The output objects
are compared before timing.

Each fixture contains four link records and three ignored address records
(host scope, an unrequested interface, and IPv6). Accepted records exercise
local/peer precedence, alias labels, unknown cache-info attributes, and /22,
/24, and /32 prefixes. The smaller fixture has three accepted addresses;
the larger has 64 and represents a stress case rather than typical Bridge
configuration. Fixture construction, imports, and baseline reconstruction are
outside the timed region. Kernel I/O, `_dump` control-message processing, and
health calculation are not timed.

The benchmark takes the shared exclusive
`fcntl.flock('/tmp/instantlink-099-benchmark.lock', LOCK_EX)`. Each workload has
200 untimed iterations per variant followed by nine sample pairs, alternating
which variant runs first. Each sample averages 2,000 parses for the smaller
fixture or 500 for the larger. Both process CPU time and elapsed time are
recorded. All numbers below are microseconds per parse.

| Accepted addresses | Baseline CPU median (range) | Packed CPU median (range) | CPU reduction | Baseline elapsed median (range) | Packed elapsed median (range) |
| --- | --- | --- | --- | --- | --- |
| 3 | 41.13 (39.76–44.64) | 28.48 (27.68–31.15) | 30.7% | 60.27 (46.05–79.73) | 36.51 (29.64–200.54) |
| 64 | 635.29 (623.57–653.96) | 369.41 (349.38–379.48) | 41.9% | 762.69 (696.59–866.42) | 436.02 (376.70–730.41) |

The [raw results](06-bridge-network-results.json) retain every sample. An
[initial elapsed-only run](06-bridge-network-initial-results.json), using nine
pairs of 4,000/1,000 iterations, showed 34.3%/42.9% median reductions but wide
scheduling variation. One bounded repeat added CPU-time measurement to clarify
the result; no samples were removed. The repeat's elapsed medians improved
39.4%/42.8%, but the small-fixture packed maximum exceeded the baseline maximum.
The CPU observations provide clearer evidence for reduced parsing work on
this host. The absolute typical-fixture saving is about 12.6 CPU microseconds.

Reproduce from the repository root:

```bash
bridge/.venv/bin/python docs/assets/performance-audit-099/06-bridge-network-benchmark.py
```

The recorded run used the existing environment at
`/Users/hongjunwu/Git/InstantLink/bridge/.venv/bin/python` while loading the
managed worktree's production source. This establishes a local parser CPU
benefit. It does not establish a reduction in end-to-end network probe latency,
upload time, reconnect time, power consumption, or battery drain. The normal
snapshot is small, so the absolute benefit is correspondingly small.

## Correctness and self-review

- The constructor still produces ordinary `IPv4Interface` objects, preserving
  host bits, subnet, netmask, ordering, and duplicates. Regression coverage
  checks all 33 valid prefixes against the text constructor for six addresses,
  including zero, all-ones, loopback, link-local, and ordinary addresses.
- Four-byte length and prefix bounds are still checked before construction.
  New tests reject prefixes 33 and 255, missing local/peer addresses, and local
  payloads with zero, three, or five bytes. A malformed `IFA_LOCAL` never falls
  back to a valid peer; a missing `IFA_LOCAL` still uses `IFA_ADDRESS`.
- IPv6 and host-scope selection, alias labels, link index reuse detection,
  administrative state, unknown attributes, and label checks are unchanged.
  Existing tests cover label ambiguity, down interfaces, interrupted dumps,
  invalid message/attribute bounds, untrusted senders, and truncation.
- Each probe still uses a new socket, the shared 250 ms dump deadline, and
  the existing single bounded `ip` fallback. No state cache was introduced.
  A new regression observes changed then removed addresses on consecutive
  probes. Existing fallback tests prove a single fresh command with the
  original 1.5 second timeout after native failure.
- Reviewed `health.py`, `addresses.py`, and the live network description in
  `docs/reference/bridge-management.md`. Receive readiness, subnet conflict
  rules, carrier checks, refresh cadence, and automatic recovery behavior are
  unchanged, so no public contract/reference change is needed.

No correctness issue remained in this self-review. The constructor's packed
tuple form is a public standard-library API; no object internals or mutable
shared state are used. Validation was on Python 3.13.9. No Raspberry Pi,
Printer, camera, or iPhone hardware was contacted, and no hardware smoke test
was performed; hardware behavior and power savings remain unmeasured.

## Validation

Commands run from the managed `bridge/` directory with the Python environment
above:

```bash
python -m pytest -q tests/test_net_linux_snapshot.py tests/test_net_addresses.py tests/test_net_health.py
python -m ruff check src/instantlink_bridge/net/linux_snapshot.py tests/test_net_linux_snapshot.py ../docs/assets/performance-audit-099/06-bridge-network-benchmark.py
python -m ruff format --check src/instantlink_bridge/net/linux_snapshot.py tests/test_net_linux_snapshot.py ../docs/assets/performance-audit-099/06-bridge-network-benchmark.py
python -m mypy src/instantlink_bridge/net/linux_snapshot.py
```

Results: **293 tests passed**, Ruff checks passed, formatting passed, and mypy
reported no issues. `git diff --check` on the production and test files passed.
The benchmark passed its baseline/result equivalence checks on both workloads.
