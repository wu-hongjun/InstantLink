# 031 — Bridge Printer Connection Recovery State Machine

Status: **Draft for review** (no implementation yet)
Author: takeover session, 2026-05-27
Hardware: Raspberry Pi Zero 2 W (BlueZ 5.79) ↔ Fujifilm Instax Square Link (`INSTAX-52006924`, `FA:AB:BC:C7:95:64`)

## 1. Why this plan exists

A live hardware session chased a chain of related printer-connection failures. Three fixes
shipped (and are deployed on the Pi as bridge `0.1.6`), each verified in isolation, but the last
hardware run surfaced a deeper failure mode that the point-fixes do not cover. Rather than stack a
fourth live hot-patch, we are stepping back to design the connection-recovery behaviour
deliberately. This document is the source of truth for that design (per `CLAUDE.md`, plans live in
`docs/plans/` and are committed alongside the code they describe).

## 2. What is already deployed (keep unless this plan says otherwise)

| Fix | Bridge ver | Commit | Verified | Keep? |
|-----|-----------|--------|----------|-------|
| Freshness gate — readiness requires a printer status confirmed within `max(30s, 3×keepalive)`; `printer_status_fresh` on `UiSnapshot`; render tick downgrades a stale `READY`. | 0.1.4 | `e59ba62` | ✅ Hardware: printer off → never "Ready"; on → "Ready" returns. | **Keep.** Orthogonal safety net; correct. |
| Stale-bond signature lowered from `notification_subscribe` (stage 6) to `characteristic_lookup` (stage 5). | 0.1.5 | `39e273f` | ✅ Unit. Hardware run hit a real stage-7 write failure (not a stage-5 false positive). | **Keep**, but re-evaluate threshold once §6 lands (see Risk R1). |
| Silent-link recovery — on `PrinterNotFound`, if BlueZ holds a *connected* link for the bonded printer, `disconnect_bluez_link()` drops it so the printer re-advertises. Per-device cooldown; no-op when nothing is connected. | 0.1.6 | `623afea` | ⚠️ Unit only (6 tests). Did **not** trigger in the failing run because the bond had already been removed (no connected device to drop). | **Keep** — it addresses a real, distinct deadlock (BlueZ auto-reconnect holds a silent link). Just not the one that bit us last. |

## 3. The failure this plan must fix

Observed sequence on a printer power-cycle (journal, 2026-05-27 ~13:3x):

```
stage=ble_connecting → service_discovery → characteristic_lookup → notification_subscribe
  → model_detecting → stage=failed  "BLE error: write failed"     # genuine stale bond (stage 7)
auto_rebond action=remove_bond → done=remove_bond                 # correct: stale bond removed
stage=ble_connecting → service_discovery → ble_connecting → failed
  "connect failed after service discovery retry"                  # re-pair attempt failed
stage=failed → "printer not found" (repeats forever)              # printer no longer discoverable
```

Post-mortem facts gathered live:
- After the rebond, `bluetoothctl info FA:AB:BC:C7:95:64` returns **nothing** — the device is gone
  from the BlueZ object table (removed by the rebond and never re-added).
- A **sustained 10 s `bluetoothctl scan on` sees no `INSTAX` advertisement at all.** The printer is
  **not advertising**. It stayed non-advertising for >100 s — well past any normal BLE supervision
  timeout — so it is durably wedged, not mid-retry.
- The printer *was* advertising and connectable at power-on (the Pi connected far enough to reach
  stage 7 before the write failed), so the wedge is a *consequence of our recovery*, not the
  power-on state.

**Root-cause statement (high confidence):** removing the BlueZ bond mid-session, after a connect
that reached late GATT stages, leaves the **printer** holding a half-open / "ghost" link on its
side. The Instax stops advertising while it believes it has an active central, so the bridge can
never rediscover it. Only a printer power-cycle (or a much longer printer-side timeout) clears it.
The current `remove_bluez_bond` path (`bluetoothctl remove <addr>`) does not guarantee the printer
observes a clean link-layer disconnect before the device object is destroyed.

