# macOS Photos — Crop / Straighten / Perspective panel research

Target reader: an engineer reimplementing Photos' Crop panel faithfully in a SwiftUI + Core Image macOS app. Scope is the **macOS** Photos app only (Ventura 13 / Sonoma 14 / Sequoia 15). Where the macOS UI diverges from iOS, the macOS behavior wins.

## Sources used

- Apple Support, "Crop and straighten photos and videos on Mac" (current canonical page) — https://support.apple.com/guide/photos/crop-and-straighten-photos-and-videos-pht13f0918f0/mac
- Apple Support, archived macOS 14 version of same page — https://support.apple.com/en-la/guide/photos/pht13f0918f0/9.0/mac/14.0
- Apple Support, "Keyboard shortcuts and gestures in Photos on Mac" — https://support.apple.com/en-in/guide/photos/pht9b4411b24/mac
- Derrick Story, "The Much-Improved Straighten Tool in Photos for Ventura" — https://thedigitalstory.com/2023/01/the-much-improved-straighten-tool-in-photos.html
- MacMost, "10 Tips For Cropping In the Mac Photos App" — https://macmost.com/10-tips-for-cropping-in-the-mac-photos-app.html
- MacMost, "3 Ways To Crop Photos On a Mac" — https://macmost.com/3-ways-to-crop-photos-on-a-mac.html
- MacMost, "Change The Perspective Of A Photo" (older, pre-Ventura) — https://macmost.com/change-the-perspective-of-a-photo.html
- Apple Community, "Grid lines - Photos" — https://discussions.apple.com/thread/254793675
- Apple Community, "photo crop how to turn off aspect ratio lock" — https://discussions.apple.com/thread/254933943
- Apple Community, "Freeform cropping" — https://discussions.apple.com/thread/8379010
- Cult of Mac, "Photos app: How to crop, straighten, unskew photos" — https://www.cultofmac.com/how-to/how-to-crop-straighten-unskew-photos-app
- Apple Developer, Core Image Filter Reference (archive) — https://developer.apple.com/library/archive/documentation/GraphicsImaging/Reference/CoreImageFilterReference/
- Markus Piipari, "Proportionally Cropping Rotated Images (Part 1)" — https://markuspiipari.com/posts/rotated-image-cropping/

## Crop panel anatomy (entry points + layout)

- Open the photo, press **Return** (or click Edit) → click **Crop** in the top toolbar or press **C** to jump straight into the Crop tab. Apple Support page; iDownloadBlog shortcut list.
- Right sidebar contains, top-to-bottom: three sliders (**Straighten**, **Vertical**, **Horizontal**), an **Aspect** popup with **Flip** and **Rotate 90°** icons inline, an **Auto** button (top of the panel, conditional), and at the bottom **Reset** (clears Crop only) plus the global **Done** / **Revert to Original** in the toolbar.
- Layout matters for the reimplementation: Flip lives **inline with the Aspect controls** (not next to Straighten), and Rotate 90° lives next to Flip. The three sliders are stacked at the **top** of the Crop panel. (MacMost "10 Tips"; Apple Support.)

## Aspect ratio chips

### Confirmed preset list (macOS, current)

Apple's support page only enumerates a few examples ("Square", "8:10", "16:9", "Custom"). The complete dropdown — from MacMost "10 Tips" walk-through and the MacMost "3 Ways" tutorial, both of which step through the popup item-by-item — is:

| Label | Notes |
|---|---|
| **Original** | Constrains to the *source* image's native aspect, not the current crop. Apple Support: "constrain the photo to its original aspect ratio." |
| **Freeform** | No constraint; each handle moves independently. Default. |
| **Square** | 1:1. |
| **16:9** | HD video. Apple cites this preset explicitly. |
| **10:8** | Pair with 8:10 via orientation toggle. |
| **7:5** | |
| **4:3** | |
| **5:3** | |
| **3:2** | |
| **Custom…** | Opens a two-field W × H numeric entry. |

