import CoreImage
import Darwin
import Foundation

@main
struct CurvesLevelsBenchmark {
    static func main() {
        let rounds = 9
        let iterations = 5000
        var checksum = 0
        print("case,round,order,baseline_ns_per_call,optimized_ns_per_call,baseline_cpu_ns_per_call,optimized_cpu_ns_per_call")
        for (name, fixture) in CurvesLevelsFixtures.benchmarkCases() {
            func run(_ optimized: Bool, count: Int) -> (wall: Double, cpu: Double) {
                let startCPU = clock_gettime_nsec_np(CLOCK_THREAD_CPUTIME_ID)
                let start = DispatchTime.now().uptimeNanoseconds
                for _ in 0..<count {
                    let data = optimized
                        ? CurvesLevelsPipeline.curvesData(curves: fixture.curves, levels: fixture.levels)
                        : CurvesLevelsReference.curvesData(curves: fixture.curves, levels: fixture.levels)
                    checksum &+= data.map { $0.count + Int($0[137]) } ?? 1
                }
                let wall = Double(DispatchTime.now().uptimeNanoseconds - start) / Double(count)
                let cpu = Double(clock_gettime_nsec_np(CLOCK_THREAD_CPUTIME_ID) - startCPU) / Double(count)
                return (wall, cpu)
            }
            _ = run(false, count: 1000)
            _ = run(true, count: 1000)
            for round in 0..<rounds {
                let first = round % 2 == 0
                let a = run(!first, count: iterations)
                let b = run(first, count: iterations)
                let baseline = first ? a : b
                let optimized = first ? b : a
                print("\(name),\(round),\(first ? "AB" : "BA"),\(baseline.wall),\(optimized.wall),\(baseline.cpu),\(optimized.cpu)")
            }
        }
        print("checksum=\(checksum)")
    }
}
