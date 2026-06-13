# 044 — Image Editor Audit (Phase 3 of 041)

Exploration deliverable for Phase 3 of `041-app-ux-optimization`. No code changes — this is the map and proposed direction.

## File: `Features/Editor/EditorViews.swift` (1364 lines)

### Surfaces

- **`ImageEditorView`** (4–53) — sheet shell, 1080×720 min / 1280×820 ideal. Header (title + Done with return shortcut) and an HSplitView: canvas (left, ≥620 pt) | sidebar (right, 360–460 pt).
- **`EditorPreviewView`** (55–96) — canvas with drag/drop, simulated film frame when a Printer is paired.
- **`EditorSidebarView`** (147–304) — scrollable VStack of `AccordionSection`s, all expanded by default:
  1. Fit Mode — segmented Crop / Contain / Stretch + QuickZoomControls
  2. Exposure — single QuickExposureControls
  3. Rotate — Rotate Left / Rotate Right / Flip (3 buttons in one row)
  4. Overlays — 2×3 grid of 5 add buttons + list of existing overlays
  5. "Defaults For New Photos" card-button → opens `NewPhotoDefaultsPopover`
- **`OverlayListRowView`** (432–541) — row in the Overlays list. When selected, expands inline to embed `SelectedOverlayInspectorView`.
- **`SelectedOverlayInspectorView`** (578–1229, 650 lines) — name + layer-order buttons + Lock/Hidden toggles + Duplicate/Delete + three `InspectorSectionCard`s (Position, Appearance, Content). Content card switches on overlay kind (text / qr / timestamp / image / location).

## Findings

**F1. Accordions are decorative, not functional.** All 4 main sections default `expanded: true` and the chevron toggle only collapses transiently — `AccordionSection`'s `@State` is per-instance and isn't persisted. Every fresh open of the editor re-expands everything. The accordion chrome adds a header row + chevron at every section but provides zero space savings in practice. It's a styled section divider with a fake interaction.

**F2. Selected-overlay inspector is buried 5 levels deep.** Hierarchy: Sidebar → `AccordionSection "Overlays"` → `OverlayListRow` (selected) → inline divider → `SelectedOverlayInspectorView` → `InspectorSectionCard` (Position/Appearance/Content). By the time the user gets to a Position slider, there are nested borders/dividers at every level. Hard to scan; even harder to know where you are after scrolling.

**F3. Inline-expanding row pushes layout unexpectedly.** When a row expands into a 600+ pt inspector, sibling overlay rows above it stay put, but the entire Overlays accordion grows. The canvas (left pane in `HSplitView`) is unaffected, but the sidebar height ballooning forces a scroll context that mixes "navigate between sections" and "navigate within inspector" into one ScrollView.

**F4. Tiny sections cost the same chrome as the big one.** Rotate (3 buttons in a single HStack) and Exposure (single `QuickExposureControlsView`) each get a full AccordionSection. Overlays — with a 5-button grid, an N-row list, and an inline 600-pt inspector — also gets one AccordionSection. The visual weight of the "drawer" doesn't scale with content.

**F5. Layer-ordering buttons compete for attention at the top of the inspector.** Send Backward / Bring Forward sit in the inspector header HStack next to the overlay title. They're per-overlay scope but feel global. They could live as hover actions on the row itself (alongside hide/trash), reserving the inspector header for naming and identity.

**F6. Lock affordance asymmetry.** `OverlayListRow` exposes Hide and Delete as hover buttons, but Lock is only inside the inspector (Toggle at line 612). Hidden appears in both places. Either both should be in the row, or both in the inspector — consistency lets users build the right mental model.

**F7. Position uses sliders only.** X/Y/Width/Height are sliders (0.05–0.95 range, displayed as 5–95 %). For precise placement, sliders are imprecise — no nudge, no numeric entry. The drag-on-canvas affordance via `PrintImagePreviewSurface` likely handles coarse positioning better; sliders are redundant for coarse and bad for fine.