Notes / caveats:

- The aspect popup **does not include named print sizes** like "4×6" or "5×7" as labels — those exist as ratios (3:2, 7:5). MacMost walkthroughs and the Watermarkly tutorial don't surface any "4×6"/"5×7" named items in the macOS popup, and Apple's docs only mention generic ratios.
- The presets are stored as a single "tall" entry plus a **Vertical/Horizontal orientation toggle** next to the popup. Selecting **10:8** and clicking the orientation icon flips the constraint to **8:10**, and similarly 4:3 ↔ 3:4, 5:3 ↔ 3:5, 3:2 ↔ 2:3, 7:5 ↔ 5:7, 16:9 ↔ 9:16. MacMost: "you can click the Vertical Icon here or Horizontal to go back."
- **Original** preserves the source image aspect (e.g., a 4032×3024 iPhone JPEG → 4:3 constraint), independent of any crop the user has dragged. Apple Support and MacMost both phrase it as "the original width and height ratio of the photo."
- **Custom** opens two numeric fields (W and H). The fields accept arbitrary positive numbers (including decimals such as 1, 1.414 for A-series paper). The MacMost tutorial shows entering ratios "like 5:7" via the same fields. No published source documents an upper bound; practical limit is the image's pixel size.

iOS Photos diverges (its Aspect sheet adds **9:16** and **8.5:11** as labeled chips). Treat the macOS list above as the source of truth; do not import the iOS labels.

### Reimplementation guidance

- Internally store presets as `(num: Double, den: Double, label: LocalizedStringKey)`.
- Selected aspect determines whether the crop frame's eight handles are linked (constrained pairs of opposite handles) or independent (Freeform).
- Original = `image.extent.width / image.extent.height` resolved at panel open; do not recompute mid-edit.

## Straighten slider

- **Label**: "Straighten". Range: **−45° to +45°**, snapping to 0° at center. The pre-Ventura UI used a vertical "tilt wheel" along the right edge of the image; **Ventura replaced that wheel with a horizontal linear slider in the right sidebar** (Derrick Story, 2023). Sonoma and Sequoia keep the slider model.
- Apple's support page does not publish the numeric range, but the slider visually reads from approximately −45 to +45° (matching iOS), and reverts on **double-click** of the slider thumb. (Apple Support describes "Drag the Straighten, Vertical, and Horizontal sliders"; MacMost shows the slider tooltip reading e.g. "3.5°".)
- **Direct drag-on-image alternative**: "Move the pointer outside of the selection rectangle and click [drag] to adjust the angle of the photo." (Apple Support, verbatim.) Cursor changes to a rotation glyph; the angle indicator overlays the photo. There is **no Lightroom-style level/ruler "click two points on the horizon"** tool.
- **Auto button**: A separate button (top of the Crop panel, **only visible when Photos detects horizontal or vertical edges**) that runs auto-straighten + auto-crop in one shot. "If there are no straight lines in the photo, the Auto button will not be shown." Auto uses Photos' built-in horizon/vertical-line detection (private framework; conceptually equivalent to a Hough transform over edge maps).
- **Snap-to**: Slider snaps to 0° with a soft detent; no documented snap to ±15°/±30°/±45°.

### Math + Core Image mapping

