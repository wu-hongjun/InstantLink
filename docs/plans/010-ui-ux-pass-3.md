# Plan 010: macOS UI/UX Pass 3

**Status:** Completed (March 2026)

## Goal

Establish the first shared visual foundation for the macOS app so it feels less like a flat utility window and more like a modern macOS app with depth, hierarchy, and polished interaction feedback.

## Scope

### In Scope

1. Shared material-based panel styling for core surfaces
2. Better grouping and hierarchy in the connected header
3. Hover feedback for desktop-first interactive elements
4. Smoother transitions for mode and status changes

### Out of Scope

- Full app-wide visual redesign
- New iconography system
- Custom typography or brand color overhaul
- Complex animation choreography
- Settings IA redesign

## Problems To Fix

- Primary surfaces still rely on flat `controlBackgroundColor` fills and strokes
- The header is dense and visually undifferentiated
- Interactive list and queue items have weak hover affordance
- Mode switches and banner changes still feel abrupt

## Implementation Workstreams

### Workstream A: Shared panel styling

- Introduce a reusable material-backed panel surface
- Apply it to camera preview, main preview, and editor preview containers

### Workstream B: Header hierarchy

- Group related controls into clearer capsules or panel clusters
- Reduce the “single long flat row” feeling

### Workstream C: Hover states

- Add hover affordance to queue thumbnails
- Add hover affordance to overlay rows
- Reveal secondary actions more intentionally

### Workstream D: Motion polish

- Add consistent transitions for file/camera mode swaps
- Add transitions for banners and queue reveal/hide

## Implemented

- Added shared `AppPanelBackground` chrome to the camera, main preview, and editor preview surfaces.
- Grouped the connected header into material capsules with a `ViewThatFits` fallback so narrow windows still collapse to a compact row cleanly.
- Added hover-aware queue thumbnail chrome and stronger overlay row hover/selection feedback without changing drag hit targets.
- Applied top-edge fade/move transitions to update and status banners, plus smoother file/camera preview and action-row swaps.
- Updated secondary surfaces such as inspector cards and editor zoom controls to use lighter material-backed styling instead of flat utility fills.

## Acceptance Criteria

- The main preview/editor/camera surfaces share a stronger visual style
- The header reads as grouped controls rather than one flat strip
- Hovering queue and overlay items gives visible desktop feedback
- State changes feel smoother without harming clarity
