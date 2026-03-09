# Plan 007: macOS UI/UX Pass 1

**Status:** In Progress

## Goal

Fix the highest-risk workflow and clarity problems in the macOS app before moving on to broader visual polish and animation work.

This pass is intentionally narrow. It does **not** try to solve the full macOS 26 visual system yet. It focuses on the UX traps that can cause data loss, confusion, or failed task completion.

## Scope

### In Scope

1. Make destructive queue actions explicit and safe
2. Protect users from losing an uncommitted camera capture
3. Keep an `Add Photo` affordance visible in file mode
4. Improve multi-print button messaging when printing is not possible
5. Make operational errors persistent and dismissible instead of transient

### Out of Scope

- Glass/material visual redesign
- Hover states and motion polish
- Overlay resize handles and advanced editor ergonomics
- Settings information architecture refactor
- Broader style/token cleanup

## Problems To Fix

### 1. Destructive queue affordance is misleading

The `X` on the main preview reads like “remove current photo” but currently clears the whole queue. In multi-image workflows this is too destructive for the affordance.

### 2. Camera mode can discard work silently

If the user captures a photo and lands in preview, switching back to file mode can drop that photo without a commit/discard decision.

### 3. Add-more flow is too hidden with one photo

Once the queue is collapsed, users with a single imported photo have weak discoverability for how to add more images.

### 4. Multi-print disabled states are unclear

`Print Next 0` is technically correct but poor UX. The user needs a reason such as `No Film` or `No Printable Items`.

### 5. Errors disappear too quickly

Print, camera, and import failures are low-salience transient messages today. Failure states should persist until dismissed.

## Implementation Workstreams

### Workstream A: Queue and file-mode actions

- Change main preview removal behavior to target the current item, not the entire queue
- Reserve full queue clearing for an explicit action if we still want it
- Add a visible `Add Photo` action in the file-mode action row
- Preserve current selection when bulk-adding into a non-empty queue
- Improve multi-print CTA copy for zero-action states

### Workstream B: Camera discard protection

- Detect mode switches away from camera preview when `capturedImage` is uncommitted
- Present a discard/keep-editing decision before leaving camera mode
- Keep existing fast paths unchanged when no captured preview exists

### Workstream C: Persistent banner system

- Replace the transient `statusMessage` pattern with structured banner state
- Keep failures persistent until dismissed
- Allow short-lived success/info banners only where appropriate

## Acceptance Criteria

- Removing from the main preview no longer wipes the queue unexpectedly
- Switching away from camera preview cannot silently lose a captured image
- Users can always discover how to add another file-mode image
- Disabled print actions explain why they are unavailable
- Error states remain visible until the user dismisses them

## Exit Criteria

Pass 1 is complete when all five scope items are shipped, validated by a clean app build, and no new work from Pass 2 or Pass 3 is mixed into the branch.
