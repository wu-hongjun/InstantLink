//! High-level API for scanning, connecting, and printing with Instax printers.

use std::path::Path;
use std::time::Duration;

// Brings the btleplug `Peripheral` trait methods (e.g. `disconnect`) into scope on the
// `btleplug::platform::Peripheral` handles returned by `transport::collect_instax_peripherals`.
use btleplug::api::Peripheral as _;

use crate::connect_progress::{ConnectProgressCallback, ConnectStage, emit_connect_progress};
use crate::device::{BlePrinterDevice, PrinterDevice, PrinterStatus};
use crate::error::{PrinterError, Result};
use crate::image::FitMode;
use crate::transport::{self, BleTransport, DEFAULT_SCAN_DURATION};

/// Poll cadence while waiting for the target printer to appear during the active scan window.
/// A named connect proceeds as soon as the printer is uniquely matched instead of waiting out the
/// full scan duration, trimming several seconds off every (re)connect. See `docs/plans/031` Phase 1.
const DISCOVERY_POLL_INTERVAL: Duration = Duration::from_millis(400);

/// Budget for the fast-path connect attempt that runs with the active scan stopped.
/// A healthy BlueZ direct connect to a bonded printer completes in ~0.3 s (including GATT/status
/// setup); the slow active-scan fallback path takes ~11 s under controller contention. 3 s gives
/// the fast path plenty of headroom while keeping the slow path well-separated. See
/// `docs/plans/031` Phase 1.
/// 5 s gives comfortable headroom over a slow-but-healthy connect: a single connect cycle on
/// BlueZ can include `peripheral.connect()` plus the up-to-2 s `CHARACTERISTIC_RESOLVE_TIMEOUT`
/// poll plus a subscribe retry, so the worst-case healthy total is ~3.5 s. 5 s keeps the fast
/// path from spuriously falling back, while staying well below the ~11 s slow path.
const FAST_PATH_TIMEOUT_S: u64 = 5;
const FAST_PATH_TIMEOUT: Duration = Duration::from_secs(FAST_PATH_TIMEOUT_S);

/// Substrings observed in btleplug/BlueZ error strings when BlueZ wedges its connection state
/// machine (D-Bus `Connect()` returns `In Progress` immediately, or never replies until the
/// ~25 s D-Bus reply timeout). The wedge is only known to clear when a live active scan is
/// running during the next connect attempt, so these signatures gate the active-scan fallback.
/// This is a pragmatic substring match — the underlying error strings are stable enough in
/// practice — rather than a typed error variant. See `docs/plans/031` Phase 1.
const WEDGE_SIGNATURE_IN_PROGRESS: &str = "In Progress";
const WEDGE_SIGNATURE_DBUS_TIMEOUT: &str = "Timeout waiting for reply";

/// Returns true if `error` matches the BlueZ "connection in progress" wedge signature, in which
/// case the only known recovery is to retry the connect with an active scan running.
fn is_wedge_signature(error: &PrinterError) -> bool {
    let message = error.to_string();
    message.contains(WEDGE_SIGNATURE_IN_PROGRESS) || message.contains(WEDGE_SIGNATURE_DBUS_TIMEOUT)
}

/// Information about a discovered printer (before connecting).
#[derive(Debug, Clone)]
pub struct DiscoveredPrinter {
    /// BLE device name.
    pub name: String,
    /// Internal index for connection.
    _index: usize,
}

impl std::fmt::Display for DiscoveredPrinter {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name)
    }
}

/// Scan for nearby Instax printers.
pub async fn scan(duration: Option<Duration>) -> Result<Vec<DiscoveredPrinter>> {
    let adapter = transport::get_adapter().await?;
    let duration = duration.unwrap_or(DEFAULT_SCAN_DURATION);
    let results = transport::scan(&adapter, duration).await?;

    Ok(results
        .into_iter()
        .enumerate()
        .map(|(i, (_, name))| DiscoveredPrinter { name, _index: i })
        .collect())
}

/// Connect to a specific printer by name.
pub async fn connect(
    device_name: &str,
    duration: Option<Duration>,
) -> Result<Box<dyn PrinterDevice>> {
    connect_internal(device_name, duration, None, false)
        .await
        .map(|(device, _)| device)
}

