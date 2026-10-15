import Foundation

/// Bounds UI work independently of URLSession's chunk size. The stream's
/// consumer owns this value; it requires neither a timer nor another task.
struct DownloadProgressReporter {
    static let interval: Duration = .milliseconds(100)

    private let report: @Sendable (Int64) -> Void
    private var lastReport: ContinuousClock.Instant?
    private var pending: Int64?

    init(report: @escaping @Sendable (Int64) -> Void) {
        self.report = report
    }

    mutating func update(_ received: Int64, now: ContinuousClock.Instant = .now) {
        pending = received
        if let lastReport, lastReport.duration(to: now) < Self.interval { return }
        report(received)
        pending = nil
        lastReport = now
    }

    /// Deliver the last written count before leaving the download, including
    /// failures and cancellation. Calling this twice does not duplicate it.
    mutating func finish() {
        guard let pending else { return }
        report(pending)
        self.pending = nil
    }
}
