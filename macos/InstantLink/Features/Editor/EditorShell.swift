import AppKit
import SwiftUI

/// Photos-style editor entry view. Plan 049 rewrites the layout to mirror the
/// real macOS Photos.app Edit window:
///
///   ┌───────────────────────────────────────────────────────────┐
///   │   zoom slider │       Adjust|Filters|Crop|Annotate (pill) │   info … ♡ ↻ ✨  [ Done ]
///   ├───────────────────────────────────────────────────────────┤
///   │                                                           │
///   │              canvas (HStack lead, near-black)             │   sidebar (~320 pt)
///   │                                                           │
///   └───────────────────────────────────────────────────────────┘
///
/// The v0.1.45 implementation used HSplitView and a full-width tab strip —
/// both replaced here so the editor reads like Photos at a glance.
struct EditorShell: View {
    @EnvironmentObject var viewModel: ViewModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var state = EditorViewState()

    /// Plan 049 PR §sidebar — Photos sidebar is fixed-width, not draggable.
    private let sidebarWidth: CGFloat = 320

    var body: some View {
        VStack(spacing: 0) {
            EditorShellTopBar(
                state: state,
                onDone: { persistSnapshot(); dismiss() },
                onRevert: { state.revert() }
            )
            Divider()
            HStack(spacing: 0) {
                ZStack {
                    // Plan 049: explicit dark canvas background, matching
                    // Photos. The MTKView itself also has a near-black clear
                    // color (defense-in-depth against the v0.1.45 blank-
                    // canvas bug).
                    Color(white: 0.07)
                        .ignoresSafeArea(edges: .bottom)
                    EditorPreview(state: state)
                    if state.activeTab == .crop {
                        CropFrameView(state: state)
                    }
                    if state.eyedropperManager.active != nil {
                        EyedropperOverlay(state: state)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                Divider()

                Group {
                    switch state.activeTab {
                    case .adjust:   AdjustSidebar(state: state)
                    case .filters:  FiltersSidebar(state: state)
                    case .crop:     CropSidebar(state: state)
                    case .annotate: AnnotateSidebar(state: state)
                    }
                }
                .frame(width: sidebarWidth)
                .frame(maxHeight: .infinity)
            }
        }
        .frame(minWidth: 980, minHeight: 640)
        .onAppear {
            if let image = viewModel.selectedImage {
                state.loadSource(image, initialSnapshot: viewModel.currentEditorSnapshot)
            }
        }
        .onChange(of: viewModel.selectedQueueIndex) { _, _ in
            persistSnapshot()
            if let image = viewModel.selectedImage {
                state.loadSource(image, initialSnapshot: viewModel.currentEditorSnapshot)
            }
        }
        .onDisappear {
            persistSnapshot()
        }
    }

    /// Writes the current `EditorSnapshot` back onto the queue item (locked
    /// decision Q3 — plan 048 PR #14). Snapshot is intentionally written only
    /// when the editor closes / the selected item changes so single-edit
    /// inspector mutations aren't billed against the queue diff per keystroke.
    private func persistSnapshot() {
        guard viewModel.selectedImage != nil else { return }
        viewModel.currentEditorSnapshot = state.snapshot()
    }
}