/// Connect to a specific printer by name and emit progress stages.
pub async fn connect_with_progress(
    device_name: &str,
    duration: Option<Duration>,
    progress: Option<&ConnectProgressCallback>,
) -> Result<Box<dyn PrinterDevice>> {
    connect_with_progress_and_status(device_name, duration, progress)
        .await
        .map(|(device, _)| device)
}

/// Connect with progress and return the freshly queried initial status from that same device.
///
/// The status is an operation result, not a cache: later calls to `PrinterDevice::status` still
/// query the Printer. Status failure tears down the new device and does not report Connected.
pub async fn connect_with_progress_and_status(
    device_name: &str,
    duration: Option<Duration>,
    progress: Option<&ConnectProgressCallback>,
) -> Result<(Box<dyn PrinterDevice>, PrinterStatus)> {
    let (device, status) = connect_internal(device_name, duration, progress, true).await?;
    // The initial-status path always fetches status before returning the device.
    Ok((device, status.expect("initial status was requested")))
}

async fn finish_connection(
    device: Box<dyn PrinterDevice>,
    progress: Option<&ConnectProgressCallback>,
    fetch_initial_status: bool,
) -> Result<(Box<dyn PrinterDevice>, Option<PrinterStatus>)> {
    let status = if fetch_initial_status {
        emit_connect_progress(progress, ConnectStage::StatusFetching, None::<String>);
        match device.status().await {
            Ok(status) => Some(status),
            Err(error) => {
                let _ = device.disconnect().await;
                return Err(error);
            }
        }
    } else {
        None
    };
    emit_connect_progress(
        progress,
        ConnectStage::Connected,
        Some(device.name().to_owned()),
    );
    Ok((device, status))
}

async fn finish_connection_after_cleanup(
    device: Box<dyn PrinterDevice>,
    progress: Option<&ConnectProgressCallback>,
    fetch_initial_status: bool,
    cleanup: impl std::future::Future<Output = ()>,
) -> Result<(Box<dyn PrinterDevice>, Option<PrinterStatus>)> {
    // A best-effort scan stop may wait for the adapter. Complete it before the initial status
    // read so the returned snapshot does not age behind an awaited cleanup operation.
    cleanup.await;
    finish_connection(device, progress, fetch_initial_status).await
}

