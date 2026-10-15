import Foundation
import os

/// Replays chunk arrival timestamps without sleeping. Compiled with the real
/// production reporter; counts callback invocations, not network throughput.
@main
enum ProgressBenchmark {
    static func main() throws {
        let chunkCount = 1_600
        let chunkBytes: Int64 = 65_536
        let start = ContinuousClock.now
        var rows: [[String: Any]] = []
        for spacing in [1, 10, 200] {
            let reports = OSAllocatedUnfairLock(initialState: [Int64]())
            var reporter = DownloadProgressReporter { received in
                reports.withLock { $0.append(received) }
            }
            reporter.update(0, now: start)
            for i in 0..<chunkCount {
                reporter.update(
                    Int64(i + 1) * chunkBytes,
                    now: start.advanced(by: .milliseconds((i + 1) * spacing))
                )
            }
            reporter.finish()
            let values = reports.withLock { $0 }
            precondition(values.first == 0)
            precondition(values.last == Int64(chunkCount) * chunkBytes)
            precondition(values == values.sorted())
            rows.append([
                "chunk_bytes": chunkBytes,
                "chunk_count": chunkCount,
                "simulated_chunk_spacing_ms": spacing,
                "baseline_callbacks": chunkCount,
                "optimized_callbacks": values.count,
                "callback_reduction_percent": 100 * (1 - Double(values.count) / Double(chunkCount)),
                "final_bytes": values.last!,
            ])
        }
        let data = try JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
}
