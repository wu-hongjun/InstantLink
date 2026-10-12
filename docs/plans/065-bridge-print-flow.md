# 065 — Simplify the one-photo print flow

Date: 2026-10-11. Scope: Bridge print screens and copy; locked Wi-Fi recovery validation.

## User request

Deploy the pending Wi-Fi recovery fix and verify it while locked with the Printer connected.
Reduce the number of screens and verbose text shown when printing one photo.

## Screen audit and implementation

The old path displayed receipt, a preparation placeholder, a timer-free Preview frame, review,
Starting/Checking/Finding Printer, transport stages, standalone completion and Home. Some states
lasted only until the next coroutine completed, producing flashes without a useful decision.

| Path | New visible flow |
| --- | --- |
| Timed review | One Review card: Preparing → photo plus countdown → one Printing layout → Home with Printed notice |
| Manual review | Same Review card; editing stops the countdown and KEY1 confirms |
| Immediate printing | One Printing layout → Home with Printed notice |
| Cancel | Return to cached Home; cancel preparation safely |
| No film | Keep reload guidance and allow navigation; normal polling detects reloaded film |
| Failure | Preserve the error and Check action; never resend automatically |
| Slow/stalled job | Keep Still printing / Print stalled and restart feedback |
| Sync | Spool and Sync Home retain their existing behavior; no print screens |

- Receipt records photo identity and activity without a separate screen or timer.
- Preparation stays inside the fixed photo card. The first ready frame includes its actual
  countdown; no timer-free preview flash precedes it. Editing retains manual confirmation.
- Printing keeps a fixed headline and one short stage: Connecting, Preparing, Sending or
  Finishing. One progress bar/percentage and the filename provide useful feedback. Remove
  duplicated progress, packet/KB details, Printer model, repeated key hints and generic warnings.
- Completion uses Home's existing card with Printed feedback, including a successful last-sheet
  print. Its two-second expiry cannot replace Settings/Post opened by the user. No-film guidance
  likewise has no forced expiry that flashes a new Printer check.
- English and Chinese use the same concise wording. Print admission, transport serialization,
  no-film checks, hard timeout, active-job boosts, lock and same-button unlock remain intact.

## Rendered evidence

![Simplified one-photo flow](../assets/bridge-print-065/print-flow.png)

Synthetic local render using a neutral test image, not a physical LCD photograph. Connecting,
Sending and Finishing above are progress updates within one layout.

## Validation and device status

Controller, app, preview and renderer regression checks cover initial frames, countdown timing,
navigation during completion/no-film, concise stages, translated copy and last-sheet success.
A locked-recovery regression exercises background hotspot restoration while retaining the
Printer snapshot, a dark display and the idle CPU tier. This is mocked regression coverage,
not proof of an uninterrupted physical BLE connection.

The Mac has not detected the Pi USB gadget during this session, and SSH to `192.168.7.1` timed
out. Deployment and real locked-Wi-Fi/Printer continuity smoke await a working data connection.
The last verified device state remains the October 6 manual recovery in plan 064 and
`bridge/docs/current-context.md`. No film or camera upload was used in this session.