async fn connect_internal(
    device_name: &str,
    duration: Option<Duration>,
    progress: Option<&ConnectProgressCallback>,
    fetch_initial_status: bool,
) -> Result<(Box<dyn PrinterDevice>, Option<PrinterStatus>)> {
    emit_connect_progress(progress, ConnectStage::ScanStarted, None::<String>);

    let adapter = match transport::get_adapter().await {
        Ok(adapter) => adapter,
        Err(err) => {
            emit_connect_progress(progress, ConnectStage::Failed, Some(err.to_string()));
            return Err(err);
        }
    };

    // Start an active scan for discovery, then run a HYBRID connect strategy:
    //
    //   1. Fast path: stop the scan and attempt a direct connect bounded by FAST_PATH_TIMEOUT
    //      (~3 s). On a healthy BlueZ this completes in ~0.3 s; with the scan still running it
    //      would always cost ~11 s due to radio contention on the Pi Zero 2 W controller.
    //   2. Active-scan fallback: if the fast path errors with the BlueZ wedge signature
    //      ("In Progress" / "Timeout waiting for reply") OR exhausts FAST_PATH_TIMEOUT, restart
    //      the active scan and retry connect with the scan held live. A live active scan is the
    //      only observed recovery for a wedged BlueZ connection state machine — without it a
    //      wedge stays wedged forever (Phase 0). This path is slow (~11 s) but reliable.
    //
    // The progress callback may emit `BleConnecting` twice (once per attempt) — readers should
    // not be surprised by the duplicate stage.
    //
    // See `docs/plans/031` Phase 1.
    if let Err(err) = transport::start_scan(&adapter).await {
        emit_connect_progress(progress, ConnectStage::Failed, Some(err.to_string()));
        return Err(err);
    }

    let result: Result<(Box<dyn PrinterDevice>, Option<PrinterStatus>)> = async {
        // Poll the candidate list during the active scan and connect as soon as the target is
        // uniquely matched, rather than always waiting out the full scan window. The scan stays
        // active throughout (started above, stopped below). On a not-found/ambiguous result we
        // keep polling until the deadline, then surface the last selection error.
        let deadline = tokio::time::Instant::now() + duration.unwrap_or(DEFAULT_SCAN_DURATION);
        let (peripheral, name) = loop {
            let candidates = transport::collect_instax_peripherals(&adapter).await?;
            match select_matching_result(candidates, device_name) {
                Ok(found) => break found,
                Err(err) => {
                    if tokio::time::Instant::now() >= deadline {
                        return Err(err);
                    }
                    tokio::time::sleep(DISCOVERY_POLL_INTERVAL).await;
                }
            }
        };
        emit_connect_progress(progress, ConnectStage::ScanFinished, None::<String>);

        emit_connect_progress(progress, ConnectStage::DeviceMatched, Some(name.clone()));

        // Hybrid connect: stop the scan and try a fast direct connect first. If it times out or
        // hits the BlueZ wedge signature, restart the active scan and retry — that is the only
        // observed recovery for a wedged BlueZ. See the comment block above and
        // `docs/plans/031` Phase 1.
        let _ = transport::stop_scan(&adapter).await;
        let fast_path_peripheral = peripheral.clone();
        let fast_path = tokio::time::timeout(
            FAST_PATH_TIMEOUT,
            BleTransport::connect_with_progress(fast_path_peripheral, progress),
        )
        .await;
        let transport = match fast_path {
            Ok(Ok(transport)) => transport,
            Ok(Err(error)) if is_wedge_signature(&error) => {
                log::debug!(
                    "fast-path connect hit BlueZ wedge signature; falling back to active-scan retry: {}",
                    error
                );
                transport::start_scan(&adapter).await?;
                BleTransport::connect_with_progress(peripheral, progress).await?
            }
            Ok(Err(error)) => return Err(error),
            Err(_) => {
                log::debug!(
                    "fast-path connect exceeded {}s; falling back to active-scan retry",
                    FAST_PATH_TIMEOUT_S
                );
                // The timeout cancelled the fast-path future mid-flight — btleplug does NOT
                // auto-disconnect on drop, so BlueZ may still hold the link with GATT/notify
                // setup incomplete. The fallback's `connect_with_progress` would then see
                // `is_connected()==true` and skip the actual connect, running discovery on an
                // inconsistent link. Force a bounded disconnect first so the retry starts clean.
                let _ = tokio::time::timeout(
                    Duration::from_secs(1),
                    peripheral.disconnect(),
                )
                .await;
                transport::start_scan(&adapter).await?;
                BleTransport::connect_with_progress(peripheral, progress).await?
            }
        };
        let device =
            BlePrinterDevice::new_with_progress(Box::new(transport), name, progress).await?;

        finish_connection_after_cleanup(
            Box::new(device),
            progress,
            fetch_initial_status,
            async {
                let _ = transport::stop_scan(&adapter).await;
            },
        )
        .await
    }
    .await;

    if let Err(err) = &result {
        // Successful connections already stopped scanning before their final status read. Failed
        // discovery, device construction or initial status still require best-effort cleanup.
        let _ = transport::stop_scan(&adapter).await;
        emit_connect_progress(
            progress,
            ConnectStage::Failed,
            Some::<String>(err.to_string()),
        );
    }

    result
}

fn printer_name_matches(discovered_name: &str, target_name: &str) -> bool {
    if discovered_name == target_name {
        return true;
    }

    let discovered_normalized = normalized_printer_name(discovered_name);
    let target_normalized = normalized_printer_name(target_name);
    if discovered_normalized == target_normalized {
        return true;
    }

    match (
        extracted_printer_serial(&discovered_normalized),
        extracted_printer_serial(&target_normalized),
    ) {
        (Some(discovered_serial), Some(target_serial)) => discovered_serial == target_serial,
        _ => false,
    }
}

fn normalized_printer_name(name: &str) -> String {
    let trimmed = name.trim();
    let without_parenthetical_suffix = trimmed.split('(').next().unwrap_or(trimmed).trim();
    without_parenthetical_suffix
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_uppercase()
}

