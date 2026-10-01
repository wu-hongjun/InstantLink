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

Validation is provisional at this record's creation. Existing first-press-deadline tests and
previous hardware smoke evidence do not verify the new inactivity behavior. Required local
regressions are:

- Same-button advancement refreshes the deadline and the third press cancels it.
- A different button resets the count and refreshes the deadline.
- The replaced first-press timer cannot blank a newer sequence.
- Expiry occurs only after 10 seconds without accepted input and remains locked afterward.
- Remote action changes and physical/remote source changes follow the same inactivity rule.
- Latest-state restoration, first-press CPU readiness, active-work boosts and one-press opt-out
  remain intact; unrelated background activity cannot refresh the unlock timeout.

On Raspberry Pi Zero 2 W / Waveshare LCD HAT, verify a press near the old deadline gives a full
new 10-second window, both with the same button and a different button. Then leave the prompt
untouched and verify it darkens while staying locked, with idle CPU at the lowest supported
clock. Verify normal unlocking cancels the pending expiry and restores the latest interface.

Record final automated checks, deployment and hardware evidence in
`bridge/docs/current-context.md`. This provisional record establishes no new hardware acceptance
or battery runtime claim.
