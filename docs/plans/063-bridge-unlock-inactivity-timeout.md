# 063 — Unlock timeout after the last accepted press

Date: 2026-10-01. Scope: incomplete unlock timeout and live documentation. This corrects the
fixed first-press deadline in plan 062. The same-button rule and control identities remain intact.

## User correction

The unlock prompt should disappear only after **10 seconds without a button press**. Restart
its timer on every accepted press, whether the same button advances the counter or a different
button resets it to one.

## Required behavior

- Unlock still requires three consecutive presses of the same physical button. KEY1 and
  joystick press remain distinct physical controls; repeated identical virtual actions use
  their own remote control identity.
- The first accepted press wakes the prompt at `1 / 3`, starts awake CPU preparation and starts
  the inactivity timer. A second press of that button advances to `2 / 3` and restarts the timer.
  The third consecutive press completes unlocking and cancels the timer.
- A different button resets the count to `1 / 3` and becomes the required button. This accepted
  press also restarts the inactivity timer. The same rule applies to different remote actions
  and switching between physical and remote input sources.
- For example, press KEY1, wait eight seconds, and press KEY2: the prompt remains at `1 / 3`
  for KEY2 and gets a new 10-second window. Its old first-press deadline must not blank it two
  seconds later. Pressing KEY2 twice more completes the sequence; each accepted press before
  completion refreshes the window.
- Holding a physical button creates no additional pressed-edge event. Release/repress produces
  the next press. Rejected remote requests do not restart the timer. FTP, status updates,
  incoming photos and screen polling do not extend the unlock timer.
- If no accepted press arrives for 10 seconds, expire to a dark **locked** display, reset the
  count and retain the latest underlying live state. Idle CPU returns to its lowest supported
  clock. Active image preparation or printing continues with its performance boost.
- Every input used before unlocking completes is consumed. The next input performs its normal
  action. The existing default-on `ui.unlock_requires_three_presses` setting and one-press
  opt-out retain their behavior.

## Timer lifecycle

Replace or reset the pending expiry on each accepted unlock press. A replaced timer must not
later blank the display after a newer press or after successful unlocking. Completing the
sequence, locking again or stopping the UI must clear the pending timeout. The physical and
virtual LCDs continue sharing one controller and render path; no API fields change.

## Validation and hardware acceptance

Final checks passed: **1,251 Bridge tests**, Ruff, touched-file formatting, strict mypy (65
source files), whitespace and strict MkDocs. The normal pre-commit gate passed. No App/iOS
source or API fields changed. Regression coverage includes:

- Same-button advancement refreshes the deadline and the third press cancels it.
- A different button resets the count and refreshes the deadline.
- The replaced first-press timer cannot blank a newer sequence.
- Expiry occurs only after 10 seconds without accepted input and remains locked afterward.
- Remote action changes and physical/remote source changes follow the same inactivity rule.
- Latest-state restoration, first-press CPU readiness, active-work boosts and one-press opt-out
  remain intact; unrelated background activity cannot refresh the unlock timeout.

Clean runtime `0c80d83` was deployed to Pi Zero 2 W / Waveshare ST7789 LCD HAT on Debian 13.2.
Film-free smoke under `ib` exercised real framebuffer/backlight and CPU controls. Both matching
and different-button trials used a six-second gap, then verified that the prompt remained visible
another 4.5 seconds after the second press, beyond the obsolete first-press deadline. With no
new input, the completed dark-frame transition was observed about 10.19 seconds after the latest
press; idle governor/frequency were verified as powersave/600 MHz. A final same-button triple
cancelled expiry, restored the latest screen and used performance/1000 MHz.

The service was restored and remains healthy with `NRestarts=0`, throttling `0x0` and working
hotspot FTP. Hardware details are recorded in `bridge/docs/current-context.md`. GPIO identities
were injected; physical switch press/hold acceptance remains pending, along with camera/Printer
and film checks. This record establishes no new battery runtime claim.
