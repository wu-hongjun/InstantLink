# Plan 012: macOS 15 Baseline and Liquid Glass Adoption

**Status:** In Progress (Phase 1 foundation implemented locally; Liquid Glass passes pending)

## Objective

Raise the macOS app baseline from 13.0 to 15.0, then make the UI feel native on macOS 26 by adopting Liquid Glass-friendly structure and visuals with graceful fallback on macOS 15.

This is not a rewrite. The goal is to remove version-floor debt, simplify platform conditionals, and deliberately restyle the existing SwiftUI app around newer macOS design language.

## Why This Plan

- The app historically targeted macOS 13 in `scripts/build-app.sh` and `macos/Info.plist.template`, which kept older platform constraints around.
- The UI already uses custom SwiftUI composition, so a deployment target bump alone will not materially improve appearance.
- A macOS 15 baseline gives us a cleaner codebase without unnecessarily dropping to a macOS 26-only support policy.
- macOS 26 should be treated as a visual enhancement target, not the minimum runtime target.

## Principles

- Keep `macOS 15` as the minimum supported version.
- Build with the latest SDK and add `macOS 26` enhancements behind availability checks where needed.
- Prefer system materials, grouping, spacing, and motion over custom borders and cards.
- Reduce custom chrome before adding more visual effects.
- Preserve workflow clarity first; visual polish must not obscure controls or state.

## Scope

### 1. Deployment Target Cleanup

- Update the Swift build target in `scripts/build-app.sh` from `macosx13.0` to `macosx15.0`.
- Update `LSMinimumSystemVersion` in `macos/Info.plist.template` to `15.0`.
- Remove or simplify macOS 13/14 compatibility branches that become unnecessary after the target bump.

## Phase 1 Foundation Slice (Implemented)

- `scripts/build-app.sh` now compiles the launcher with `-target arm64-apple-macosx15.0`.
- `macos/Info.plist.template` now sets `LSMinimumSystemVersion` to `15.0`.
- Camera mode now has a stable camera-selection control and refreshed camera discovery/session handling.
- Baseline documentation was updated to reflect macOS 15 as the minimum supported version.
- Remaining work is UI modernization and polish phases; no backward-compatibility layer for macOS 13/14 is planned.

### 2. Camera Platform Modernization

- Keep multi-camera selection visible and stable in camera mode.
- Use the newer camera device surface available on macOS 15+ for better built-in, Continuity Camera, and Desk View handling.
- Refresh camera availability dynamically when devices connect or disconnect.
- Revisit camera ordering and naming so the active camera is obvious.

### 3. Main Window Liquid Glass Pass

- Audit `macos/InstantLink/Features/Main/MainView.swift`, `macos/InstantLink/Features/Main/MainPreviewAndQueue.swift`, and `macos/InstantLink/Support/PreviewSupport.swift`.
- Remove remaining redundant borders, opaque cards, and nested chrome.
- Rebuild the connected header and printer-mode action rows around cleaner system grouping.
- Prefer material-backed surfaces only where they separate layers or anchor interaction.

### 4. Camera and Editor Surface Pass

- Audit `macos/InstantLink/Features/Camera/CameraViews.swift` and `macos/InstantLink/Features/Editor/EditorViews.swift`.
- Make the camera action strip and editor sidebar controls feel consistent with the main window.
- Replace remaining control-specific wrappers with shared styles or plain system controls.
- Ensure overlays, crop controls, exposure controls, and defaults popovers read as one coherent system.

### 5. Motion and State Polish

- Add restrained transitions for mode switches, queue reveal/hide, overlay selection, and editor presentation.
- Add hover and pressed-state polish to desktop controls where helpful.
- Ensure animations are fast, interruptible, and do not block print/camera workflows.

## Implementation Order

### Phase 1: Foundation

- Bump the deployment target to macOS 15.
- Land the camera selector/discovery cleanup.
- Remove obsolete availability branches and document the new baseline.

### Phase 2: Visual Structure

- Refactor shared visual primitives in `macos/InstantLink/Support/PreviewSupport.swift`.
- Standardize toolbar/action-row structure across printer mode, camera mode, and editor.
- Reduce chrome density and align spacing rules.

### Phase 3: Liquid Glass Enhancements

- Introduce macOS 26-specific material refinements where they clearly improve the app.
- Tune hover, focus, and transition behavior for a more modern desktop feel.
- Avoid custom effects that compete with system glass.

### Phase 4: QA and Audit

- Verify appearance in `System`, `Light`, and `Dark`.
- Manually test printer mode, camera mode, queue editing, overlays, settings, and update/restart flows.
- Run a focused UI review on both macOS 15 and macOS 26.

## Exit Criteria

- The app builds and runs with a minimum target of macOS 15.
- Camera mode reliably lists and switches among all cameras available to the system.
- The main window, camera mode, and editor no longer rely on redundant card chrome.
- The app feels visually intentional on macOS 26 without breaking on macOS 15.
- No core workflows regress: connect, capture, import, edit, overlay, print, and batch print.

## Non-Goals

- Dropping support to a macOS 26-only minimum.
- Rewriting the app around a new navigation model.
- Large-scale visual experimentation that diverges from system conventions.