- **Filter**: `CIStraightenFilter` exists and is the natural fit. It takes `inputAngle` in **radians** and "rotates the source image by the specified angle. The image is scaled and cropped so that the rotated image fits the extent of the input image." (Apple Core Image Filter Reference; Microsoft CIStraightenFilter doc.) This is exactly Photos' behavior: rotating expands the image content, and the crop rectangle stays inside the rotated bounds.
- Caveat: there is **no public API to read back the implicit inscribed-rectangle** that CIStraightenFilter uses, so for a faithful reimplementation that needs an exact crop frame, prefer **manual `CIAffineTransform` with a bounds-aware inscribed-rectangle calc** (Markus Piipari has the closed-form for the largest axis-aligned rectangle fitting inside a rotated source). Use angle θ; the inscribed rect is `w' = w·|cosθ| + h·|sinθ|` for the enclosing box, and the inscribed crop dimensions are the standard "largest rect that fits inside rotated rect" formula.
- **Order of operations**: Photos applies **Straighten before Crop**. The crop frame is overlaid on the *rotated* image, not the original. When the user changes Straighten after committing a Crop and re-entering the editor, Photos re-rotates from the original and the crop frame **expands** to encompass the new rotated bounds — multiple straighten passes therefore compound losses unless you Reset first. (Search result quoting Apple Community: "after pressing done and rotating the image with all the sides cropped off, if you try to rotate that image again, it expands and gets cropped even more.")
- **Crop frame auto-shrink**: While straightening, Photos automatically **shrinks the crop rectangle to stay inside the rotated content** (no white triangles in the corners). Implementation: clamp the user-chosen crop rect to the inscribed rectangle of the rotated source on every slider tick.

## Vertical perspective slider

