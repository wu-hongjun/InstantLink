# 055 — Bridge Print and Sync modes

## Decision

The Bridge exposes two mutually exclusive delivery modes:

- **Print** sends received camera photos to the selected Printer.
- **Sync** stores received camera photos for the iOS app and never starts a print.

Simultaneous `both` delivery is no longer a user-facing mode. Existing configuration files that
contain `destination = "both"` remain readable and migrate to Print mode in memory, which is the
safer default for an appliance that may already receive camera uploads automatically.

## Interaction

KEY2 switches modes directly from normal home/status surfaces:

- Print mode shows `KEY2 Sync`.
- Sync mode shows `KEY2 Print`.

The switch is persisted immediately, starts or stops the sync service through the existing runtime
configuration callback, and refreshes the home surface. Settings keeps a two-choice `Mode` picker
as the slower, discoverable path. KEY3 remains contextual: Printer/network actions in Print mode,
and the iPhone pairing QR in Sync mode.

## Verification

- Config parsing migrates legacy `both` to `print` and rejects unknown values.
- Controller tests cover home switching in both directions, persistence, callback notification,
  status-poll cancellation, and first-boot access to Sync mode.
- Render tests cover KEY2 labels in Print and Sync modes.
- App, FTP, status-indicator, settings, and manager tests cover the two-mode contract.
- Affected files pass Ruff format; full Ruff lint, strict mypy, and the full Bridge pytest suite
  pass.
