# Bridge live runtime acceptance

Deploy plan075, review complete available service/kernel journals, and validate installed
lock/unlock, printing and automatic recovery on Pi Zero2W / ST7789 / X306 / Instax Square.

## Live finding: inactive BlueZ records

The fresh boot retains the saved Printer's name, UUIDs and bond, but Connected=false and no
RSSI property. Native discovery accepts the cached name immediately and attempts connection:
30-second reply timeout followed by In Progress. Cancelling a genuinely long call during
deployment hit the old runtime's five-second cleanup deadline. Plan075's completed-error
correction does not claim to fix a still-running native connection attempt.

On Linux, exclude a candidate with neither RSSI nor a confirmed connected link. Keep already
connected devices usable without advertisements. Bound connected-state queries by one shared
250ms budget per collection, rather than paying a new timeout for every cached Printer.
Other platforms and image/packet/pacing behavior stay unchanged. RSSI is scan evidence, not
a guarantee of current liveness; stale RSSI after prior discovery remains a limitation.

## Hardware validation

Use a temporary root/ib-only Unix socket observer around the installed runtime. Send abstract
button events through the same action queue as GPIO; use the actual LCD/framebuffer, CPU helper,
FTP, networking, FFI and saved settings. Record this automation boundary: it does not test the
electrical switch contacts. Restore the normal service afterward and remove the observer.

Check same-button unlock including different GPIO identities sharing Select, blank-frame
regression, ten-second abandonment and CPU return to600MHz. Upload DSC02825.jpeg once through
production FTP for one authorized physical print; no uncertain retry. Check film/history and
captured JPEG bytes, expected orientation, ACKs, CPU boost and terminal UI state. Recover a
controlled disconnected link automatically while locked and retain service/FTP/network health.
Separate deployment/test restarts from spontaneous failures and historical faults.

## Live finding: startup bond recovery

Repeated service-discovery failures after deployment exposed a missed online→offline edge:
BlueZ retains the Printer bond across Bridge restarts, while an Instax power-off can clear
its key. Check the existing `reset_bond_if_disconnected` guard once when a status polling
generation starts, after backend readiness and before its first fetch. Connected identities
are preserved; selection is retained. Superseded generations do not fetch after the check,
and cancellation propagates through owned cleanup. Three regression cases fail before the
fix. This startup action is logged at INFO with its actual reason.

The user-selected validation photo changed to DSC02832.jpeg because the earlier source was
no longer present. Preserve the original and saved processing settings.