fn extracted_printer_serial(name: &str) -> Option<String> {
    let normalized = normalized_printer_name(name);
    let suffix = normalized.strip_prefix("INSTAX-")?;
    let serial: String = suffix
        .chars()
        .take_while(|ch| ch.is_ascii_alphanumeric())
        .collect();
    (!serial.is_empty()).then_some(serial)
}

fn select_matching_result<T>(results: Vec<(T, String)>, device_name: &str) -> Result<(T, String)> {
    let target_name = device_name.trim();
    let mut exact_name_matches = Vec::new();
    let mut normalized_matches = Vec::new();
    let mut partial_matches = Vec::new();

    for result in results {
        if result.1.trim() == target_name {
            exact_name_matches.push(result);
        } else if printer_name_matches(&result.1, device_name) {
            normalized_matches.push(result);
        } else if normalized_printer_name(&result.1).contains(&normalized_printer_name(device_name))
            || normalized_printer_name(device_name).contains(&normalized_printer_name(&result.1))
        {
            partial_matches.push(result);
        }
    }

    let target_has_platform_suffix = has_platform_suffix(target_name);
    if target_has_platform_suffix && exact_name_matches.len() == 1 {
        return Ok(exact_name_matches
            .into_iter()
            .next()
            .expect("one match must exist"));
    }
    if target_has_platform_suffix && exact_name_matches.len() > 1 {
        return select_preferred_advertisement(exact_name_matches);
    }

    let matches = if exact_name_matches.is_empty() && normalized_matches.is_empty() {
        partial_matches
    } else {
        exact_name_matches.append(&mut normalized_matches);
        exact_name_matches
    };

    match matches.len() {
        0 => Err(PrinterError::PrinterNotFound),
        1 => Ok(matches.into_iter().next().expect("one match must exist")),
        _count => select_preferred_advertisement(matches),
    }
}

fn has_platform_suffix(name: &str) -> bool {
    let upper = name.to_ascii_uppercase();
    upper.ends_with("(IOS)") || upper.ends_with("(ANDROID)")
}

fn select_preferred_advertisement<T>(mut matches: Vec<(T, String)>) -> Result<(T, String)> {
    if !all_same_printer_identity(&matches) {
        return Err(PrinterError::MultiplePrinters {
            count: matches.len(),
        });
    }
    matches.sort_by_key(|(_, name)| advertisement_priority(name));
    let best_priority = matches
        .first()
        .map(|(_, name)| advertisement_priority(name))
        .ok_or(PrinterError::PrinterNotFound)?;
    let same_priority_count = matches
        .iter()
        .filter(|(_, name)| advertisement_priority(name) == best_priority)
        .count();
    if same_priority_count == 1 {
        return Ok(matches.remove(0));
    }
    Err(PrinterError::MultiplePrinters {
        count: matches.len(),
    })
}

fn all_same_printer_identity<T>(matches: &[(T, String)]) -> bool {
    let Some((_, first_name)) = matches.first() else {
        return false;
    };
    let first_identity = printer_identity(first_name);
    matches
        .iter()
        .all(|(_, name)| printer_identity(name) == first_identity)
}

fn printer_identity(name: &str) -> String {
    extracted_printer_serial(name).unwrap_or_else(|| normalized_printer_name(name))
}

fn advertisement_priority(name: &str) -> u8 {
    let upper = name.to_ascii_uppercase();
    if upper.ends_with("(IOS)") {
        0
    } else if upper.ends_with("(ANDROID)") {
        1
    } else {
        2
    }
}

fn combine_operation_and_disconnect<T>(
    operation_result: Result<T>,
    disconnect_result: Result<()>,
) -> Result<T> {
    match (operation_result, disconnect_result) {
        (Err(err), _) => Err(err),
        (Ok(_), Err(err)) => Err(err),
        (Ok(value), Ok(())) => Ok(value),
    }
}

/// Connect to the first available Instax printer.
pub async fn connect_any(duration: Option<Duration>) -> Result<Box<dyn PrinterDevice>> {
    let adapter = transport::get_adapter().await?;
    let results = transport::scan(&adapter, duration.unwrap_or(DEFAULT_SCAN_DURATION)).await?;

    let (peripheral, name) = results
        .into_iter()
        .next()
        .ok_or(PrinterError::PrinterNotFound)?;

    let transport = BleTransport::connect(peripheral).await?;
    let device = BlePrinterDevice::new(Box::new(transport), name).await?;
    Ok(Box::new(device))
}

