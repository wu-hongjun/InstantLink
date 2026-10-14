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

Clean `92c57e4` installed. Final source gate passed **2,481 Bridge tests** with eight expected
Mac GPIO warnings, **602 focused checks**, Ruff lint/format of 159 files, strict mypy of 68 source
files and strict MkDocs. Existing navigation tests were updated for actual submenu routes; the
full run caught one remaining old unlock-toggle path, which was corrected before the final gate.
The full suite also covers native cancellation, stale watches and lock/unlock behavior.

A controlled on-Pi production controller/provider/Rust FFI probe used an unmatched synthetic
Printer and NullDisplay. Normal Bridge was stopped for this probe and restored by an EXIT trap.
Real awake gaps were **1.378–1.392 seconds**, including one-second scans and driver overhead.
Dark start period was **30.002 seconds**, with a five-second scan at 600 MHz. The first unlock
press woke the next scan in **40.8 ms**; CPU reached 1 GHz before that press returned. The native
scan can begin during CPU warm-up while the three-press prompt remains visible. Triple unlock
completed; no physical button, actual Printer connection, bond change, image or film operation.

Normal service restored at PID 1293 with zero automatic restarts. Its policy records confirm
`screen=on scan_window_s=1 interval_s=1.0`, then
`screen=off scan_window_s=5 interval_s=30.0`. Installed source hashes match the checkout; FFI
remains `b91cf3fdd128b314cbcb952037e686514023371fe960a1c7d8ed4562d9ea1175`. FTP 220/200,
600 MHz/powersave/backlight GPIO 24 low and no runtime warnings verified. The Printer remained
offline; normal installed automatic boot-to-connected validation is **pending availability**.

[LCD previews and measurements](../assets/bridge-audit-095/README.md) use synthetic credentials.
Previews were visually reviewed with Mac font fallbacks, including English/Chinese large text.
Short labels avoid the previous clipped unlock row and exposed token terminology. No hardware
panel scanout or physical button contact claim. Pi Zero 2 W/ST7789/X306, Debian 13.2/Linux
6.12.47/BlueZ 5.82 and Link Square INSTAX-52006924; native firmware, camera transfer and image
rules are unchanged by this Python/UI update.
