# InstantLink local patch

Source: crates.io `bluez-async` 0.8.2 (lockfile checksum before this patch:
`84ae4213cc2a8dc663acecac67bbdad05142be4d8ef372b6903abf878b0c690a`).
Upstream tag: <https://github.com/bluez-rs/bluez-async/tree/bluez-async-0.8.2>.
Original source and examples are retained, with localized changes to
`src/lib.rs`, `src/messagestream.rs`, `src/device.rs`, `src/serde_path.rs`, and
`Cargo.toml` described below. License files
are copied from that upstream tag; the upstream `MIT OR Apache-2.0` license applies.

The runtime behavior change is ownership of MessageStream teardown: retain its
receiver and match until local filter removal, remove the daemon rule even if
the local filter is temporarily unavailable during dispatch, and handle errors
and drops outside an entered Tokio runtime without panicking. Cleanup is bounded
(100 ms local-dispatch retry plus a 1 second daemon RPC) and issues exactly one
daemon RemoveMatch per registered stream while an entered runtime is available.
Outside a runtime, local detachment is best effort and daemon cleanup waits for
connection closure. A callback remaining in flight beyond the retry budget can
leave a weak local filter until a queued signal or connection closure removes it;
it cannot deliver into the abandoned stream. No permanent cleanup task is created.

Private-bus race tests require Linux, an isolated dbus-daemon, and no Printer:
`dbus-run-session -- <bluez-async-test-binary> --ignored messagestream::tests`.
The tests never access BlueZ or the system bus.

The vendored package is a workspace member so the standard workspace gates also
compile/test its code on Linux. Its library and DBus dependencies are scoped to
Linux, where btleplug uses this backend; on macOS the library is empty and the App
continues using btleplug's CoreBluetooth backend. Upstream examples remain intact
and opt-in with the `examples` feature. The three InstantLink crates remain the
default workspace members. Production dependency versions are unchanged; only
upstream example/test dev-dependencies were added to the lockfile.

The production Tokio dependency explicitly enables `time` for bounded cleanup;
its version is unchanged.

Three equivalent upstream style adjustments allow the workspace's strict Clippy
gate: remove redundant formatting borrows in two warning logs (`device.rs`), and
return the already-correct Result directly in path deserialization (`serde_path.rs`).
Their values, errors, and runtime behavior are unchanged.
