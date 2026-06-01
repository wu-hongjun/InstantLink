import Foundation

/// One observation of the bridge's wall-clock at a known monotonic instant.
///
/// The Mac signs management requests with ``X-Bridge-Timestamp`` and the
/// bridge enforces a ±30 s future-skew window on it. Plan 040 records a
/// sample of the bridge's own epoch (returned by ``GET /v1/time``) anchored
/// to the host's monotonic clock, so we can synthesize a "current bridge
/// epoch" for any later signing without round-tripping again. The bridge
/// has no RTC and no internet egress in the default headless hotspot mode,
/// so its clock can sit arbitrarily off real wall time — the magnitude of
/// the offset is bounded only by the bridge's actual boot stamp.
struct BridgeServerClockSample: Equatable {
    /// Bridge wall-clock epoch (Unix seconds) at the moment we sampled.
    let serverEpochAtSample: Int
    /// Host monotonic clock reading at the same instant. Monotonic so it
    /// is immune to wall-clock changes on the Mac (e.g. NTP step,
    /// suspend/resume drift, manual time set).
    let monotonicAtSample: TimeInterval

    /// Synthesize the bridge's "current" epoch at ``monotonicNow``.
    ///
    /// The cache holds a single sample point; everything since rides on
    /// the host's monotonic clock. If the bridge clock drifts relative to
    /// the host during the session the next signed call will fail the
    /// skew window, the transport will refresh this sample, and the
    /// retry will succeed — small drift is absorbed without round-trips.
    func currentServerEpoch(monotonicNow: TimeInterval) -> Int {
        let elapsed = monotonicNow - monotonicAtSample
        return serverEpochAtSample + Int(elapsed)
    }
}

/// Per-device clock-offset cache shared by all signed sends in a process.
///
/// Keyed by ``BridgeDevice.deviceID`` so multiple paired bridges, each
/// with their own drift, do not poison one another's offsets. The cache is
/// populated lazily — never on the happy path of the first signed call —
/// and is invalidated when a signed call returns ``timestamp_future`` or
/// ``stale`` so the next attempt re-anchors before retrying.
actor BridgeServerClockCache {
    private var samples: [String: BridgeServerClockSample] = [:]

    /// Return the cached "current" bridge epoch for ``deviceID`` or
    /// ``nil`` if no sample is on file.
    ///
    /// ``monotonicNow`` is injected so callers — including tests —
    /// control the host clock reading and stay independent of
    /// ``ProcessInfo.systemUptime`` side effects.
    func serverEpoch(forDeviceID deviceID: String, monotonicNow: TimeInterval) -> Int? {
        guard let sample = samples[deviceID] else { return nil }
        return sample.currentServerEpoch(monotonicNow: monotonicNow)
    }

    /// Record a fresh observation of the bridge's epoch for ``deviceID``.
    func record(
        deviceID: String,
        serverEpoch: Int,
        monotonicNow: TimeInterval
    ) {
        samples[deviceID] = BridgeServerClockSample(
            serverEpochAtSample: serverEpoch,
            monotonicAtSample: monotonicNow
        )
    }

    /// Drop the cached sample for ``deviceID``.
    ///
    /// Called when a signed request is rejected with ``timestamp_future``
    /// or ``stale`` — the next ``serverEpoch(forDeviceID:monotonicNow:)``
    /// call will return ``nil`` so the transport knows to fetch a fresh
    /// sample before retrying.
    func invalidate(deviceID: String) {
        samples.removeValue(forKey: deviceID)
    }

    /// Drop every cached sample. Used by tests and by code paths that
    /// want to force a clean re-anchor across the whole device set.
    func reset() {
        samples.removeAll()
    }
}

/// Read the host's monotonic clock — the same source used by the
/// transport when signing. Lives at module scope so tests and production
/// code share one definition.
///
/// ``ProcessInfo.systemUptime`` advances strictly forward and ignores
/// wall-clock changes, which is exactly what we need to anchor a server
/// epoch observation against.
func bridgeMonotonicNow() -> TimeInterval {
    ProcessInfo.processInfo.systemUptime
}
