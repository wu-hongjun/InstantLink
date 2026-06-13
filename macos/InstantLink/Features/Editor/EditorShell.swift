import AppKit
import SwiftUI

/// New Photos-style editor entry view. Top tab bar + split canvas / sidebar.
struct EditorShell: View {
    @EnvironmentObject var viewModel: ViewModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var state = EditorViewState()

    var body: some View {
        VStack(spacing: 0) {
            EditorShellToolbar(
                state: state,
                onDone: { dismiss() },
                onRevert: { state.revert() }
            )
            Divider()
            EditorTabBar(active: $state.activeTab)
            Divider()
            HSplitView {
                ZStack {
                    EditorPreview(state: state)
                    if state.activeTab == .crop {
                        CropFrameView(state: state)
                    }
                    if state.eyedropperManager.active != nil {
                        EyedropperOverlay(state: state)
                    }
                }
                .frame(minWidth: 620)
                Group {
                    switch state.activeTab {
                    case .adjust:   AdjustSidebar(state: state)
                    case .filters:  FiltersSidebar(state: state)
                    case .crop:     CropSidebar(state: state)
                    case .annotate: AnnotateSidebar(state: state)
                    }
                }
                .frame(minWidth: 320, idealWidth: 400, maxWidth: 460)
            }
        }
        .frame(minWidth: 980, minHeight: 640)
        .onAppear {
            if let image = viewModel.selectedImage {
                state.loadSource(image)
            }
        }
        .onChange(of: viewModel.selectedQueueIndex) { _, _ in
            if let image = viewModel.selectedImage {
                state.loadSource(image)
            }
        }
    }
}

/// Top tab bar.
private struct EditorTabBar: View {
    @Binding var active: EditorTab

    var body: some View {
        HStack(spacing: 0) {
            ForEach(EditorTab.allCases, id: \.self) { tab in
                Button {
                    active = tab
                } label: {
                    Text(tab.localizedTitle)
                        .font(.callout.weight(active == tab ? .semibold : .regular))
                        .padding(.vertical, 8)
                        .padding(.horizontal, 16)
                        .frame(maxWidth: .infinity)
                        .background(
                            active == tab
                                ? Color.accentColor.opacity(0.15)
                                : Color.clear
                        )
                        .foregroundStyle(active == tab ? Color.accentColor : Color.primary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
    }
}

/// Done / Revert / Undo / Redo toolbar.
private struct EditorShellToolbar: View {
    @ObservedObject var state: EditorViewState
    let onDone: () -> Void
    let onRevert: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button {
                state.undo()
            } label: {
                Label(L("editor_undo"), systemImage: "arrow.uturn.backward")
            }
            .disabled(!state.history.canUndo)

            Button {
                state.redo()
            } label: {
                Label(L("editor_redo"), systemImage: "arrow.uturn.forward")
            }
            .disabled(!state.history.canRedo)

            Spacer()

            Button(L("editor_revert")) {
                onRevert()
            }

            Button(L("editor_done")) {
                onDone()
            }
            .keyboardShortcut(.return, modifiers: [.command])
            .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }
}
