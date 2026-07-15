# 051 — Sync UX audit (post-plan-050)

Adversarial audit of the LCD UX after the iPhone-sync feature landed (`7b4f35d`,
`8f24c4c`), run 2026-07-14 against `bridge/docs/ux-flows.md`, the
`bridge/CLAUDE.md` UX policies, and plan 050. Verdict: **REVISE** — the data
path is sound and printing is unaffected; the defects cluster on the
status/honesty surface, mostly from reusing the READY screen for four sync
sub-states instead of giving sync its own readiness rendering.

## P1 — broken / contradicts spec

1. **iphone-only READY headline is unconditional.** `render.py` `_ready` draws
   the big `"Sync to iPhone"` title regardless of FTP readiness and never
   renders `readiness_cause_texts`; with no FTP path the top bar says
   "Waiting" while the body claims sync-ready and the Host row shows
   `FTP: no address` (render.py:1222, 3165, 3438). The controller comment
   (controller.py:107-109) references a "setup-needed body via the renderer's
   can_accept fallback" that does not exist in `_ready`. Violates ux-flows.md
   READY gating ("only when … at least one FTP receive path is visible").
   *Fix: when `not can_accept_images(snapshot)`, render the setup-needed body
   with causes instead of the ready headline; delete the false comment.*
2. **Outbox chip goes stale after ack.** `sync_outbox_changed` fires only on
   spool-add (app.py:564); `_handle_ack` (sync/server.py:227) deletes the file
   but never notifies the UI, so after the iPhone drains the queue the LCD
   can read "iPhone: 3 pending" forever (until the next upload). *Fix: notify
   depth changes from ack (and eviction), not just add.*

## P2 — confusing / should fix

3. **Sync-ready shown even when the service failed to start.** Start failures
   (port bind, zeroconf skip) only log (app.py:144-154); the READY/QR surfaces
   derive purely from config, so the screen can claim sync-ready while nothing
   listens on :8721. *Fix: thread service-listening state into the snapshot;
   degrade to "sync unavailable".*
4. **Incoming photo clobbers the QR mid-scan.** `image_received`
   (controller.py:665) sets `IMAGE_RECEIVED` with no `SYNC_PAIRING` guard —
   in both-mode a camera upload interrupts pairing. (Flagged with high
   confidence; end-to-end trace was cut short — confirm with a failing test
   first.) *Fix: defer/suppress while pairing screen is up.*
5. **QR screen dims at 30 s / blanks at 90 s mid-scan.** No idle carve-out for
   `SYNC_PAIRING`; no GPIO activity happens while someone aims a phone at the
   screen. *Fix: exempt the pairing screen from dim/screen-off (or pump
   activity while it is open).*
6. **iphone-only footer advertises the wrong actions.** With no printer
   paired the footer offers "KEY2 Refresh" (a no-op — the printer poll is
   stopped) and "Hold KEY3" (starts a *printer* scan); short KEY3 is a silent
   no-op; nothing mentions iPhone pairing (render.py:2999, controller.py:1258,
   1272). *Fix: sync-specific footer for the sync-ready surface.*
7. **Feature split across Settings pages with no cross-link.** `Send to`
   (Print page) globally changes FTP/readiness gating; `iPhone pairing`
   (Network page) is where enabling actually becomes useful. *Fix: cross-link;
   hint "Pair iPhone" on the ready surface when sync is on but no client has
   ever connected.*

## P3 — polish

8. Both-mode + empty film shows READY with a "No film · photos sync only"
   note — reasonable, but contradicts the written NO-FILM rule; document the
   carve-out (CLAUDE.md + ux-flows.md).
9. "connected" chip means "authed request in last 20 s"
   (SYNC_CLIENT_RECENT_TTL_S); overstates once the app idles. Rename to
   "active" or drive from an app heartbeat.
10. zh-Hans chip: `"3 张待传"` should drop the space before the measure word
    ("3张待传"); pressure-test chip width at largest font.
11. The QR encodes hotspot PSK + long-lived bearer token — one photo of the
    screen is persistent access until rotation. Document a token-rotation
    story; re-key the cached QR raster if the host changes while open.

## Genuinely good (keep)

- Spool-before-print ordering; outbox failures can never break printing.
- Guarded sync-service lifecycle: fire-and-forget task, never delays
  `bridge.ready`, holds no BLE locks.
