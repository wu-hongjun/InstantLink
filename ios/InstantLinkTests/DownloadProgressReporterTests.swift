import XCTest
import os
@testable import InstantLink

final class DownloadProgressReporterTests: XCTestCase {
    func testFirstReportIsImmediateAndIntermediateReportsAreBounded() {
        let values = OSAllocatedUnfairLock(initialState: [Int64]())
        var reporter = DownloadProgressReporter { received in
            values.withLock { $0.append(received) }
        }
        let start = ContinuousClock.now
        reporter.update(64, now: start)
        reporter.update(128, now: start.advanced(by: .milliseconds(99)))
        XCTAssertEqual(values.withLock { $0 }, [64])
        reporter.update(192, now: start.advanced(by: .milliseconds(100)))
        XCTAssertEqual(values.withLock { $0 }, [64, 192])
        reporter.finish()
        XCTAssertEqual(values.withLock { $0 }, [64, 192])
    }

    func testFinishFlushesLatestValueExactlyOnce() {
        let values = OSAllocatedUnfairLock(initialState: [Int64]())
        var reporter = DownloadProgressReporter { received in
            values.withLock { $0.append(received) }
        }
        let start = ContinuousClock.now
        reporter.update(80_000, now: start)
        reporter.update(90_000, now: start.advanced(by: .milliseconds(1)))
        reporter.update(100_000, now: start.advanced(by: .milliseconds(2)))
        reporter.finish()
        reporter.finish()
        XCTAssertEqual(values.withLock { $0 }, [80_000, 100_000])
    }

    func testSlowChunksRemainFreshAndEmptyDownloadDoesNotInventBytes() {
        let values = OSAllocatedUnfairLock(initialState: [Int64]())
        var reporter = DownloadProgressReporter { received in
            values.withLock { $0.append(received) }
        }
        reporter.finish()
        XCTAssertTrue(values.withLock { $0.isEmpty })
        let start = ContinuousClock.now
        for i in 1...3 {
            reporter.update(Int64(i), now: start.advanced(by: .milliseconds(i * 200)))
        }
        reporter.finish()
        XCTAssertEqual(values.withLock { $0 }, [1, 2, 3])
    }

    func testUnwindingCancellationFlushesLastWrittenBytes() {
        let values = OSAllocatedUnfairLock(initialState: [Int64]())
        func interruptedDownload() throws {
            var reporter = DownloadProgressReporter { received in
                values.withLock { $0.append(received) }
            }
            defer { reporter.finish() }
            let start = ContinuousClock.now
            reporter.update(64, now: start)
            reporter.update(128, now: start.advanced(by: .milliseconds(1)))
            throw CancellationError()
        }
        XCTAssertThrowsError(try interruptedDownload()) { XCTAssertTrue($0 is CancellationError) }
        XCTAssertEqual(values.withLock { $0 }, [64, 128])
    }
}
