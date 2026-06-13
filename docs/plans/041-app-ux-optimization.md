# 041 — App UX Optimization (multi-phase)

Scope: the macOS **App** (`InstantLink.app`). Bridge UI is out of scope here; it has its own ongoing track (037–040).

## Goals

- Hide developer/diagnostic affordances from the main Settings surface without removing them.
- Reduce visual noise on the most-used screens (main window, editor, camera).
- Establish a small set of UX conventions so future additions land consistently.

## Phase 1 — Settings sheet polish (this commit)

**Concrete changes:**
- Add an `ellipsis.circle` (⋯) Menu button to the Settings sheet header, immediately left of the close X.
- Move "Run LED Test" out of the inline ExperimentalSettingsSection and into a Menu item under an "Experimental" section in the ⋯ menu.
- During the test, the menu item shows progress in its label and is disabled (e.g. "Running LED Test (R)…").
- Drop the R/G/B/W chip strip — it was an inline visual indicator for a feature that no longer lives inline. If users miss it, resurrect as a HUD popover later.
- Delete the now-unused `ExperimentalSettingsSection` and `LedTestChannelChip` structs.
- Remove the preceding `Divider` from the ScrollView so Settings ends cleanly at Printers.

**Out of scope for this phase:**
- Restructuring About / Appearance / Printers layout. They stay as-is.
- Adding new experimental tools to the menu (we keep it lean — one item today).

## Phase 2 — Main window / printing flow (next plan)

**Pre-work needed:** read `MainView.swift` (783 lines) and `MainPreviewAndQueue.swift` (647 lines) end-to-end; map the open → edit → print path; note every conditional banner / status surface (update banners, status messages, bridge discovery, queue strips). Identify the actual friction before designing fixes.

**Likely directions:**
- Consolidate the top-of-window banner stack — currently up to 5 surfaces (Bridge discovery, update error, update progress, update available, status message) can stack. Pick a precedence rule and a max of 1–2 visible at a time.
- Audit the connected/disconnected/printing state matrix for redundant copy.

## Phase 3 — Image editor

**Pre-work:** read `EditorViews.swift` (1364 lines, largest single feature file).

**Likely directions:**
- Audit crop/contain/stretch + rotation + overlays affordances for discoverability and grouping.
- Confirm undo/reset model matches user expectations.

## Phase 4 — Camera capture

**Pre-work:** read `CameraViews.swift` (279 lines, smallest).

**Likely directions:**
- Self-timer (2s / 10s) discoverability.
- Film orientation toggle visibility.
- Framing affordances around `FilmFrameView`.

## Conventions established by this plan

- Developer / diagnostic / experimental affordances live in the Settings ⋯ menu, never inline in the main Settings scroll.
- Banner stacks in the main window respect a single precedence and a max display count (TBD in Phase 2).
- Section names in Settings refer to user-facing nouns (Appearance, Printers, About) — never to internal subsystems.

## Versioning

Each phase that ships a binary change bumps all three `Cargo.toml` files + the App version in `build-app.sh` per CLAUDE.md.