#[cfg(test)]
mod tests {
    use super::{
        combine_operation_and_disconnect, extracted_printer_serial, is_wedge_signature,
        normalized_printer_name, printer_name_matches, select_matching_result,
    };
    use crate::error::PrinterError;

    struct StatusTransport {
        replies: std::sync::Arc<
            std::sync::Mutex<std::collections::VecDeque<crate::Result<crate::protocol::Packet>>>,
        >,
        sent: std::sync::Arc<std::sync::Mutex<Vec<Vec<u8>>>>,
        disconnects: std::sync::Arc<std::sync::atomic::AtomicUsize>,
    }

    #[async_trait::async_trait]
    impl crate::transport::Transport for StatusTransport {
        async fn send(&self, data: &[u8]) -> crate::Result<()> {
            self.sent.lock().unwrap().push(data.to_vec());
            Ok(())
        }
        async fn receive(&self, _: std::time::Duration) -> crate::Result<crate::protocol::Packet> {
            self.replies
                .lock()
                .unwrap()
                .pop_front()
                .unwrap_or(Err(PrinterError::Timeout))
        }
        async fn send_and_receive(
            &self,
            data: &[u8],
            timeout: std::time::Duration,
        ) -> crate::Result<crate::protocol::Packet> {
            self.send(data).await?;
            self.receive(timeout).await
        }
        async fn disconnect(&self) -> crate::Result<()> {
            self.disconnects
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            Ok(())
        }
    }

    fn status_reply(info: u8, data: &[u8]) -> crate::Result<crate::protocol::Packet> {
        let mut payload = vec![0, info];
        payload.extend_from_slice(data);
        Ok(crate::protocol::Packet {
            opcode: crate::commands::OP_SUPPORT_FUNCTION_INFO,
            payload,
        })
    }

