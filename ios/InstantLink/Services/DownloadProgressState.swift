import os

/// One download attempt's bridge from synchronous progress callbacks to UI
/// tasks. Reading the latest value prevents queued tasks from applying older
/// counts; invalidation prevents them from updating a subsequent attempt.
final class DownloadProgressState: Sendable {
    private struct State {
        var received: Int64
        var active = true
    }

    private let state: OSAllocatedUnfairLock<State>

    init(received: Int64) {
        state = OSAllocatedUnfairLock(initialState: State(received: received))
    }

    var latestReceived: Int64 { state.withLock { $0.received } }

    var currentIfActive: Int64? {
        state.withLock { $0.active ? $0.received : nil }
    }

    func update(_ received: Int64) {
        state.withLock {
            guard $0.active else { return }
            $0.received = received
        }
    }

    func invalidate() {
        state.withLock { $0.active = false }
    }
}
