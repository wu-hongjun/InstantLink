# Bridge startup model-query recovery

## Goal

Reduce the startup delay when the Printer does not answer the first ImageSupportInfo query.
Preserve automatic reconnect, model-specific preparation/orientation, authoritative dimensions,
command serialization and failed/cancelled session retirement. Hardware validation uses status
requests and external disconnects only; no film.

## Approach and acceptance

Subagents implement and audit a single retry of this read-only capability request after a
short first response window, within the original ten-second response budget. One command lock
and delivery guard span both writes; terminal failure still retires the uncertain session.
No actuating command is replayed. Model detection retains queried dimensions and validates
known DIS identity conflicts. Ambiguous Link 3 hints fail safely instead of changing orientation.

Independent adversarial review covers late/duplicate replies, partial packets, no response,
write failure, cancellation/disconnect, unrelated commands and model/hint conflicts. Compare
baseline, candidate and installed warm startup, request counts, subsequent periodic freshness,
automatic reconnect at600MHz and logs. Preserve failed attempts and radio variance. Run relevant
local/ARM gates, deploy clean artifacts and restore normal service/remove owned fixtures.

Hardware: Pi Zero 2 W Rev1.0, ST7789 LCD, X306 battery; Debian13.2/Linux6.12.47+rpt-rpi-v8,
Python3.13.5/BlueZ5.82. Instax Link Square INSTAX-52006924. No physical film-quality claim.