- `[sync]` validation + manager-payload preservation (Mac PUTs don't drop it).
- Explicit option lists and KEY3 help on both new rows (no blind cycling).
- FTP 501 copy no longer claims a Mac is required.
- QR screen ignores stray keys (only KEY2/LEFT exits) and renders
  black-on-white regardless of theme, LRU-cached.

## Stale docs to update (with the fixes, not before)

- ux-flows.md: READY gating sync carve-out; both-mode No-Film exception; new
  `Send to` row; new `iPhone pairing` row + SYNC_PAIRING screen template;
  idle-policy exemption for the QR screen; iphone-only footer semantics.
- bridge/CLAUDE.md: "exactly 10 user-visible states" (now 11+ with
  SYNC_PAIRING); NO-FILM and Ready-to-print rules need sync exceptions.

## Execution plan

- **Pass 1 (now):** P1.1, P1.2, P2.4 (test-first — also settles the audit's
  open question), P2.5. All locally verifiable (pytest); no device needed.
- **Pass 2:** P2.3 service-state honesty, P2.6 footer, P2.7 discoverability,
  then the doc updates above reflecting as-built behavior.
- **Pass 3:** P3 items alongside the iPhone field test.

## Pass 1 outcome (2026-07-14, TDD)

- **P1.1 — did not reproduce; finding was stale.** `_ready` has had a
  `can_accept_images` → `_validation` fallback since `c43f5bd5` (2026-05-29):
  iphone-only with no FTP path already renders "Setup needed" + causes, and
  the controller comment the audit called false is accurate. The surface was
  previously untested, so the two renders (negative + positive) are now
  regression-pinned in `test_ui_render.py`.
- **P1.2 — confirmed, fixed.** `SyncService` gained a keyword-only
  `outbox_changed_callback`; `_handle_ack` notifies the new depth
  (exception-guarded), wired in `app.py` to the existing
  `notify_sync_outbox_changed` task pattern. The chip now decrements as the
  iPhone drains the queue.
- **P2.4 — confirmed by failing test, fixed.** `image_received` suppresses the
  mode switch while `SYNC_PAIRING` is up (logs
  `ui.image_received_suppressed`); queue/outbox chips still update. Settles
  the audit's open question. **New Pass-2 item:** in both-mode with a usable
  printer, the auto-print preview (`_show_print_preview`/`printing_started`)
  can still switch away from the QR — fold into Pass 2.
- **P2.5 — confirmed, fixed.** Non-ACTIVE idle-stage events arriving during
  `SYNC_PAIRING` are converted into power activity instead of applied
  (`ui.sync_pairing_idle_exempted`), so the QR never dims/blanks mid-scan;
  `SHUTDOWN_REQUESTED` (critical battery) is deliberately not exempted.
  Normal idle behavior resumes on exit (key press = real activity).
- Verification: full bridge suite 1013 passed; ruff + `mypy --strict` clean on
  touched files.

## Pass 2 outcome (2026-07-14, TDD — 27 new tests)

- **P2.3 fixed.** `UiSnapshot.sync_service_state: "starting"|"listening"|"unavailable"`
  (three states — a bool can't distinguish the async-start boot window from a
  bind failure), stamped via `BridgeUi.sync_service_state_changed(listening)`
  from all app.py start/stop/apply paths. iphone-only readiness now requires
  listening ("Sync starting" / "Sync failed · restart bridge" causes);
  both-mode stays un-gated (spool still works) but shows the failure note;
  the QR action refuses to render a QR to a dead port (toast + log).
- **P2.6 fixed.** iphone-only footer is now `KEY1 Setting / — / KEY3 iPhone`
  with both short and hold KEY3 opening the pairing QR (BACK returns home);
  both-mode-unpaired gets `KEY3 Pair` (printer scan, NEEDS_PAIRING precedent).
- **P2.7 fixed.** Send to ↔ iPhone pairing help cross-links; new boot-scoped
  `sync_client_ever_seen`; READY shows a "Pair iPhone" nudge (KEY3 /
  Settings ▸ Network per mode) when sync is listening but never used.
  Card note priority: unavailable > paused > nudge.
- **Preview-vs-QR fixed (defer policy).** `await_print_confirmation` holds the
  queue item while SYNC_PAIRING is up (event-driven wake + safety re-check);
  preserves auto-print/explicit-confirm semantics, no deadlock, countdown
  restarts after exit.
- Docs updated as-built: ux-flows.md (READY carve-out, No-Film exception, new
  rows + SYNC_PAIRING template, footer semantics, idle exemption) and
  bridge/CLAUDE.md (state list rewritten from the UiMode enum; sync exceptions
  on the Ready/NO-FILM rules).
- Verification: full suite 1052 passed; ruff/format clean; mypy --strict clean
  on touched sources.

Remaining (Pass 3, with hardware): P3 items + on-device smoke of the new
surfaces (largest-font render of nudge/unavailable lines, real port-bind
failure), iPhone field test.