This is **distinct** from the two deadlocks already handled:
- Not the freshness/stale-display bug (0.1.4).
- Not the BlueZ-holds-a-silent-connected-link deadlock (0.1.6) — here the device is *removed*, so
  there is no connected object to drop.

## 4. Hypotheses for the wedge (validate before committing to a fix)

| ID | Hypothesis | How to confirm | Implication if true |
|----|-----------|-----------------|---------------------|
| H-A | `bluetoothctl remove` destroys the device object without a clean LL `Disconnect`, so the printer never sees the teardown and holds the link. | Instrument: before `remove`, log `Connected`; issue explicit `disconnect`, poll `Connected=no`, *then* `remove`; observe whether the printer re-advertises. | Fix = clean disconnect + settle before remove. |
| H-B | The btleplug-side `device.disconnect()` on the status-fetch error path completes locally but BlueZ/controller does not emit the LL disconnect (e.g. because the bond removal races it). | Add LL-level tracing (`btmon`) during the rebond window. | Fix = serialize disconnect → confirm → remove; add settle delay. |
| H-C | The Instax firmware genuinely wedges for a long, fixed interval after an interrupted pairing, regardless of clean disconnect. | After a *clean* disconnect (H-A fix) the printer still won't advertise for N seconds. | Bond removal is too costly; prefer reconnect-without-removal (see §6, Option 2). |
| H-D | Removing the bond is unnecessary: a plain reconnect (without `remove`) re-pairs via the `NoInputNoOutput` agent because the printer already cleared *its* key on power-cycle. | A/B: on the stale-bond signature, try reconnect-only first; only remove the bond if reconnect-only fails K times. | Auto-rebond should be a last resort, not first response. |

`btmon` capture during one power-cycle is the single highest-value diagnostic and should be step 1
of implementation.

## 5. Design goals / invariants

1. **Never wedge the printer.** Any recovery action must leave the printer either connected or
   freely advertising — never holding a ghost link.
2. **Always converge.** From any failed state, the bridge must return to "searching → connected"
   without user intervention (no "hold K3", no power-cycle) within a bounded time.
3. **Bond removal is a last resort**, gated and rate-limited, because it is the most disruptive
   action and the suspected wedge trigger.
4. **One owner of the BLE link.** The FFI/btleplug session and BlueZ auto-reconnect must not fight
   over the single Instax connection slot. Recovery decisions live in one place (the controller),
   driven by typed failure signals from the status provider.
5. **Observable.** Every recovery transition emits a single structured log line; the LCD shows an
   honest, specific state (not a generic spinner).

## 6. Proposed recovery state machine (to be refined after §4 validation)

Failure signals already available as typed fields on `PrinterStatusUnavailableError`:
`stale_bond_suspected` (connect reached ≥ stage 5 then BLE-failed) and `printer_not_found`
(advertisement scan saw nothing). We add the wedge dimension.

```
        ┌────────────┐  status ok
        │  CONNECTED  │◀───────────────────────────┐
        └─────┬───────┘                            │
   status fail │                                   │ status ok
        ▼      ▼                                    │
   ┌──────────────┐  not_found (& was advertising)  │
   │  SEARCHING   │─────────────┐                   │
   └─────┬────────┘             │                   │
 stale_bond_suspected           │ not_found persists│
        ▼                       ▼                   │
 ┌───────────────┐      ┌────────────────┐          │
 │ RECONNECT_ONLY│      │ SILENT_LINK_RX │──drop────┘
 │ (no remove,   │      │ (BlueZ holds   │  connected link
 │  K attempts)  │      │  connected)    │
 └─────┬─────────┘      └────────────────┘
   still failing after K
        ▼
 ┌──────────────────────────┐
 │ REBOND (last resort):     │
 │ 1. clean disconnect       │
 │ 2. confirm Connected=no   │
 │ 3. settle delay           │
 │ 4. bluetoothctl remove    │
 │ 5. confirm re-advertising │  ← if not re-advertising within T, surface "Restart printer"
 └──────────────────────────┘
```

Key changes vs. today:
- **RECONNECT_ONLY before REBOND** (tests H-D): on the stale-bond signature, first retry a plain
  reconnect K times (the printer cleared its own key on power-cycle, so the agent may re-pair
  without us removing anything). Only escalate to REBOND if reconnect-only keeps failing.