**F8. "Defaults For New Photos" is styled like a card.** Custom `CompactGlassSurface` background, chevron-right at the trailing edge, title + description stacked. It's actually a button that opens a popover. The card styling makes it read as "this is an info card you can tap" instead of "tap to open Defaults", which it is.

**F9. No per-section Reset.** `Reset Zoom` and `Reset Crop` strings exist in `en.lproj` but aren't surfaced in the sidebar I read. Users adjust exposure / rotation / position, then want to undo a single tweak without dismissing the editor — no path for that today.

**F10. Done-only commit, no Cancel.** Header has only "Done" (return shortcut). No "Cancel" / "Discard". Whether the editor is effectively auto-saving (changes commit live to the queue) or only on Done is not visible from the structure; if auto-saving, the Done button is just a window close — and the lack of Cancel is fine. If it's commit-on-Done, the missing Cancel is a real gap.

## Proposed direction

Two passes. **Pass A** is mechanical cleanup (low risk, big visual quiet). **Pass B** is a structural change to the inspector placement (higher impact, more invasive).

### Pass A — Sidebar visual quieting

- Replace `AccordionSection` with a flat `SidebarSection` header (icon + title, no chevron, no toggle, no animation). Sections become permanent visual groups, not pretend-collapsible drawers.
- Merge Rotate + Fit Mode → "Transform". Rotate's 3 buttons sit below the Crop/Contain/Stretch picker. Saves one section row.
- Demote "Defaults For New Photos" to a quiet text-link or `.bordered` button at the bottom. The card styling overpromises.
- Add per-section Reset affordances where the strings already exist (Reset Crop, Reset Zoom). Small chevron-arrow icon to the right of the section title, only visible when the section's state has diverged from defaults.

### Pass B — Move SelectedOverlayInspectorView out of the row

Currently the inspector expands *inside* the Overlays list row. Move it to a sibling surface in the sidebar:

```
┌ Sidebar ──────────────┐
│ Transform             │
│ Exposure              │
│ Overlays              │
│  ┌ row ┐ ┌ row ┐      │   ← compact rows (no inline expansion)
│  └─────┘ └─────┘      │
├───────────────────────┤
│ Inspector             │   ← appears when an overlay is selected
│ (Name, Position, ...) │
└───────────────────────┘
```

When no overlay is selected, the inspector pane is empty (or hides). When an overlay is selected, the rows stay compact (just chevron-down to indicate selection), and the inspector appears as a sibling pane *below the sections list* — still in the sidebar's ScrollView, but no longer nested inside Overlays. This collapses the depth from 5 levels to 3 (Sidebar → Inspector → SectionCard).

If the sidebar height is constrained, the Inspector could become a separate Inspector column in the HSplitView (canvas | sections | inspector), but that pushes the editor wider than 1280 pt comfortably.

### Out of scope for this pass

- Replacing Position sliders with numeric inputs (F7) — desirable, but a separate input-affordance pass.
- Reworking `SelectedOverlayInspectorView`'s internal Content section (text / qr / timestamp / image / location). Each kind has its own controls; auditing those individually is its own follow-up.
- Verifying Done-only commit semantics (F10) — needs runtime test, not a structural read.

## Open questions to decide before implementation

1. **Pass A only, or A + B together?** A is safe and visually impactful; B is a real layout change. Doing A first lets us evaluate whether B is still needed.
2. **Are `expanded` flags on `AccordionSection` worth preserving as user-collapsible sections?** If users want to hide Overlays when they're not in use, real collapse + persistence (UserDefaults) would help. If accordions go entirely, that affordance goes with them.
3. **For Reset affordances**: which sections get them in Pass A? (Fit Mode → Reset Crop, Quick Zoom → Reset Zoom are obvious. Rotate → reset to 0°? Exposure → reset to neutral? Overlays → delete all?)

## Next step

Pick a scope (A only / A + B / different cut), then write `045-image-editor-implementation.md` with concrete diffs.