- **Label**: "Vertical" (verbatim in Apple Support: "Drag the Straighten, Vertical, and Horizontal sliders"). Added to macOS in **Ventura (13)** — prior macOS versions only had Straighten. The MacMost "Change The Perspective" article from before Ventura still incorrectly claims "There's no perspective tool in the Photos app" — treat that page as outdated.
- **Purpose**: Keystone correction — "tilt the photo toward you or away from you" (MacMost "10 Tips"); typical use cases are buildings that converge upward and railway lines (Cult of Mac).
- **Range / units**: Apple does not publish a numeric range. Visually the slider mirrors the Straighten slider (centered, with a 0 detent, ~±45 perceptual units). Internally Apple stores a unit-less coefficient that drives a vertical keystone transform; the slider thumb tooltip does **not** print degrees the way Straighten does — it shows a unit-less value or no readout. Recommend exposing a normalized **−1.0 … +1.0** in your reimplementation and mapping to the trapezoid offset.
- **Double-click** on the thumb resets to 0 (consistent with Photos' general slider behavior across the Adjust tab).

## Horizontal perspective slider

- **Label**: "Horizontal". Same Ventura+ caveat as Vertical.
- **Purpose**: Correct objects that tilt left/right when the camera was rotated around its vertical axis — Cult of Mac names "paintings on walls" as the canonical use case.
- **Range / units**: Same UI shape as Vertical — centered slider, double-click resets, no documented numeric tooltip.

### Perspective math + Core Image mapping

Photos' vertical/horizontal sliders are **keystone (trapezoid) transforms**, not affine shears:

- Vertical positive ⇒ widen the top edge or narrow the bottom edge (depending on sign convention) → makes a forward-leaning building stand upright.
- Horizontal positive ⇒ widen one vertical edge, narrow the other → corrects a painting that's tilted around the vertical axis.

Core Image options:

- **`CIPerspectiveTransform`** takes four corner points (`inputTopLeft`, `inputTopRight`, `inputBottomLeft`, `inputBottomRight`) and performs an arbitrary homography. Use this if you want one filter to express Straighten + Vertical + Horizontal as a single 3×3 projective matrix.
- **`CIPerspectiveCorrection`** takes the same four input corners but interprets them as the **source quadrilateral** to be straightened back to a rectangle — the inverse problem. Less convenient here.
- **`CIPerspectiveTransformWithExtent`** is the bounds-preserving variant.
- Available since OS X 10.10 / iOS 8 (Apple Core Image Filter Reference).

Suggested formulation for a SwiftUI reimplementation:

1. Start with the source image extent `R = (0,0,w,h)`.
2. Apply Straighten by rotating the four corners around the center by θ.
3. Apply Vertical perspective by shifting top edge inward (or outward) by `dy_v · h` for some normalized slider value `dy_v ∈ [−0.3, +0.3]`.
4. Apply Horizontal perspective analogously by shifting one vertical edge.
5. Feed the four mutated corners into `CIPerspectiveTransform`.
6. Compute the largest axis-aligned inscribed rectangle inside that quadrilateral and clamp the user's crop frame to it (so the editor never shows blank corners).
7. Final pipeline: `CIPerspectiveTransform → CICrop` (or `cropped(to:)` on the CIImage).

This matches what Photos does on screen — you see the whole warped image inside the editor with the crop rectangle drawn over it, and the area **outside the crop rectangle is dimmed** (not hidden). (MacMost screenshots; Apple Support description of cropping overlay.)

## Flip horizontal / Flip vertical

- **Location**: Inline with the Aspect popup and the Rotate-90° button, in the Crop panel sidebar. Not at the top of the panel; not next to the sliders.
- **Behavior**: A single **Flip** button. Plain click = horizontal flip. **Option-click** = vertical flip. (Verbatim Apple Support: "Click Flip to flip the image horizontally. Option-click to flip the image vertically.")
- **Keyboard shortcut**: Photos exposes ⌘R for rotate counterclockwise (Image menu); there is **no documented dedicated keyboard shortcut for Flip** in the published shortcut list (idownloadblog / Apple Support keyboard reference). For a reimplementation, expose Shift+⌘H (horizontal) and Shift+⌘V (vertical) as a thoughtful addition.
- **Rotate 90°** sits adjacent. Click = 90° CCW (per Apple Support image-menu shortcut), Option-click = 90° CW.

### Core Image mapping

- Horizontal flip: `CIAffineTransform` with `CGAffineTransform(scaleX: -1, y: 1)` followed by a translation `tx = width` to keep origin at 0,0. Equivalent: `image.transformed(by: .init(scaleX: -1, y: 1).translatedBy(x: -width, y: 0))`.
- Vertical flip: same with `scaleY: -1` and `ty = height`.
- 90° rotation: `CGAffineTransform(rotationAngle: .pi/2)` plus translation, or use `CIAffineTransform`.

## Grid overlay

- **Style**: 3×3 rule-of-thirds grid (two horizontal + two vertical lines dividing the crop rectangle into thirds). MacMost: "The Rule of Thirds grid divides your frame to help position important parts of your photo at the intersections."
- **Visibility**: **Transient**, not persistent. It appears while the user is actively **dragging** a corner/edge handle or holding the mouse down on the crop rectangle, and fades after a moment of inactivity. There is no preference to keep it visible, no toggle for other grid patterns. Apple Community thread "Grid lines - Photos" confirms: "the grid is only shown in Edit Mode, while you are using the Crop tool... while you are holding down on the Trackpad or while you are resizing the photo. It cannot be shown continually."
- **No other overlays**: No golden ratio, no golden spiral, no diagonals, no triangle — unlike Lightroom or Pixelmator Pro. A faithful reimplementation can ship only the 3×3 grid.

## Crop frame

- **Eight handles**: Four corners + four edge midpoints. Corner drag respects the current aspect constraint (Freeform leaves them independent). Edge drag in a constrained aspect resizes proportionally; in Freeform it moves only that edge.
- **Outside-crop dimming**: Photos dims (does not fully hide) the area outside the crop rectangle — you still see the rotated/warped image full-bleed in the editor canvas, with the cropped region at full brightness. This matters for the reimplementation: render the whole transformed image, overlay a darkened rectangle with the crop window punched out.
- **Aspect lock interaction with handles**: When an aspect ratio (other than Freeform) is active, all eight handles maintain the lock; dragging an edge midpoint scales the crop in both dimensions proportionally about the opposite edge.
- **Behavior on Straighten / Perspective change**: The frame auto-shrinks (clamps) to stay inside the transformed content. When the user re-enters Crop after committing one round, the previously-stored straighten + crop are restored as the starting state.
- **Behavior on aspect change mid-edit**: Switching from Freeform to a fixed aspect snaps the existing crop rectangle to the nearest rectangle of that aspect, centered on the current crop center.

## Reset / Auto / Done semantics

- **Reset** in the Crop panel clears only Crop + Straighten + Vertical + Horizontal + Flip. It does not touch Adjust-tab edits (Light, Color, etc.).
- **Auto** = simultaneous auto-straighten + auto-crop. Photos picks an angle, an aspect (often Original), and a frame; the user can then tweak any of them. Only appears when edge detection succeeds.
- **Revert to Original** (toolbar) destroys *all* edits, not just Crop.
- **Done** commits and exits Edit mode. Re-entering Edit + Crop restores the same slider positions and crop rectangle (edits are non-destructive in the Photos library — the original pixels are kept).

## Order of operations (canonical pipeline)

In Photos:

1. Apply **rotation 90°** (multiple of 90, lossless).
2. Apply **Flip** (horizontal/vertical, lossless).
3. Apply **Straighten** (rotation by θ ∈ [−45°, +45°]) around image center.
4. Apply **Vertical** keystone.
5. Apply **Horizontal** keystone.
6. Apply **Crop** rectangle on the warped result.

For Core Image, collapse 3-5 into a single `CIPerspectiveTransform` (one homography), then `CICrop`. Steps 1-2 are pre-composed as an affine. This minimizes resampling passes.

## Suggested Core Image filter map (summary)

| Photos control | Recommended Core Image |
|---|---|
| Rotate 90° CCW/CW | `CIAffineTransform` with `.init(rotationAngle: ±π/2)` |
| Flip H / Flip V | `CIAffineTransform` with `scale(-1, 1)` or `scale(1, -1)` |
| Straighten (θ in radians) | `CIStraightenFilter(inputAngle: θ)` for quick wins; or roll into the `CIPerspectiveTransform` matrix for a single resample |
| Vertical perspective | `CIPerspectiveTransform` with `inputTopLeft.x += dx`, `inputTopRight.x -= dx` (or invert sign for bottom edge) |
| Horizontal perspective | `CIPerspectiveTransform` with `inputTopRight.y += dy`, `inputBottomRight.y -= dy` (or invert sign for left edge) |
| Crop rectangle | `image.cropped(to: cropRect)` after the transform |
| Auto-straighten | `VNDetectHorizonRequest` (Vision framework) for angle; Vision rectangle detection for auto-crop bounds |

For a single-resample pipeline, compute the composite 3×3 projective matrix yourself and feed the four corners to `CIPerspectiveTransform`. Reserve `CIStraightenFilter` for cases where you just want rotation + auto-inscribed-crop without explicit math.

## Open uncertainties

- **Exact numeric range** of the Vertical and Horizontal sliders. Apple does not publish it, and the Photos UI does not show a tooltip with units. The Straighten slider is widely reported as ±45° (matching iOS), but the perspective sliders' internal scale is unconfirmed in any public source.
- **Whether the Aspect popup includes "9:16" as a named portrait preset on macOS Sequoia.** iOS Photos exposes 9:16 directly; macOS sources I checked enumerate the popup as Original/Freeform/Square/16:9/10:8/7:5/4:3/5:3/3:2/Custom with a Vertical/Horizontal toggle, which yields 9:16 implicitly. Worth confirming hands-on on a live Sequoia install.
- **Whether Custom accepts decimal entries** like `1 : 1.414` (A-series paper) or restricts to integers. MacMost shows whole-number examples only; no source documents the validation rules.
- **Auto-straighten algorithm**: Photos almost certainly uses Vision's horizon/edge detection internally, but Apple has never confirmed the implementation; the only observable fact is that Auto is **suppressed when no straight edges are detected**.
- **Keyboard shortcut for Flip**: not in the published Photos shortcut list. Apple users have to click the Flip icon; there may be an undocumented shortcut.
- **CIStraightenFilter vs. custom rotation**: `CIStraightenFilter` is documented but does not expose the inscribed crop rectangle. For a pixel-faithful Photos clone, the safe choice is to compute the inscribed rectangle yourself rather than relying on the filter's internal scale-and-crop heuristic.