- **REBOND becomes a guarded sequence** (tests H-A/H-B): clean disconnect → confirm `Connected=no`
  → settle → `remove` → confirm the printer re-advertises. If it does not re-advertise within `T`,
  stop looping and show a specific, honest recovery prompt instead of silent "Finding Printer".
- **Wedge detection / honest UI:** if the printer is neither connected nor advertising for `> T`
  after a REBOND, the LCD must say something actionable (e.g. "Restart printer") rather than an
  endless "Finding Printer". This directly addresses the trust complaint.

## 7. Implementation phases

- **Phase 0 — Diagnose (no behaviour change).** Add `btmon`/structured tracing around the rebond
  window; run one power-cycle; confirm which of H-A…H-D holds. Land findings in this doc.
- **Phase 1 — Guarded REBOND.** Clean disconnect + confirm + settle + remove + re-advertise check.
  Unit tests for the sequence ordering; hardware test: power-cycle → must not wedge.
- **Phase 2 — RECONNECT_ONLY escalation.** Try reconnect K times before any bond removal. Tune K /
  thresholds. Re-evaluate the stage-5 stale-bond threshold (Risk R1) once reconnect-first exists.
- **Phase 3 — Wedge UI.** Bounded recovery → honest "Restart printer" copy; never loop silently.
- **Phase 4 — Durable core fix (carry-over from the 0.1.6 follow-up).** Make the core adopt an
  already-connected/known peripheral when the advertisement scan misses it (`adapter.peripherals()`
  rather than advertisement-only `transport::scan`). Removes the silent-link mitigation's reliance
  on a Python-side disconnect. Requires cross-compiled `.so` redeploy (cargo-zigbuild).

## 8. Validation (hardware, per phase)

For each phase, the acceptance test is a **printer power-cycle while the bridge is running**:
1. Printer off → LCD leaves "Ready", shows searching (freshness gate — already passing).
2. Printer on → bridge connects and shows status within a bounded time **without** the printer
   wedging (no sustained non-advertising state; `btmon` shows a clean disconnect on any teardown).
3. Repeat 5× consecutively with no manual intervention (no `bluetoothctl` by hand, no power-cycle to
   un-stick). This is the bar that the current build fails and that the freshness gate alone cannot
   satisfy.
Battery/film status must keep flowing on the 10 s keepalive throughout the connected state.

## 9. Risks

- **R1 — stage-5 stale-bond threshold may now over-trigger** once reconnect-first exists; a stage-5
  characteristic-lookup miss can be transient. Re-evaluate after Phase 2; consider requiring 2
  consecutive signatures or reserving REBOND for stage ≥ 6 again once RECONNECT_ONLY absorbs the
  transient cases.
- **R2 — single connection slot.** BlueZ auto-reconnect of the bonded device competes with the FFI
  session for the Instax's one slot. Phase 4 (adopt the existing connection) is the principled fix;
  until then the silent-link mitigation (0.1.6) papers over it.
- **R3 — `Trusted: no`.** The bonded device shows `Trusted: no`. `CLAUDE.md` warns bonded printers
  should be `Trusted=true` or reconnect-after-reboot can fail. Decide in Phase 1 whether to set
  trust on pair (and whether that *worsens* R2 by making BlueZ auto-reconnect more aggressively).
- **R4 — cross-compile cadence.** Phases 1–3 are Python-only (fast `--deps OFFLINE_DEPS` deploy).
  Phase 4 needs an `.so` rebuild; budget for slower hardware iteration.

## 10. Out of scope

- The freshness gate, stage-5 signature, and silent-link mitigation already shipped (§2) — kept.
- macOS app behaviour (CoreBluetooth manages bonding itself; the BlueZ bond dance is Pi-specific).
  We borrow its UX contract (always searching, robust reconnect) but not its bonding mechanism.

## 11. Immediate operator note

The printer is currently wedged from the failing run. **Power-cycle the printer** to restore a clean
state before further testing.

---

## 12. Phase 0 findings (2026-05-27, btmon capture `14:20:57–14:23:47` local / `18:20:57Z`)

