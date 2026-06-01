# Plan 040 — Server-driven request timestamps

## Problem

A v0.1.28 macOS app paired with a bridge whose system clock was running
~224 s behind the Mac displayed:

> Management settings unavailable — Management request timestamp is in the
> future.

The Mac signs every authenticated management request with
`X-Bridge-Timestamp = Int(Date().timeIntervalSince1970)`. The bridge
enforces `±max_request_age_s = 300 s` in the past and `+max_future_skew_s
= 30 s` in the future
(`bridge/src/instantlink_bridge/manager/auth.py:37-38, 386-392`). The Pi
Zero 2 W has no RTC; on boot it relies on fake-hwclock + a flaky NTP path
(systemd-timesyncd has to egress over USB-NAT through the Mac). When NTP
hasn't converged, the bridge clock can sit minutes behind real wall time,
and **every** signed request returns
`401 error_code="timestamp_future"`. The same failure mode hits in the
opposite direction (`error_code="stale"`) the first time the Pi runs
ahead of the host.

Simply widening the future-skew window would weaken replay protection's
effective horizon and still leave first-boot drift unbounded. The proper
fix is to **stop assuming the Mac and the bridge share a wall clock**.

## Design

### Server-driven request time

The bridge already owns the timestamp it'll *validate against*. Let the
Mac just ask for it.

1. Bridge exposes a new unsigned discovery route:
   ```
   GET /v1/time
   200 { "epoch": <int seconds> }
   ```
   No auth, no body, no nonce — equivalent in trust posture to
   `/v1/hello`. Costs nothing to leak (it's literally `time.time()`).

2. Mac maintains a per-device clock offset cache:
   `BridgeServerClockCache` keyed by `BridgeDevice.deviceID`, holding
   `(server_epoch_at_sample, mac_monotonic_at_sample)`. Effective
   server time at signing is
   `server_epoch_at_sample + (mac_monotonic_now − mac_monotonic_at_sample)`.

3. Cache is **populated lazily** — never on the happy path of the first
   request. The first signed call uses the local clock; if the bridge
   replies with `error_code="timestamp_future"` or `"stale"`, the Mac
   hits `GET /v1/time`, refreshes the cache, and retries the original
   request **once**. The retry-once policy keeps a genuinely broken
   clock from looping forever and keeps clock-skew errors visible in
   diagnostics.

4. Subsequent signed calls during the session sign with the cached
   offset, so the Mac stays in lockstep with the bridge even if the
   Mac wakes from sleep with drift.

### Why not always pre-fetch `/v1/time`?

- Doubles RTT on every signed call.
- Adds an unsigned-call dependency to every authenticated call,
  blurring the auth boundary.
- The lazy + retry-once shape pays the extra RTT only when the
  clocks actually disagree, which is the rare case.

### Why not just bump `max_future_skew_s`?

- Doesn't help on first-boot Pi where drift can be hours.
- Weakens replay protection's effective horizon (a window of
  `max_request_age_s + max_future_skew_s` nonces must be kept alive).
- Doesn't solve the symmetric "stale" failure when the Pi runs ahead.

### Replay protection still holds

The bridge gates on its **own** clock + nonce store. The Mac just
adjusts the timestamp it sends to match what the bridge will accept.
Nonces remain bridge-generated-unique-per-request; the
`max_request_age_s + max_future_skew_s` window on the nonce store is
unchanged.

## Bridge changes

- `bridge/src/instantlink_bridge/manager/contract.py`: extend
  `DISCOVERY_ROUTES` with a `/v1/time` `ManagementRoute`
  (`auth_required=False`).
- `bridge/src/instantlink_bridge/manager/api.py`: register
  `handle_time`. Inject `now_seconds` factory so tests can drive it.
- `bridge/src/instantlink_bridge/manager/status.py`: tiny
  `collect_time_payload(now_seconds=current_unix_seconds)` returning
  `{"epoch": int}`.
- `bridge/tests/test_manager_api.py`: pytest cases for happy path,
  no-auth-required, monotonicity with injected `now`.

## Mac changes

- `macos/InstantLink/Core/BridgeServerClock.swift` (new):
  - `actor BridgeServerClockCache` — `[String: ServerClockOffset]` map.
  - `struct ServerClockOffset { let serverEpochAtSample: Int; let
    monotonicAtSample: TimeInterval }`.
  - Functions: `serverEpoch(forDeviceID:monotonicNow:) -> Int?`,
    `record(deviceID:serverEpoch:monotonicNow:)`,
    `invalidate(deviceID:)`.
- `macos/InstantLink/Core/BridgeHTTPTransport.swift`:
  - Hold a `BridgeServerClockCache`.
  - Add private `getServerTime(device:) async throws -> Int` — calls
    unsigned `/v1/time`.
  - Add private `nextTimestamp(for device:) async throws -> Int` —
    reads cache; if absent, returns local clock (so first call is
    cheap).
  - Add private `sendSigned(...) async throws -> BridgeAPIEnvelope`
    that:
    1. Builds + sends a signed request using `nextTimestamp(for:)`.
    2. If response is `BridgeAPIError` with
       `code ∈ {.timestampFuture, .timestampStale}`, calls
       `getServerTime`, refreshes the cache, and retries the same
       request once.
    3. Surfaces the error otherwise.
  - Route every signed call (status / config / update / backup /
    diagnostics / etc.) through `sendSigned`.
- `macos/InstantLink/Core/BridgeModels.swift`:
  - Add `static let timestampFuture = BridgeErrorCode("timestamp_future")`
  - Add `static let timestampStale = BridgeErrorCode("stale")`

## Tests

### Bridge

- `GET /v1/time` returns `{"epoch": <int>}` with no auth headers and
  echoes the injected now factory.
- Two consecutive calls with monotonically advancing now factory return
  the advanced value.
- Route appears in MANAGEMENT_ROUTES manifest with `auth_required=False`.

### Mac

- `BridgeServerClockCacheTests`:
  - `serverEpoch` returns nil before any sample.
  - After `record(deviceID:, serverEpoch: 1_000_000, monotonicNow: 100)`
    and reading with `monotonicNow: 105`, returns `1_000_005`.
  - `invalidate` clears the entry.
  - Two devices have independent offsets.
- `BridgeHTTPTransportClockSkewTests` (URLProtocol stub):
  - First signed call → bridge replies 401 `timestamp_future`.
  - Stub asserts a subsequent `GET /v1/time` is issued.
  - Retry uses the server-anchored timestamp and the stub answers 200.
  - Final transport return value reflects the retry success.
  - A `stale` error follows the same path.
  - A non-clock-skew 401 (`invalid_signature`) bubbles up without retry.

## Rollout

1. Land bridge route + tests, deploy to Pi.
2. Land Mac transport changes + tests, ship in v0.1.29.
3. Old Mac clients hitting a new bridge: unchanged — the new route is
   additive and the existing skew enforcement is untouched.
4. New Mac clients hitting an old bridge: the new code only fetches
   `/v1/time` when it sees `timestamp_future`/`stale`; against an old
   bridge with a healthy clock, this never fires and behaviour is
   identical to today. Against an old bridge with a sick clock, the
   `/v1/time` call returns 404 — the Mac surfaces the original
   `timestamp_future` error, same as before. Acceptable degradation.

## Non-goals

- Fixing the Pi's clock itself (out of scope; orthogonal NTP/RTC work).
- Re-architecting nonce storage or signing.
- Touching the bridge skew constants.
