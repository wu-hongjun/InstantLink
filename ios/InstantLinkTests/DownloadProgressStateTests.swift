import XCTest
@testable import InstantLink

final class DownloadProgressStateTests: XCTestCase {
    func testFailureBeforeResponsePreservesPreviouslyDisplayedPartial() {
        let progress = DownloadProgressState(received: 80_000)
        // Header failure produces no progress callback. The VM uses this
        // count when transitioning to failed or waiting.
        XCTAssertEqual(progress.latestReceived, 80_000)
        progress.invalidate()
        XCTAssertNil(progress.currentIfActive)
        XCTAssertEqual(progress.latestReceived, 80_000)
    }

    func testAcceptedRestartCanResetPreviousPartialToZero() {
        let progress = DownloadProgressState(received: 80_000)
        progress.update(0)
        XCTAssertEqual(progress.currentIfActive, 0)
        progress.update(64_000)
        XCTAssertEqual(progress.currentIfActive, 64_000)
    }

    func testQueuedUpdatesReadLatestResumedCount() {
        let progress = DownloadProgressState(received: 80_000)
        progress.update(80_000)
        progress.update(144_000)
        progress.update(200_000)
        // Both an older queued UI task and the latest one read the same
        // authoritative count, regardless of their scheduling order.
        XCTAssertEqual(progress.currentIfActive, 200_000)
        XCTAssertEqual(progress.currentIfActive, 200_000)
    }

    func testCompletedOrForgottenAttemptCannotUpdateRetry() {
        let old = DownloadProgressState(received: 80_000)
        old.invalidate()
        let retry = DownloadProgressState(received: old.latestReceived)
        retry.update(0)
        old.update(100_000)
        XCTAssertNil(old.currentIfActive)
        XCTAssertEqual(old.latestReceived, 80_000)
        XCTAssertEqual(retry.currentIfActive, 0)
    }
}
