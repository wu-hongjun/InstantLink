import Foundation

/// Snapshot pushed onto the editor's undo / redo stack.
///
/// Codable shape includes `filterID` and `overlays` placeholders so persisted
/// snapshots written by PR #1 stay compatible once PR #14 ports overlays and
/// PR #15 wires the filter rail. Both default-empty; absent keys decode to
/// neutral via the synthesized Codable.
struct EditorSnapshot: Equatable, Codable {
    var adjustments: AdjustmentState = .neutral
    var crop: CropState = .neutral
    var filterID: String? = nil
    var overlays: [OverlayItem] = []

    static let neutral = EditorSnapshot()
}

/// Stack of full `EditorSnapshot`s with cursor-based undo / redo and a
/// 200 ms debounce so slider drags collapse into one commit on release.
@MainActor
final class AdjustmentHistory {
    private var stack: [EditorSnapshot] = []
    private var cursor: Int = -1
    private let limit: Int
    private let debounceInterval: TimeInterval
    private var pending: EditorSnapshot?
    private var debounceTask: Task<Void, Never>?

    init(limit: Int = 64, debounceMs: Int = 200) {
        self.limit = limit
        self.debounceInterval = TimeInterval(debounceMs) / 1000.0
    }

    var canUndo: Bool { cursor > 0 }
    var canRedo: Bool { cursor >= 0 && cursor < stack.count - 1 }

    /// Push a snapshot immediately (used on drag-end / discrete actions).
    func commit(_ snap: EditorSnapshot) {
        cancelDebounce()
        appendCommit(snap)
    }

    /// Coalesce snapshots during a continuous drag.
    func commitDebounced(_ snap: EditorSnapshot) {
        pending = snap
        debounceTask?.cancel()
        let interval = debounceInterval
        debounceTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
            await MainActor.run {
                guard let self, !Task.isCancelled, let pending = self.pending else { return }
                self.pending = nil
                self.appendCommit(pending)
            }
        }
    }

    func undo() -> EditorSnapshot? {
        cancelDebounce()
        guard cursor > 0 else { return nil }
        cursor -= 1
        return stack[cursor]
    }

    func redo() -> EditorSnapshot? {
        cancelDebounce()
        guard cursor >= 0, cursor < stack.count - 1 else { return nil }
        cursor += 1
        return stack[cursor]
    }

    func reset(to snap: EditorSnapshot) {
        cancelDebounce()
        stack = [snap]
        cursor = 0
    }

    private func appendCommit(_ snap: EditorSnapshot) {
        if cursor >= 0, cursor < stack.count, stack[cursor] == snap {
            return
        }
        if cursor < stack.count - 1 {
            stack.removeSubrange((cursor + 1)...)
        }
        stack.append(snap)
        if stack.count > limit {
            stack.removeFirst(stack.count - limit)
        }
        cursor = stack.count - 1
    }

    private func cancelDebounce() {
        debounceTask?.cancel()
        debounceTask = nil
        pending = nil
    }
}