**The capture did NOT reproduce the rebond→wedge in §3.** No write failure, no `auto_rebond`, no
bond removal occurred. Instead it exposed a *different and apparently dominant* failure: **the LE
connection never establishes at all.**

### Evidence
- **Bridge journal** (every attempt, repeating): `scan_started → scan_finished → device_matched
  (INSTAX-52006924 (IOS)) → ble_connecting → stage=failed "BLE error: connect failed: Timeout
  waiting for reply"`. The printer **is** discovered and matched every cycle (good RSSI −46…−72 dBm).
  "Timeout waiting for reply" is a **D-Bus** reply timeout on BlueZ's `Connect()`.
- **btmon (link layer), full 170 s:**
  - Only `LE Set Scan Enable` connection-class commands. **Zero `LE Create Connection`,
    zero `LE (Enhanced) Connection Complete`, zero `Device Connected (mgmt 0x000b)`,
    zero `Disconnect`.** The controller was never told to connect, and no connection ever completed.
  - Three `MGMT Event: Connect Failed (0x000d)` for `FA:AB:BC:C7:95:64`, each `Status:
    Disconnected (0x0e)`, one per connect attempt.
- **Isolation ladder (each tried, none recovered):**
  1. Manual `bluetoothctl connect` → `org.bluez.Error.InProgress "In Progress"`.
  2. `bluetoothctl disconnect` → "Disconnection successful" (cancels the stuck attempt) but the next
     bridge attempt re-wedges to `In Progress` within seconds.
  3. Adapter `power off/on` → still `Timeout waiting`.
  4. Bridge process restart (fresh btleplug `Manager`/adapter) → still `In Progress`.
  5. `bluetoothd` + bridge restart (fully fresh Pi BLE stack) → still `In Progress` / `Timeout`.

### Conclusion
The **Pi side is healthy and was reset at every layer**; the printer advertises connectable but
**no connection ever completes**, leaving BlueZ stuck in a perpetual "connection In Progress" that
never times out or self-cancels. This is **not** the rebond ghost-link (§3) and **not**
"not advertising" — it is a failure to complete the LL connection to an advertising, bonded peer.

### Revised hypotheses (supersede H-A…H-D as the primary target)
| ID | Hypothesis | Decisive probe |
|----|-----------|----------------|
| P1 | **Printer firmware wedge:** after repeated power-cycles / bond churn the printer advertises but no longer honours connection requests; only a printer power-cycle clears it. | Clean printer power-cycle (off ≥5 s, on) with the fresh Pi stack already in place; confirm `Connection Complete` + status. |
| P2 | **BlueZ background/allowlist auto-connect never fires** for this bonded *Static Random* address on the Pi Zero 2 W controller (explains zero `LE Create Connection`); a *direct/active* connect would work. | With bond present it stays stuck; remove bond → BlueZ falls back to direct connect → does it now issue `LE Create Connection` and succeed? |
| P3 | **Stale LTK on the Pi:** BlueZ tries encrypt-on-connect with a key the (re-paired-cleared) printer rejects, dropping the link. | Weak: argued against by the total absence of any `Connection Complete`/`Disconnect` HCI (never gets to encryption). |

P1 vs P2 is the next fork. P2, if true, is the highest-value fix: **stop relying on BlueZ
background auto-connect; drive a direct active connection** (and/or do not keep a stale bond that
pushes BlueZ onto the background-connect path). The shipped bond-removal auto-rebond and the
silent-link (`disconnect when Connected`) mitigation target neither P1 nor P2 — they assume the
connection gets far enough to fail at GATT/write, which this failure does not.

### Phase 0 → revised next steps
1. **Clean printer power-cycle** with the now-fresh Pi stack; capture btmon again. If it connects,
   P1 is confirmed (printer wedge) and recovery must include "ask user to restart printer" UX plus a
   bounded give-up (never silent infinite "Finding Printer").
2. If it still fails after a clean printer power-cycle, test P2: remove the bond and watch whether a
   **direct** connect issues `LE Create Connection` and completes. If yes, the fix is connection-path
   (direct connect / bonding strategy), not the recovery state machine in §6.
