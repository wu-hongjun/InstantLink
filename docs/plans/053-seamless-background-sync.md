# 053 — Seamless background sync (BLE wake + background transfer + Live Activity)

## Why

The v1 sync loop (plan 050) is foreground-only: the iOS app must be open for
photos to flow. The target experience is appliance-grade: **as long as the
Bridge is powered, camera photos land in the iPhone's Photos library without
the phone being in the app** — with a Live Activity / Dynamic Island surface
showing transfer progress instead of an open app.

Prerequisite: a **paid Apple Developer membership**. Three independent
reasons, any one of which is sufficient:
- free-team installs expire after 7 days — an always-installed accessory
  companion cannot exist on a free team;
- the Hotspot Configuration entitlement (invisible Wi-Fi joins) is refused to
  free teams (verified 2026-07-15);
- Live Activity push updates and any future APNs channel need the program.

This plan is the readiness bar for buying the membership: everything here is
designed so the purchase unlocks it, and nothing here is throwaway if pieces
ship early in foreground form.

## The iOS platform boundaries this design respects

1. **No background poll loops.** A suspended app gets no timer. The sanctioned
   wake path for accessories is CoreBluetooth: an app with the
   `bluetooth-central` background mode, holding a connection to a paired
   peripheral with a subscribed characteristic, is woken (~10 s of execution)
   when the peripheral notifies — and is *relaunched* for the event via state
   restoration if iOS had terminated it. (Not after user force-quit or before
   first unlock; those are platform-wide limits every accessory app shares.)
2. **Downloads outlive the app.** `URLSession(configuration: .background)`
   hands transfers to the system daemon; they proceed while the app is
   suspended and each completion briefly wakes the app to save/ack/update UI.
   Works on local networks — no internet required.
3. **No Wi-Fi joins from the background.** `NEHotspotConfiguration` is a
   foreground affordance. Consequence: at home (Same Wi-Fi mode) background
   sync is fully silent; in the field (hotspot mode), if iOS left the Bridge
   network, the BLE wake posts a **local notification** — one tap foregrounds
   the app, which re-joins invisibly and syncs. One tap is the iOS floor.

## Architecture

```text
Camera ──FTP──▶ Bridge outbox (plan 050)
                    │ outbox depth changed
                    ▼
        BLE GATT "pending" characteristic ── notify ──▶ iPhone (backgrounded)
                                                            │ ~10s CB wake
                                            ┌───────────────┴───────────────┐
                                            │ on Bridge LAN?                 │
                                            ▼ yes                           ▼ no (field, wandered off)
                                 enqueue background-URLSession      local notification
                                 GET /v1/photos/{id} (Range)        "N photos — tap to import"
                                            │ per-task completion wakes app
                                            ▼
                                 save to Photos → POST ack → update Live Activity
```

- **Control plane — BLE (extends plan 052's GATT service).** New
  characteristic `a7a6cdd7-…` (already reserved): `outbox_pending` (uint16,
  notify + encrypted-read). The bridge notifies on every outbox add/ack. The
  iOS app maintains a standing (auto-reconnecting) CB connection with state
  restoration; subscription is created at ASK pairing time.
- **Data plane — existing HTTP API, unchanged.** Background URLSession with
  per-item download tasks (Range resume already server-side). The 20s
  "active" TTL and outbox chip on the LCD work unchanged since every request
  is still token-authed HTTP.
- **Foreground stays the fast path.** The current 4 s poll loop remains; the
  background machinery is additive.

## Live Activity / Dynamic Island

- Start: on the BLE wake that begins a transfer batch (ActivityKit allows
  starting from background execution windows).
- Update: on each background-URLSession task completion (per-photo progress:
  "2 of 5 · DSC01262", ring in the compact Dynamic Island). Per-byte smooth
  progress is NOT promised — background wakes are per-task, not per-chunk;
  the Activity updates in photo-sized steps. (A later APNs/frequent-update
  channel can smooth this; explicitly out of scope for v1.)
- End: batch drained → success state for a few seconds → dismiss. Failure →
  "Tap to finish importing" state that deep-links into the app.

## Bridge work (phase A — extends 052-A)

- `outbox_pending` GATT characteristic + notify on outbox add/ack/evict
  (single writer: the sync service already owns depth-change callbacks).
- Advertise/notify policy follows plan 052's honesty rules (only while
  destination includes iPhone and the sync service is listening).
- No other bridge changes: the HTTP data plane is already correct.

## iOS work (phase B)

- B1 — background plumbing: `bluetooth-central` UIBackgroundMode, CB state
  restoration, standing connection manager, wake handler that checks LAN
  reachability (quick /v1/status probe) and either enqueues background
  downloads or posts the local notification. Background URLSession migration
  of SyncClient's download path (keep the foreground fast path); save/ack in
  completion wakes; synced-ids dedupe unchanged.
- B2 — Live Activity: ActivityKit attributes (batch count, current file,
  fraction), start/update/end from the wake windows; Dynamic Island compact +
  lock-screen presentation.
- B3 — field polish: notification category with "Import" action, re-join
  UX on tap, battery instrumentation (standing BLE link is ~negligible;
  measure anyway), settle Photos-permission edge cases in background saves.

## Verification gates

- **Gate 1 (with 052's Gate 0):** Bridge advertises + notifies while the
  printer link is active — coexistence spike outcome governs both plans.
- **Gate 2:** phone locked in pocket, app not open, home Wi-Fi: camera shot →
  photo in Photos with no interaction, < 60 s. Journal shows served/acked;
  no foreground session existed.
- **Gate 3:** hotspot mode, phone wandered off Bridge Wi-Fi: camera shot →
  notification < 30 s → one tap → import completes with app immediately
  backgrounded again.
- **Gate 4:** Live Activity appears/updates/dismisses through a 5-photo burst
  with the app never foregrounded (home Wi-Fi case).
- **Gate 5:** 24 h soak — standing BLE link survives Bridge reboots (recon-
  nect), no battery complaint on either side, no stuck Live Activities.

## Risks / open questions

- **CB background wake latency** is officially "opportunistic": usually
  seconds, occasionally tens of seconds. Gates measure reality; the local-
  notification fallback bounds the worst case.
- **Bridge BLE coexistence** (peripheral advertiser + printer central on one
  BCM43436 radio) — inherited from plan 052 Gate 0; this plan dies or
  degrades with it (degraded mode: notify only while no print active).
- **Background URLSession to a LAN host** is well-trodden but the no-internet
  hotspot case needs a real soak (iOS network-path flapping while the daemon
  holds tasks).
- **Force-quit** (user swipes the app away) disables all background wakes
  until the next manual open — platform behavior, document in-app, not
  fixable.
- **Battery**: standing BLE connection + periodic wakes; measure in Gate 5
  before tuning connection latency parameters.
- Whether ActivityKit start-from-background needs the app to have been
  foregrounded since last device boot (verify empirically in B2).

## Sequencing

052 Gate 0 (radio spike) → 052 A/B (ASK pairing) → **buy the membership** →
053 A (pending characteristic) → 053 B1 (background wake + transfer) →
Gate 2/3 → 053 B2 (Live Activity) → Gate 4/5 → ship. Foreground v1 (plan 050)
remains fully functional at every intermediate point.