    #[tokio::test]
    async fn connection_returns_one_initial_status_and_later_queries_are_fresh() {
        use crate::commands::{
            INFO_BATTERY, INFO_IMAGE_SUPPORT, INFO_PRINT_HISTORY, INFO_PRINTER_FUNCTION,
        };
        use crate::device::BlePrinterDevice;
        use crate::models::PrinterModel;
        use std::sync::{Arc, Mutex};
        let sent = Arc::new(Mutex::new(Vec::new()));
        let disconnects = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let transport = StatusTransport {
            replies: Arc::new(Mutex::new(
                vec![
                    status_reply(INFO_IMAGE_SUPPORT, &[0x03, 0x20, 0x03, 0x20]),
                    status_reply(INFO_BATTERY, &[0, 5]),
                    status_reply(INFO_PRINTER_FUNCTION, &[0x80]),
                    status_reply(INFO_PRINT_HISTORY, &[0, 68]),
                    status_reply(INFO_BATTERY, &[0, 4]),
                    status_reply(INFO_PRINTER_FUNCTION, &[0]),
                    status_reply(INFO_PRINT_HISTORY, &[0, 69]),
                ]
                .into(),
            )),
            sent: Arc::clone(&sent),
            disconnects: Arc::clone(&disconnects),
        };
        let device = BlePrinterDevice::new(Box::new(transport), "INSTAX-52006924".into())
            .await
            .unwrap();
        let stages = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::clone(&stages);
        let progress: Box<crate::connect_progress::ConnectProgressCallback> =
            Box::new(move |event| observed.lock().unwrap().push(event.stage));
        let (device, initial) =
            super::finish_connection(Box::new(device), Some(progress.as_ref()), true)
                .await
                .unwrap();
        let initial = initial.unwrap();
        assert_eq!(
            (
                initial.battery,
                initial.film_remaining,
                initial.is_charging,
                initial.print_count
            ),
            (5, 0, true, 68)
        );
        assert_eq!(initial.model, PrinterModel::Square);
        assert_eq!(initial.name, device.name());
        assert_eq!(sent.lock().unwrap().len(), 4); // model + one three-command status
        assert_eq!(
            *stages.lock().unwrap(),
            vec![
                crate::connect_progress::ConnectStage::StatusFetching,
                crate::connect_progress::ConnectStage::Connected
            ]
        );
        let current = device.status().await.unwrap();
        assert_eq!(
            (current.battery, current.is_charging, current.print_count),
            (4, false, 69)
        );
        assert_eq!(sent.lock().unwrap().len(), 7);
        assert_eq!(disconnects.load(std::sync::atomic::Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn initial_status_failure_disconnects_and_never_emits_connected() {
        use crate::commands::INFO_IMAGE_SUPPORT;
        use std::sync::{Arc, Mutex};
        let disconnects = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let transport = StatusTransport {
            replies: Arc::new(Mutex::new(
                vec![
                    status_reply(INFO_IMAGE_SUPPORT, &[0x03, 0x20, 0x03, 0x20]),
                    Err(PrinterError::Timeout),
                ]
                .into(),
            )),
            sent: Arc::new(Mutex::new(Vec::new())),
            disconnects: Arc::clone(&disconnects),
        };
        let device =
            crate::device::BlePrinterDevice::new(Box::new(transport), "TestPrinter".into())
                .await
                .unwrap();
        let stages = Arc::new(Mutex::new(Vec::new()));
        let observed = Arc::clone(&stages);
        let progress: Box<crate::connect_progress::ConnectProgressCallback> =
            Box::new(move |event| observed.lock().unwrap().push(event.stage));
        assert!(matches!(
            super::finish_connection(Box::new(device), Some(progress.as_ref()), true).await,
            Err(PrinterError::Timeout)
        ));
        assert_eq!(disconnects.load(std::sync::atomic::Ordering::SeqCst), 1);
        assert_eq!(
            *stages.lock().unwrap(),
            vec![crate::connect_progress::ConnectStage::StatusFetching]
        );
    }

    #[tokio::test]
    async fn classic_connect_finishing_does_not_query_status() {
        use crate::commands::INFO_IMAGE_SUPPORT;
        use std::sync::{Arc, Mutex};
        let sent = Arc::new(Mutex::new(Vec::new()));
        let transport = StatusTransport {
            replies: Arc::new(Mutex::new(
                vec![status_reply(INFO_IMAGE_SUPPORT, &[0x03, 0x20, 0x03, 0x20])].into(),
            )),
            sent: Arc::clone(&sent),
            disconnects: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
        };
        let device =
            crate::device::BlePrinterDevice::new(Box::new(transport), "TestPrinter".into())
                .await
                .unwrap();
        let (_, status) = super::finish_connection(Box::new(device), None, false)
            .await
            .unwrap();
        assert!(status.is_none());
        assert_eq!(sent.lock().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn awaited_scan_cleanup_finishes_before_initial_status_is_sampled() {
        use crate::commands::{
            INFO_BATTERY, INFO_IMAGE_SUPPORT, INFO_PRINT_HISTORY, INFO_PRINTER_FUNCTION,
        };
        use std::sync::{Arc, Mutex};
        let sent = Arc::new(Mutex::new(Vec::new()));
        let replies = Arc::new(Mutex::new(
            vec![
                status_reply(INFO_IMAGE_SUPPORT, &[0x03, 0x20, 0x03, 0x20]),
                status_reply(INFO_BATTERY, &[0, 80]),
                status_reply(INFO_PRINTER_FUNCTION, &[7]),
                status_reply(INFO_PRINT_HISTORY, &[0, 68]),
            ]
            .into(),
        ));
        let transport = StatusTransport {
            replies: Arc::clone(&replies),
            sent: Arc::clone(&sent),
            disconnects: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
        };
        let device =
            crate::device::BlePrinterDevice::new(Box::new(transport), "TestPrinter".into())
                .await
                .unwrap();
        let entered = Arc::new(tokio::sync::Notify::new());
        let release = Arc::new(tokio::sync::Notify::new());
        let cleanup_entered = Arc::clone(&entered);
        let cleanup_release = Arc::clone(&release);
        let task = tokio::spawn(super::finish_connection_after_cleanup(
            Box::new(device),
            None,
            true,
            async move {
                cleanup_entered.notify_one();
                cleanup_release.notified().await;
            },
        ));
        entered.notified().await;
        assert_eq!(sent.lock().unwrap().len(), 1); // Only model detection before cleanup.
        assert!(!task.is_finished());
        // State changes while scan cleanup is pending must be reflected in the returned snapshot.
        *replies.lock().unwrap() = vec![
            status_reply(INFO_BATTERY, &[0, 79]),
            status_reply(INFO_PRINTER_FUNCTION, &[6]),
            status_reply(INFO_PRINT_HISTORY, &[0, 69]),
        ]
        .into();
        release.notify_one();
        let (_, status) = task.await.unwrap().unwrap();
        let status = status.unwrap();
        assert_eq!(
            (status.battery, status.film_remaining, status.print_count),
            (79, 6, 69)
        );
        assert_eq!(sent.lock().unwrap().len(), 4); // One status, with no second query.
    }

    #[test]
    fn is_wedge_signature_matches_in_progress() {
        // Mirrors the error string built by `BleTransport::connect_with_progress` when btleplug
        // surfaces BlueZ's "Connect() returned In Progress" wedge.
        let err = PrinterError::Ble("connect failed: In Progress".to_string());
        assert!(is_wedge_signature(&err));
    }

    #[test]
    fn is_wedge_signature_matches_dbus_reply_timeout() {
        // BlueZ's other wedge surface: D-Bus Connect() never returns within the ~25 s reply
        // timeout, yielding a btleplug error containing "Timeout waiting for reply".
        let err = PrinterError::Ble("connect failed: Timeout waiting for reply".to_string());
        assert!(is_wedge_signature(&err));
    }

    #[test]
    fn is_wedge_signature_rejects_unrelated_ble_errors() {
        // A generic write/discover failure should propagate to the caller, not trigger the
        // expensive active-scan recovery path.
        let err = PrinterError::Ble("write failed: not connected".to_string());
        assert!(!is_wedge_signature(&err));
    }

    #[test]
    fn is_wedge_signature_rejects_non_ble_errors() {
        assert!(!is_wedge_signature(&PrinterError::PrinterNotFound));
        assert!(!is_wedge_signature(&PrinterError::Timeout));
    }

    #[test]
    fn normalizes_parenthetical_suffixes() {
        assert_eq!(
            normalized_printer_name("INSTAX-12345678 (iOS)"),
            "INSTAX-12345678"
        );
    }

    #[test]
    fn matches_same_printer_with_ios_suffix_variants() {
        assert!(printer_name_matches(
            "INSTAX-12345678 (iOS)",
            "INSTAX-12345678"
        ));
        assert!(printer_name_matches(
            "INSTAX-12345678",
            "INSTAX-12345678 (IOS)"
        ));
    }

    #[test]
    fn extracts_serial_from_instax_name() {
        assert_eq!(
            extracted_printer_serial("INSTAX-12345678 (iOS)").as_deref(),
            Some("12345678")
        );
        assert_eq!(
            extracted_printer_serial("INSTAX-1N034655 (iOS)").as_deref(),
            Some("1N034655")
        );
    }

    #[test]
    fn normalized_printer_name_collapses_whitespace_and_uppercases() {
        assert_eq!(
            normalized_printer_name("  instax-12345678   (iOS)  "),
            "INSTAX-12345678"
        );
    }

    #[test]
    fn extracted_printer_serial_returns_none_for_non_instax_names() {
        assert_eq!(extracted_printer_serial("mini-link"), None);
        assert_eq!(extracted_printer_serial("INSTAX-"), None);
    }

    #[test]
    fn printer_name_matches_returns_false_for_different_serials() {
        assert!(!printer_name_matches(
            "INSTAX-12345678 (iOS)",
            "INSTAX-87654321"
        ));
        assert!(!printer_name_matches(
            "INSTAX-1N034655 (iOS)",
            "INSTAX-1X999999"
        ));
    }

    #[test]
    fn select_matching_result_prefers_exact_match_over_partial_match() {
        let results = vec![
            (1, "INSTAX-1234".to_string()),
            (2, "INSTAX-12345678 (iOS)".to_string()),
        ];
        let (matched, name) = select_matching_result(results, "INSTAX-12345678").unwrap();
        assert_eq!(matched, 2);
        assert_eq!(name, "INSTAX-12345678 (iOS)");
    }

    #[test]
    fn select_matching_result_prefers_ios_when_serial_has_multiple_advertisements() {
        let results = vec![
            (1, "INSTAX-12345678".to_string()),
            (2, "INSTAX-12345678 (iOS)".to_string()),
        ];
        let (matched, name) = select_matching_result(results, "INSTAX-12345678").unwrap();
        assert_eq!(matched, 2);
        assert_eq!(name, "INSTAX-12345678 (iOS)");
    }

    #[test]
    fn select_matching_result_prefers_exact_platform_suffix() {
        let results = vec![
            (1, "INSTAX-12345678 (ANDROID)".to_string()),
            (2, "INSTAX-12345678 (iOS)".to_string()),
        ];
        let (matched, name) = select_matching_result(results, "INSTAX-12345678 (ANDROID)").unwrap();
        assert_eq!(matched, 1);
        assert_eq!(name, "INSTAX-12345678 (ANDROID)");
    }

    #[test]
    fn select_matching_result_falls_back_to_partial_match() {
        let results = vec![
            (1, "INSTAX-1234".to_string()),
            (2, "INSTAX-9999".to_string()),
        ];
        let (matched, name) = select_matching_result(results, "1234").unwrap();
        assert_eq!(matched, 1);
        assert_eq!(name, "INSTAX-1234");
    }

    #[test]
    fn select_matching_result_returns_not_found_when_no_match_exists() {
        let results = vec![(1, "INSTAX-1234".to_string())];
        let err = select_matching_result(results, "INSTAX-9999").unwrap_err();
        assert!(matches!(err, PrinterError::PrinterNotFound));
    }

    #[test]
    fn select_matching_result_returns_multiple_printers_for_multiple_partial_matches() {
        let results = vec![
            (1, "INSTAX-1234".to_string()),
            (2, "INSTAX-12345".to_string()),
        ];
        let err = select_matching_result(results, "123").unwrap_err();
        assert!(matches!(err, PrinterError::MultiplePrinters { count: 2 }));
    }

    #[test]
    fn select_matching_result_does_not_prefer_platform_suffix_across_different_printers() {
        let results = vec![
            (1, "INSTAX-1N034655 (iOS)".to_string()),
            (2, "INSTAX-1X999999 (ANDROID)".to_string()),
        ];
        let err = select_matching_result(results, "1").unwrap_err();
        assert!(matches!(err, PrinterError::MultiplePrinters { count: 2 }));
    }

    #[test]
    fn combine_operation_and_disconnect_prefers_operation_error() {
        let err = combine_operation_and_disconnect::<()>(
            Err(PrinterError::PrinterBusy),
            Err(PrinterError::Timeout),
        )
        .unwrap_err();
        assert!(matches!(err, PrinterError::PrinterBusy));
    }

    #[test]
    fn combine_operation_and_disconnect_returns_disconnect_error_after_success() {
        let err = combine_operation_and_disconnect(Ok(()), Err(PrinterError::Timeout)).unwrap_err();
        assert!(matches!(err, PrinterError::Timeout));
    }

    #[test]
    fn combine_operation_and_disconnect_returns_success_value() {
        let value = combine_operation_and_disconnect(Ok(42_u8), Ok(())).unwrap();
        assert_eq!(value, 42);
    }
}

/// One-shot print: connect to a printer, print an image, disconnect.
///
/// If `device_name` is None, connects to the first available printer.
pub async fn print_file(
    path: &Path,
    fit: FitMode,
    quality: u8,
    device_name: Option<&str>,
    progress: Option<&(dyn Fn(usize, usize) + Send + Sync)>,
) -> Result<()> {
    let device = match device_name {
        Some(name) => connect(name, None).await?,
        None => connect_any(None).await?,
    };

    let print_result = device.print_file(path, fit, quality, 0, progress).await;
    let disconnect_result = device.disconnect().await;
    combine_operation_and_disconnect(print_result, disconnect_result)
}

/// Get printer status: connect, query, disconnect.
pub async fn get_status(
    device_name: Option<&str>,
    duration: Option<Duration>,
) -> Result<PrinterStatus> {
    let device = match device_name {
        Some(name) => connect(name, duration).await?,
        None => connect_any(duration).await?,
    };

    let status_result = device.status().await;
    let disconnect_result = device.disconnect().await;
    combine_operation_and_disconnect(status_result, disconnect_result)
}
