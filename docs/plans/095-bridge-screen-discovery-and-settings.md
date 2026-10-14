# Screen-based Printer discovery and grouped Settings

## Observed problem

The physical boot journal confirmed the reported behavior. UI readiness was at 14.854 seconds
after boot, the first discovery found no Printer, and the saved 30-second period delayed retry.
KEY3 at 39.529 seconds woke that wait; fresh status followed at 43.443 seconds. This establishes
an unnecessary awake wait, not a guaranteed radio availability time.

## Screen-based discovery

Following the user's clarification, offline discovery uses a one-second scan window and
one-second target retry period while the screen is visible, including the unlock prompt.
The existing configured search interval applies while dark: 30 seconds by default, with a
five-second scan window. The minimum awake yield is 50 ms; scans/connections are serialized,
so a scan that consumes its whole window or a longer connection attempt can exceed one second.
The C ABI accepts integer-second scan windows, so the selected awake setting is one second.

Screen changes interrupt the wait and recompute its deadline. Locking adopts the dark cadence;
the first unlock press requests a prompt fresh check without completing the three-press unlock.
Repeated requests retain one minimum gap. In-flight work completes without cancellation/replay,
and disconnect events retain their existing serialized cleanup and bounded recovery retries.
Established-link keepalive/status intervals remain separately configured. Policy changes log once,
with screen state, actual scan budget and target interval; unchanged polls do not add INFO noise.

The native provider forwards the new scan budget to the existing FFI API. The diagnostic Bleak
provider also adjusts its internal unavailable-scan pacing, preventing that fallback from retaining
its old longer wait after wake. No configuration fields, payload shape, protocol or native ABI change.
The App's existing `search_interval_s` control maps to the dark discovery period.

## LCD copy and Settings

- Empty-film home and error states explain **“No film is left in the Printer.”** Error recovery
  asks for a new film pack. No-film testing is confined to its explicit Printer option.
- Network has four rows: **FTP**, **Wi-Fi**, **iPhone**, **Connections**.
- FTP holds Camera link, server, user, PIN and credential reset. Wi-Fi holds the Bridge SSID,
  Wi-Fi PIN and joined-network address. iPhone holds pairing and token reset. Connections holds
  Bluetooth and USB status. Destructive confirmations and full credential detail dialogs remain.
- System groups appearance, text size, language and unlock under **Screen**. Shutdown, refresh
  and About stay directly accessible. Child pages return to their parent and remembered cursor.
- First Printer pairing opens FTP; iPhone QR returns to the page that opened it. Physical and
  virtual LCDs retain the same controller/render path. English and Simplified Chinese copy is updated.

## Validation

Focused tests cover screen-based cadence, slow checks without overlap, lock/wake during waits,
coalesced requests, in-flight scan-budget ownership, group navigation, credential dialogs,
destructive confirmation, both languages and all text sizes. Full checks and installed boot,
reconnect and LCD observations will be recorded below. No film or Printer actuator commands.
