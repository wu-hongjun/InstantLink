# Independent adversarial review: Bridge optimizations 03–06

Reviewed on 2026-10-15 against baseline `f5ed2c8`, independently of the four implementation agents. Scope: FTP retention comparisons, outbox index projection, support-bundle hashing, packed IPv4 construction, their new/existing regression tests, and evidence reports 03–06. Hue optimization 07 was reviewed separately after its bounded tile implementation settled; see `review-hue.md`.

## Finding — resolved

**Resolved P2 — New retention tests bypassed their injection on supported Python 3.11/3.12.**

`bridge/tests/test_incoming_prune_scan.py`, `test_same_mtime_uses_scan_order_for_budget_and_newest` and `test_scan_failure_does_not_retire_partial_candidate_list`, monkeypatch `os.scandir` to control the enumeration used by `Path.iterdir`. That works on the measured Python 3.13 runtime. However, `Path.iterdir` calls `os.listdir` in both [CPython 3.11.14](https://github.com/python/cpython/blob/v3.11.14/Lib/pathlib.py) and [CPython 3.12.12](https://github.com/python/cpython/blob/v3.12.12/Lib/pathlib.py). Thus the failure injection is never reached on these supported versions: the old fixture is deleted normally and the test fails. The equal-mtime test also stops controlling enumeration and can pass accidentally or fail with filesystem order.

Recommended correction: inject ordered and interrupted `Path` generators at `Path.iterdir`, the production boundary being exercised. Preserve the test's deliberate yield-before-error and assertion that no partial candidate list is pruned. This changes tests only; the final production retention implementation retains its original error phases.

Narrow reproduction on available Python 3.13.9: temporarily substitute `Path.iterdir` with an `os.listdir`-based generator equivalent to the 3.11/3.12 enumeration boundary, then run just these two tests. Result: **1 failed, 1 passed** in 0.05 s. The scan-failure test returned the deleted `original.jpg` instead of `[]`; the ordering test happened to match this filesystem's order. No repository source was changed for reproduction. Python 3.11/3.12 interpreters were unavailable, so this was a boundary simulation backed by the official standard-library implementations, not a full runtime run.

## Resolution verification

The coordinator changed both tests to monkeypatch `Path.iterdir` directly, returning ordered `Path` values or yielding the first `Path` before raising `OSError`. This preserves the intended failure phase without relying on a Python-version-specific directory enumeration implementation. Independent review confirmed that the production code is unchanged by this correction.

Re-ran the same two-test reproduction with the older `os.listdir` enumeration boundary: **2 passed in 0.13 s**. The coordinator also reported all 12 retention tests and Bridge Ruff lint/format passing. Python 3.11/3.12 were still not executed directly; the original reproduction and its limits remain recorded above.

## Production review rationale

- **03 / FTP:** Resolved directory children and resolved protected paths have the same lexical POSIX equality as their string representations. Case remains significant; no additional child resolution changes symlink semantics. Directory scan and `is_file` still finish before the second fresh `stat` phase. Stable sorting, newest selection, ownership/grace checks, age-before-budget eviction, unlink-failure accounting, and returned `Path` values remain unchanged. No skipped metadata checks or cached cross-sweep state were introduced.
- **04 / outbox:** All six current `OutboxItem` fields are immutable scalar values, projected in exactly their dataclass order. `json.dumps` options, item insertion order, version, UTF-8 writing and `os.replace` are unchanged. Existing locks still surround publication, and the committed snapshot and spool deletion still follow successful publication. Source copying, hard-link migration and failure cleanup are untouched. The new persisted-byte comparison against `asdict` guards schema drift and add/ACK/reload behavior.
- **05 / diagnostics:** The ZIP context closes before the unchanged size stat and new hashing call. `file_digest` consumes the same file bytes with SHA-256, and the new `with` closes the descriptor on success or read failure. Exceptions propagate; no partial digest is returned. Redaction, source materialization, ZIP entries and response metadata remain unchanged. Evidence correctly limits the claim to bounded hashing memory and reports the small-file allocation increase; it does not claim lower peak memory for the whole bundle operation.
- **06 / networking:** Packed bytes and the validated integer prefix go through the public `IPv4Interface` constructor. Four-byte address and 0–32 prefix checks still precede construction. Local-over-peer selection, malformed-local rejection, host bits, ordering, labels, scope/family filtering, link identity checks, fresh per-call sockets, shared deadline and bounded fallback are unchanged. New tests cover every valid prefix and malformed address inputs; existing tests cover identity, interruption, closure and fallback.

No production regression was identified in these four final changes. The test-portability finding is resolved; no open finding remains in this reviewed scope.

## Limits

Review used source/diff inspection and the narrow reproduction above. The coordinator reported 3,147 Bridge tests and Ruff/mypy passing on the available environment; this reviewer did not rerun those broad gates or performance benchmarks. No hardware, SSH, deployment, network interface mutation, or Printer activity occurred. Host-local measurements do not establish Raspberry Pi latency, energy, or battery improvements. The review does not certify behavior beyond the explicitly reviewed changes.