3. Re-scope §6: the recovery machine must first handle "connection never completes / BlueZ stuck
   In Progress" (cancel pending + bounded retry + honest UI), which is more common than the
   rebond-wedge it was originally drawn around.

### Phase 0 CONCLUSION (after the clean printer power-cycle test)

A clean printer power-cycle did **not** fix it (still cycled through `printer not found` /
`In Progress`). What **did** recover it — twice today, reproducibly — was a **sustained active
`bluetoothctl scan on`**: within seconds of active scanning, BlueZ completed the connection
(`Connected: yes`) and the bridge immediately adopted it and resumed `film_remaining=4` status
every 10 s. The phone app was confirmed **not** connected, ruling out single-slot contention.

This favours **P2 over P1**: the printer is fine once a connection is actually initiated; the
failure is that **BlueZ's background/passive auto-connect (allowlist) for the bonded printer does
not fire reliably on the Pi Zero 2 W controller** — consistent with btmon showing *zero*
`LE Create Connection` over 170 s (background mode armed but never firing). An **active scan forces
discovery and lets the connection complete** (an active scan elicits the advertisement that triggers
the controller's connect, and/or btleplug then issues a direct connect).

**Confirmed root cause (Phase 0):** the bridge relies, via BlueZ, on background auto-connect to the
bonded printer; on this controller that path stalls (`In Progress` / `printer not found` / D-Bus
`Connect()` timeout), and only sustained **active scanning / a forced direct connect** reliably
establishes the link. Once connected, everything downstream (status, keepalive, freshness gate)
works. The freshness gate (0.1.4) behaved correctly throughout — never showed "Ready" while
disconnected. The shipped bond-removal auto-rebond (0.1.5) and silent-link-disconnect (0.1.6)
address adjacent symptoms but **not** this connect-initiation stall.

**Fix direction for implementation (supersedes §6's framing):**
1. **Drive a continuous/active scan while disconnected** (not 5 s bursts with idle gaps) so the
   controller keeps seeing the advertisement and the connection can complete — mirror what the
   manual `scan on` does. Re-check `transport::scan` duty cycle and whether `peripheral.connect()`
   on BlueZ defers to background mode vs. issuing a direct `LE Create Connection`.
2. **Bound every failure with honest UX:** never loop silent "Finding Printer"; after N failed
   connects surface a specific, actionable state.
3. **De-prioritise bond removal** as a recovery (it targets the wrong layer and previously wedged
   the printer); keep it only as a last resort behind reconnect-first.
4. Validate any change by the §8 acceptance bar: 5 consecutive printer power-cycles auto-recovering
   with **zero** manual `bluetoothctl` intervention.

State note: live probing (manual scans, disconnects, adapter/bluetoothd restarts) contaminated the
observed state during Phase 0; the *reproducible* signal — "active scan completes the connection" —
is the reliable takeaway. The system is currently healthy (`Connected: yes`, film 4/10).

---

## 13. Phase 1 implementation + outcome (2026-05-27, bridge .so 0.1.11 → 0.1.12)

**Change (commits `4f57404`, `68892c8`):**
- `transport::scan()` split into `start_scan` / `collect_instax_peripherals` / `stop_scan`
  (`scan()` still composes them for the standalone scan + `connect_any` callers).
- `connect_internal` now keeps an **active scan running across discovery AND the connect/status
  handshake** (was: `stop_scan` before connecting, which dropped onto BlueZ's stalling
  background-connect path), and **polls the candidate list to connect the moment the target is
  uniquely matched** (`DISCOVERY_POLL_INTERVAL` 400 ms) instead of sleeping the full 5 s window.

**Result — partial pass:**
- ✅ **From a clean BlueZ state it works.** After a `bluetoothd` restart, 0.1.11 connected
  autonomously in ~10 s (first time all day without a manual `scan on`), and a **printer
  power-cycle recovered on its own (1 cycle): write-fail → auto_rebond → reconnect → status, no
  wedge, ~58 s** (3 attempts incl. the stale-bond rebond; ~11 s `ble_connecting` per attempt is the
  dominant cost). The poll-during-scan trims the per-attempt scan wait.
- ❌ **New, distinct failure isolated: a *bridge restart* wedges BlueZ.** The 0.1.12 deploy restarts
  the bridge but not `bluetoothd`; the old process, killed while a connect was pending (printer
  asleep), left BlueZ stuck. The fresh 0.1.12 then failed **7/7** connects with
  `connect failed: Timeout waiting for reply` over 6 min even though the printer was matched 6× —
  cleared only by a `bluetoothd` restart. This is the same "stuck In Progress" wedge from Phase 0,
  but its **trigger is a bridge restart** (deploy / crash / systemd `WatchdogSec` restart), which
  the active-scan fix does not address (it helps *initiate* from a clean state; it can't clear a
  pre-existing stuck pending connect).

**So Phase 1 fixes the clean-state connect stall and the printer-power-cycle recovery, but does NOT
satisfy the §8 acceptance bar yet** because a bridge restart can leave BlueZ wedged with no
self-heal.

### Phase 2 scope (the bridge-restart wedge)
The bridge must self-heal from a `Timeout waiting for reply` / `org.bluez.Error.InProgress` wedge
rather than depending on a manual `bluetoothd` restart:
- **Runtime self-heal (preferred):** on a connect that fails with the wedge signature, cancel the
  stuck pending connection (`peripheral.disconnect()` / BlueZ `Device.Disconnect`) before retrying;
  the active-scan retry should then complete. Phase 0 saw a one-shot cancel re-wedge *without* the
  active-scan fix — re-test now that the active scan is in place.
- **Startup hygiene:** on bridge start, cancel/clear any stale pending connection for the selected
  printer before the first connect, so a restart never inherits a wedged Device1.
- **Operational stopgap:** have `deploy-to-pi.sh` (and/or the systemd unit ordering) restart
  `bluetooth.service` alongside the bridge so deploys don't leave a wedge. Cheap; does not fix
  watchdog-triggered restarts, so it is a stopgap, not the fix.
- Investigate the **shutdown path**: the old bridge wedging BlueZ when killed mid-connect (printer
  offline) is the trigger; a clean cancel-on-shutdown would prevent creating the wedge at all
  (relates to the existing `TimeoutStopSec=12` note).

### Acceptance status
§8 bar (5 consecutive printer power-cycles, zero manual intervention): **not yet met** — blocked by
the bridge-restart wedge. Clean-state printer power-cycle recovery: **1/5 observed, passing.**

### Phase 2 attempt #1 — runtime cancel-on-error: REVERTED (counterproductive)

`0.1.13` added `cancel_pending_connection` (an unconditional `Device.Disconnect`) on the first
connect error, plus the deploy stopgap. On hardware it made things **worse**: from a *clean* BlueZ
state the printer was matched ~10× over 7 min but **never connected** — every attempt failed
`connect failed: In Progress` and none reached `service_discovery`.

Root cause of the regression: on this controller `peripheral.connect()` returns a transient error
(`In Progress`) **while the active-scan background connect is still completing**. 0.1.12 lets that
pending connection finish (the next poll finds it connected); the new cancel **disconnected the
in-flight connection every cycle**, so it could never complete. Lesson: **`In Progress` is success
in progress — never cancel it.** Reverted in `0.1.14` (restored 0.1.12 connect path; removed the
helper). The deploy stopgap (restart `bluetooth.service` on `--restart`) is **kept** — harmless and
gives clean deploys.

Revised Phase 2 plan: do **not** cancel on a generic connect error. The genuine wedge to handle is
only `Timeout waiting for reply` (a stuck D-Bus `Connect()`), which is distinct from `In Progress`.
A future self-heal must (a) match that specific signature, (b) only act after several consecutive
failures (not the first), and (c) never disconnect while a connection is `In Progress`. For now the
deploy stopgap covers deploys; crash/watchdog-triggered wedges remain a known open item.

Next: validate `0.1.14` (clean 0.1.12 connect behaviour + deploy stopgap) against the §8 5× bar.

---

## 14. Milestone — 2026-05-27 (end of day)

Hardware-validated. The combination of two final changes, working together, brings the
power-cycle reconnect from the ~25 s starting point to **~4 s active** (`scan_started → connected
with status`), confirmed across two consecutive power-cycles with a clean trace (zero
`write failed`, zero `auto_rebond`, zero wasted attempts).

### Final state on hardware
- **Crates `0.1.17`** (`66b95a0` hybrid connect): the fast stop-scan path with a 5 s budget tries
  first (~0.3–1.5 s on a healthy BlueZ); on a wedge-signature error (`In Progress` /
  `Timeout waiting for reply`) **or** the timeout firing, it forces a bounded
  `peripheral.disconnect()` to clear any half-set-up BlueZ link and falls back to the slow
  (~11 s) but reliable active-scan retry. Restores the speed win from `0.1.15` **and** the
  wedge-recovery from `0.1.12`/`0.1.16` — the previous two strategies each lost one of those.
- **Bridge `0.1.11`** (`179cf0f` always-fresh-pair): on the `_printer_was_online` True→False edge
  the bridge proactively removes the BlueZ bond (gated `Connected=no`, double-checked at the
  pairer), so the *next* reconnect after a power-cycle pairs fresh via the `NoInputNoOutput` agent
  — no stale-LTK write-fail and no reactive `auto_rebond` detour. `auto_rebond` stays as a
  dormant safety net.

### Measured trace (cycle 2, representative — 03:13:42 → 03:14:02 UTC)
```
03:13:42  film_remaining=4                       last keepalive before drop
03:13:53  proactive_bond_reset done=remove_bond  ← always-fresh-pair fires on drop
03:13:58  scan_started                           ← printer back on, advertising
03:13:59  device_matched                          (~0.5 s into scan)
03:13:59  ble_connecting
03:14:00  service_discovery                      ← FAST PATH: 1.5 s (was ~11 s)
03:14:02  connected
03:14:02  film_remaining=4
```
Both cycles landed within ~100 ms of each other on the active reconnect interval.

### Eliminated costs vs. the ~25 s starting point
| Cost | Before | After | How |
|------|--------|-------|-----|
| ~10 s detect-drop gap | yes | gone | `_printer_was_online`-aware 0 s retry on connected→failed edge |
| ~5.6 s write-fail attempt (stale bond) | yes | gone | proactive bond removal on drop edge |
| ~5.6 s wasted post-rebond `service_discovery` retry | yes | gone | no rebond → no wasted retry; hybrid fallback only on wedge |
| ~11 s `ble_connecting → service_discovery` | yes | ~1.5 s | hybrid fast path: stop scan before connect |
| `In Progress` wedge → stuck forever | regression in `0.1.15` | recovers in ~11 s | hybrid active-scan fallback + bounded disconnect |

### Pipeline used
Architect (read-only design) → executor (implementation) → codex (review) → I integrated
findings and ran the hardware deploy/test loop. Architect's **Rec 1 (always-fresh-pair)** shipped
in `0.1.11`; the **hybrid** answered the speed-vs-recovery tradeoff that surfaced after the `0.1.15`
regression. Codex flagged one HIGH (cancellation-safety on timeout) + one LOW (5 s budget) on the
hybrid; both fixed before deploy.

### Still open / worth iterating
- §8 acceptance bar (5× consecutive auto-recovery): **2/5 verified** today; user is "iterating."
- The recurring BlueZ "In Progress" wedge root cause is still untraced at the controller layer; the
  hybrid recovers from it (slow path), so the bar moved from "blocker" to "tolerated cost."
- The Instax's own ~2–3 s boot/settle before it advertises is inherent and not addressable here —
  this sets the practical floor for an immediate-power-cycle reconnect at ~5–6 s end-to-end.
- Codex `is_wedge_signature` substring match (LOW): pragmatic, cost of a false-positive is ~11 s
  spurious fallback — accepted.

### Knobs left in for ops
- Settings > Printer > **Search rate**: 5 s (continuous) / 15 s / 30 s / 60 s, no backoff.
- Settings > Printer > Keepalive: 5 s / 10 s / 15 s / 30 s (unchanged).
- `deploy-to-pi.sh --restart` restarts `bluetoothd` first (deploy-time wedge stopgap).
