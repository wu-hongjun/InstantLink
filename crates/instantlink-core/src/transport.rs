//! BLE GATT transport layer using btleplug.
//!
//! Handles service/characteristic discovery, notification subscription,
//! send/receive with timeouts, and MTU fragmentation.

use std::collections::BTreeMap;
use std::future::Future;
use std::num::NonZeroUsize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{LazyLock, Mutex as StdMutex};
use std::time::Duration;

use async_trait::async_trait;
use btleplug::api::{
    Central, Characteristic, Manager as _, Peripheral as _, ScanFilter, WriteType,
};
use btleplug::platform::{Adapter, Manager, Peripheral};
use futures::StreamExt;
use tokio::sync::{Mutex, mpsc};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

#[cfg(target_os = "linux")]
use std::process::Stdio;

use crate::commands::{Command, OP_DATA, ResponseExpectation};
use crate::connect_progress::{ConnectProgressCallback, ConnectStage, emit_connect_progress};
use crate::error::{PrinterError, Result};
use crate::models::PrinterModel;
use crate::protocol::{self, PacketAssembler};

#[cfg(target_os = "linux")]
#[path = "transport_discovery.rs"]
mod discovery;

async fn receive_packet_from_channel(
    rx: &mut mpsc::Receiver<Vec<u8>>,
    assembler: &mut PacketAssembler,
    timeout: Duration,
) -> Result<protocol::Packet> {
    let deadline = tokio::time::Instant::now() + timeout;

    loop {
        match assembler.feed(&[]) {
            Ok(Some(packet)) => return Ok(packet),
            Ok(None) => {}
            Err(e) => log::warn!("protocol error (buffered data): {e}"),
        }

        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            assembler.reset();
            return Err(PrinterError::Timeout);
        }

        let data = match tokio::time::timeout(remaining, rx.recv()).await {
            Ok(Some(data)) => data,
            Ok(None) => return Err(PrinterError::Ble("notification channel closed".into())),
            Err(_) => {
                assembler.reset();
                return Err(PrinterError::Timeout);
            }
        };

        match assembler.feed(&data) {
            Ok(Some(packet)) => return Ok(packet),
            Ok(None) => {}
            Err(e) => log::warn!("protocol error (incoming data): {e}"),
        }
    }
}

async fn receive_expected_from_transport<T: Transport + ?Sized>(
    transport: &T,
    timeout: Duration,
    expectation: ResponseExpectation,
) -> Result<protocol::Packet> {
    let deadline = tokio::time::Instant::now() + timeout;

    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            return Err(PrinterError::Timeout);
        }

        let packet = transport.receive(remaining).await?;
        if expectation.matches(&packet) {
            return Ok(packet);
        }

        log::debug!(
            "skipping unrelated printer response while waiting for {expectation:?}: opcode=0x{:04x}, payload_len={}",
            packet.opcode,
            packet.payload.len()
        );
    }
}

/// Probe only an outstanding response, after its normal fast ACK window. Query
/// failures are inconclusive; the original protocol deadline still applies.
async fn wait_for_confirmed_disconnect<Q, Fut>(mut query: Q)
where
    Q: FnMut() -> Fut,
    Fut: Future<Output = Result<bool>>,
{
    loop {
        tokio::time::sleep(Duration::from_secs(1)).await;
        if matches!(
            tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, query()).await,
            Ok(Ok(false))
        ) {
            return;
        }
    }
}

fn closed_link_error() -> PrinterError {
    PrinterError::Ble("BLE link disconnected; reconnect before sending".into())
}

async fn receive_packet_with_link_checks<Q, Fut>(
    rx: &mut mpsc::Receiver<Vec<u8>>,
    assembler: &mut PacketAssembler,
    timeout: Duration,
    closed: &CancellationToken,
    query: Q,
) -> Result<protocol::Packet>
where
    Q: FnMut() -> Fut,
    Fut: Future<Output = Result<bool>>,
{
    // A queued, complete ACK takes priority over a simultaneous state query.
    // Both futures stay in this scope: receiving an ACK or cancellation drops
    // the probe immediately, without leaving a background task behind.
    let result = tokio::select! {
        biased;
        packet = receive_packet_from_channel(rx, assembler, timeout) => packet,
        _ = closed.cancelled() => Err(closed_link_error()),
        _ = wait_for_confirmed_disconnect(query) => Err(closed_link_error()),
    };
    if matches!(&result, Err(PrinterError::Ble(_))) {
        assembler.reset();
    }
    result
}

/// Instax BLE service UUID.
pub const SERVICE_UUID: Uuid = Uuid::from_u128(0x70954782_2d83_473d_9e5f_81e1d02d5273);
/// Instax BLE write characteristic UUID.
pub const WRITE_CHAR_UUID: Uuid = Uuid::from_u128(0x70954783_2d83_473d_9e5f_81e1d02d5273);
/// Instax BLE notify characteristic UUID.
pub const NOTIFY_CHAR_UUID: Uuid = Uuid::from_u128(0x70954784_2d83_473d_9e5f_81e1d02d5273);

/// Standard BLE Device Information Service UUID.
pub const DIS_SERVICE_UUID: Uuid = Uuid::from_u128(0x0000180a_0000_1000_8000_00805f9b34fb);
/// Standard BLE DIS Model Number characteristic UUID.
pub const DIS_MODEL_NUMBER_UUID: Uuid = Uuid::from_u128(0x00002a24_0000_1000_8000_00805f9b34fb);

/// Default scan duration.
pub const DEFAULT_SCAN_DURATION: Duration = Duration::from_secs(5);
/// Default command timeout.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(10);
/// Timeout for individual BLE write operations.
pub const DEFAULT_WRITE_TIMEOUT: Duration = Duration::from_secs(2);
/// Timeout for BLE state queries and notification cleanup.
pub const DEFAULT_DISCONNECT_TIMEOUT: Duration = Duration::from_secs(2);
/// BlueZ deliberately delays physical disconnect using a two-second GLib timer.
/// Allow timer/controller completion without extending state-query budgets.
#[cfg(target_os = "linux")]
pub const DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT: Duration = Duration::from_secs(5);
#[cfg(not(target_os = "linux"))]
pub const DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT: Duration = DEFAULT_DISCONNECT_TIMEOUT;

/// Timeout to wait for the listener task to exit gracefully after cancellation.
const LISTENER_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(250);
const MTU_DISCOVERY_TIMEOUT: Duration = Duration::from_secs(1);
#[cfg(target_os = "linux")]
static MTU_BUS_OPEN: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
const MAX_FALLBACK_DEVICES: usize = 128;

#[derive(Default)]
struct FallbackPolicy {
    fragments: bool,
    pacing: bool,
}

#[derive(Default)]
struct FallbackDevices {
    devices: BTreeMap<String, FallbackPolicy>,
    reset_required: std::collections::BTreeSet<String>,
    /// Once capacity is reached, use conservative fragments for all new devices
    /// rather than evicting a device whose larger writes were unsafe.
    saturated: bool,
}

static FALLBACK_DEVICES: LazyLock<StdMutex<FallbackDevices>> =
    LazyLock::new(|| StdMutex::new(FallbackDevices::default()));

impl FallbackDevices {
    fn contains(&self, device: &str) -> bool {
        self.saturated
            || self
                .devices
                .get(device)
                .is_some_and(|policy| policy.fragments)
    }

    fn conservative_pacing(&self, device: &str) -> bool {
        self.saturated || self.devices.get(device).is_some_and(|policy| policy.pacing)
    }

    fn disable_fast_pacing(&mut self, device: &str) {
        if let Some(policy) = self.devices.get_mut(device) {
            policy.pacing = true;
        } else if self.devices.len() < MAX_FALLBACK_DEVICES {
            self.devices.insert(
                device.to_owned(),
                FallbackPolicy {
                    fragments: false,
                    pacing: true,
                },
            );
        } else {
            self.saturated = true;
        }
    }

    fn requires_reset(&self, device: &str) -> bool {
        self.saturated || self.reset_required.contains(device)
    }

    fn reset_completed(&mut self, device: &str) {
        self.reset_required.remove(device);
        if self
            .devices
            .get(device)
            .is_some_and(|policy| !policy.fragments && !policy.pacing)
        {
            self.devices.remove(device);
        }
    }

    fn insert(&mut self, device: &str, enlarged: bool) {
        if let Some(policy) = self.devices.get_mut(device) {
            policy.fragments |= enlarged;
            self.reset_required.insert(device.to_owned());
        } else if self.devices.len() < MAX_FALLBACK_DEVICES {
            self.devices.insert(
                device.to_owned(),
                FallbackPolicy {
                    fragments: enlarged,
                    pacing: false,
                },
            );
            self.reset_required.insert(device.to_owned());
        } else {
            self.saturated = true;
        }
    }
}

fn conservative_device(device: &str) -> bool {
    FALLBACK_DEVICES
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .contains(device)
}

/// Validated Square/Linux/236-byte intermediate gap. Keep model final settling
/// and pre-execute waits, and retain baseline for unverified or failed sessions.
pub const PREFERRED_SQUARE_CHUNK_DELAY_MS: u64 = 25;

pub fn data_packet_delay_ms_for_context(
    model: PrinterModel,
    linux: bool,
    payload: usize,
    legacy: bool,
    pacing_fallback: bool,
) -> u64 {
    if linux
        && model == PrinterModel::Square
        && payload == protocol::MAX_FRAGMENT_PAYLOAD
        && !legacy
        && !pacing_fallback
    {
        PREFERRED_SQUARE_CHUNK_DELAY_MS
    } else {
        model.spec().packet_delay_ms
    }
}

struct PacingSession {
    device: String,
    legacy_ack_seen: AtomicBool,
    fast_gap_used: AtomicBool,
    disabled: AtomicBool,
}

impl PacingSession {
    fn new(device: String) -> Self {
        let disabled = FALLBACK_DEVICES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .conservative_pacing(&device);
        Self {
            device,
            legacy_ack_seen: AtomicBool::new(false),
            fast_gap_used: AtomicBool::new(false),
            disabled: AtomicBool::new(disabled),
        }
    }

    fn record_ack(&self, packet: &protocol::Packet) {
        if packet.opcode == OP_DATA && packet.payload.len() == 1 {
            self.legacy_ack_seen.store(true, Ordering::Release);
        }
    }

    fn started(&self) {
        self.fast_gap_used.store(false, Ordering::Release);
    }
    fn completed(&self) {
        self.fast_gap_used.store(false, Ordering::Release);
    }
    fn failed(&self, writes: &WriteSession) {
        writes.require_link_reset();
        if self.fast_gap_used.load(Ordering::Acquire) {
            self.disabled.store(true, Ordering::Release);
            FALLBACK_DEVICES
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .disable_fast_pacing(&self.device);
        }
    }
}

struct WriteSession {
    device: String,
    payload_size: NonZeroUsize,
    poisoned: AtomicBool,
    enlarged_attempted: AtomicBool,
}

impl WriteSession {
    fn require_link_reset(&self) {
        self.poisoned.store(true, Ordering::Release);
        FALLBACK_DEVICES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(&self.device, false);
    }

    fn delivery(&self) -> Result<DeliveryGuard<'_>> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(PrinterError::Ble(
                "previous BLE delivery was interrupted; reconnect before sending".into(),
            ));
        }
        self.enlarged_attempted.store(false, Ordering::Release);
        Ok(DeliveryGuard {
            session: self,
            armed: true,
        })
    }

    fn interrupt(&self) {
        self.poisoned.store(true, Ordering::Release);
        FALLBACK_DEVICES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(
                &self.device,
                self.enlarged_attempted.load(Ordering::Acquire),
            );
    }
}

/// Cancellation and errors may leave an uncertain prefix in the Printer. Never
/// restart that message or let another command use this transport afterward.
struct DeliveryGuard<'a> {
    session: &'a WriteSession,
    armed: bool,
}

impl DeliveryGuard<'_> {
    fn complete(mut self) {
        self.armed = false;
    }
}

impl Drop for DeliveryGuard<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.session.interrupt();
        }
    }
}

/// Teardown uncertainty requires a fresh link, without attributing a previously
/// successful large write to a fragmentation failure.
struct LinkResetGuard<'a> {
    session: &'a WriteSession,
    armed: bool,
}

impl LinkResetGuard<'_> {
    fn complete(mut self) {
        self.armed = false;
    }
}

impl Drop for LinkResetGuard<'_> {
    fn drop(&mut self) {
        if self.armed {
            self.session.require_link_reset();
        }
    }
}

async fn disconnect_and_verify<D, DFut, Q, QFut>(disconnect: D, query_connected: Q) -> Result<()>
where
    D: FnOnce() -> DFut,
    DFut: Future<Output = Result<()>>,
    Q: FnOnce() -> QFut,
    QFut: Future<Output = Result<bool>>,
{
    // Never gate the action on a preliminary status RPC: BlueZ can stop
    // answering that query while still holding a physical connection open.
    let disconnect_error =
        match tokio::time::timeout(DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT, disconnect()).await {
            Ok(Ok(())) => None,
            Ok(Err(error)) => Some(error),
            Err(_) => Some(PrinterError::Timeout),
        };
    match tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, query_connected()).await {
        Ok(Ok(false)) => Ok(()),
        Ok(Ok(true)) => Err(disconnect_error.unwrap_or_else(|| {
            PrinterError::Ble("BLE link remained connected after disconnect".into())
        })),
        Ok(Err(error)) => Err(disconnect_error.unwrap_or(error)),
        Err(_) => Err(disconnect_error.unwrap_or(PrinterError::Timeout)),
    }
}

async fn write_fragments<F, Fut>(data: &[u8], session: &WriteSession, mut write: F) -> Result<()>
where
    F: FnMut(Vec<u8>) -> Fut,
    Fut: Future<Output = Result<()>>,
{
    let delivery = session.delivery()?;
    for fragment in protocol::fragment_with_size(data, session.payload_size) {
        if fragment.len() > protocol::MTU_SIZE {
            session.enlarged_attempted.store(true, Ordering::Release);
        }
        tokio::time::timeout(DEFAULT_WRITE_TIMEOUT, write(fragment))
            .await
            .map_err(|_| PrinterError::Timeout)??;
    }
    delivery.complete();
    Ok(())
}

fn close_link(session: &WriteSession, closed: &CancellationToken, listener: &CancellationToken) {
    session.require_link_reset();
    closed.cancel();
    listener.cancel();
}

async fn write_fragments_on_open_link<F, Fut>(
    data: &[u8],
    session: &WriteSession,
    closed: &CancellationToken,
    write: F,
) -> Result<()>
where
    F: FnMut(Vec<u8>) -> Fut,
    Fut: Future<Output = Result<()>>,
{
    tokio::select! {
        biased;
        _ = closed.cancelled() => Err(closed_link_error()),
        result = write_fragments(data, session, write) => result,
    }
}
/// Maximum time to wait for the Instax GATT characteristics to be exported by
/// the OS BLE stack after service discovery. BlueZ exports characteristics
/// incrementally, so they may not all be present immediately after connect.
/// Kept short: this blocking connect holds the bridge's serialized BLE lock, so
/// a long poll starves the single-threaded UI/render loop. The loop also breaks
/// early when the link drops, so a missing characteristic resolves quickly.
const CHARACTERISTIC_RESOLVE_TIMEOUT: Duration = Duration::from_secs(2);
/// Interval between characteristic-resolution poll attempts.
const CHARACTERISTIC_RESOLVE_POLL_INTERVAL: Duration = Duration::from_millis(300);
/// Timeout for the Linux bluetoothctl fallback used when btleplug connect races BlueZ discovery.
#[cfg(target_os = "linux")]
const BLUETOOTHCTL_CONNECT_TIMEOUT: Duration = Duration::from_secs(15);

/// Trait for BLE transport operations (enables mocking in tests).
#[async_trait]
pub trait Transport: Send + Sync {
    /// Cheap, read-only evidence of terminal link closure. An uncertain ACK or
    /// state-query failure is not proof of disconnection.
    fn known_disconnected(&self) -> bool {
        false
    }

    /// Send raw bytes to the printer's write characteristic.
    async fn send(&self, data: &[u8]) -> Result<()>;

    /// Receive the next complete protocol packet, with timeout.
    async fn receive(&self, timeout: Duration) -> Result<protocol::Packet>;

    /// Send a command packet and wait for the response.
    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<protocol::Packet>;

    /// Send a command packet and wait for a matching response, skipping stale
    /// notifications or ACKs that belong to earlier commands.
    async fn send_and_receive_expected(
        &self,
        data: &[u8],
        timeout: Duration,
        expectation: ResponseExpectation,
    ) -> Result<protocol::Packet> {
        self.send(data).await?;
        receive_expected_from_transport(self, timeout, expectation).await
    }

    /// Disconnect from the printer.
    async fn disconnect(&self) -> Result<()>;

    /// Preferred intermediate gap; final-chunk settle always uses the model spec.
    fn data_packet_delay_ms(&self, model: PrinterModel) -> u64 {
        model.spec().packet_delay_ms
    }
    fn image_transfer_started(&self) {}
    fn image_transfer_completed(&self) {}
    fn image_transfer_failed(&self) {}
    fn image_transfer_rejected(&self) {
        self.image_transfer_failed();
    }
    fn fast_chunk_gap_used(&self) {}

    /// Optional DIS Model Number hint for printer model detection.
    /// Returns `None` if DIS was not available or not read.
    fn model_number_hint(&self) -> Option<&str> {
        None
    }
}

/// Process-wide cache of the BLE `Manager` and selected `Adapter`.
///
/// The `Manager` is cached (not just the `Adapter`) because on BlueZ each
/// `Manager::new()` opens a fresh D-Bus connection. Creating a new manager on
/// every scan/connect leaks D-Bus connections; after ~256 of them BlueZ refuses
/// new connections ("max number of active connections for UID"). Holding the
/// `Manager` for the process lifetime keeps a single D-Bus session alive and
/// reused. `OnceCell::get_or_try_init` does NOT cache failures, so a transient
/// init error can be retried on the next call.
static BLE_ADAPTER: tokio::sync::OnceCell<(Manager, Adapter)> = tokio::sync::OnceCell::const_new();

/// Get the default BLE adapter.
///
/// The underlying `Manager`/`Adapter` are created exactly once per process and
/// reused on every call (see [`BLE_ADAPTER`]). Returns a clone of the cached
/// `Adapter` (`Adapter: Clone`).
pub async fn get_adapter() -> Result<Adapter> {
    let (_manager, adapter) = BLE_ADAPTER
        .get_or_try_init(|| async {
            let manager = Manager::new()
                .await
                .map_err(|e| PrinterError::Ble(format!("failed to create BLE manager: {e}")))?;
            let adapter = manager
                .adapters()
                .await
                .map_err(|e| PrinterError::Ble(format!("failed to list BLE adapters: {e}")))?
                .into_iter()
                .next()
                .ok_or_else(|| PrinterError::Ble("no BLE adapter found".into()))?;
            Ok::<_, PrinterError>((manager, adapter))
        })
        .await?;
    Ok(adapter.clone())
}

/// Scan for Instax printers.
///
/// Returns a list of `(peripheral, local_name)` pairs for nearby Instax devices.
/// Uses name-based matching ("INSTAX") because some printers don't advertise
/// the service UUID until after connection.
pub async fn scan(adapter: &Adapter, duration: Duration) -> Result<Vec<(Peripheral, String)>> {
    start_scan(adapter).await?;
    tokio::time::sleep(duration).await;
    stop_scan(adapter).await?;
    collect_instax_peripherals(adapter).await
}

/// Begin an active BLE scan.
///
/// Scans without a service UUID filter — some Instax printers don't advertise the service UUID in
/// their advertisements, only exposing it after connection during service discovery.
///
/// Kept separate from [`stop_scan`] so callers can keep the scan running *across* a connect attempt.
/// On BlueZ + the Pi Zero 2 W controller, background auto-connect to a bonded peripheral stalls
/// ("connection In Progress" that never completes); a live active scan lets the controller complete
/// the connection. See `docs/plans/031` Phase 0.
pub async fn start_scan(adapter: &Adapter) -> Result<()> {
    adapter
        .start_scan(ScanFilter::default())
        .await
        .map_err(|e| PrinterError::Ble(format!("scan failed: {e}")))
}

/// Stop an active BLE scan started by [`start_scan`].
pub async fn stop_scan(adapter: &Adapter) -> Result<()> {
    adapter
        .stop_scan()
        .await
        .map_err(|e| PrinterError::Ble(format!("stop scan failed: {e}")))
}

/// Return `(peripheral, local_name)` pairs for the Instax devices the adapter currently knows about.
///
/// Reads the adapter's peripheral cache without controlling the scan, so it can be called while a
/// scan started by [`start_scan`] is still running. Linux excludes inactive known-only records;
/// a connected link or RSSI is required, although retained RSSI is not a liveness guarantee.
pub async fn collect_instax_peripherals(adapter: &Adapter) -> Result<Vec<(Peripheral, String)>> {
    #[cfg(target_os = "linux")]
    let mut evidence_deadline = None;
    let peripherals = adapter
        .peripherals()
        .await
        .map_err(|e| PrinterError::Ble(format!("failed to list peripherals: {e}")))?;

    #[cfg(target_os = "linux")]
    let snapshot = if peripherals.is_empty() {
        None
    } else {
        discovery::snapshot().await
    };

    let mut results = Vec::new();
    #[cfg(target_os = "linux")]
    let mut skipped = 0;
    for p in peripherals {
        #[cfg(target_os = "linux")]
        if snapshot.as_ref().is_some_and(|objects| {
            discovery::definitely_non_instax(objects, &format!("/org/bluez/{}", p.id()))
        }) {
            skipped += 1;
            continue;
        }
        if let Ok(Some(props)) = p.properties().await {
            let matches_name = props
                .local_name
                .as_deref()
                .is_some_and(|name| name.starts_with("INSTAX"));
            let matches_service = props.services.contains(&SERVICE_UUID);

            if matches_name || matches_service {
                let display_name = props
                    .local_name
                    .clone()
                    .unwrap_or_else(|| p.id().to_string());
                if is_android_advertisement(&display_name) {
                    continue;
                }
                #[cfg(target_os = "linux")]
                if props.rssi.is_none() {
                    let deadline = *evidence_deadline.get_or_insert_with(|| {
                        tokio::time::Instant::now() + Duration::from_millis(250)
                    });
                    if !linux_scan_candidate_has_evidence(props.rssi, p.is_connected(), deadline)
                        .await
                    {
                        // BlueZ persists names/UUIDs for bonded, powered-off
                        // Printers. A connected link remains usable without
                        // RSSI; queries share one budget across cached devices.
                        continue;
                    }
                }
                results.push((p, display_name));
            }
        }
    }

    #[cfg(target_os = "linux")]
    log::debug!(
        "native discovery bulk prefilter: snapshot={}, unrelated_skipped={}, candidates={}",
        snapshot.is_some(),
        skipped,
        results.len()
    );

    Ok(results)
}

#[cfg(any(target_os = "linux", test))]
async fn linux_scan_candidate_has_evidence<F, E>(
    rssi: Option<i16>,
    connected: F,
    deadline: tokio::time::Instant,
) -> bool
where
    F: Future<Output = std::result::Result<bool, E>>,
{
    rssi.is_some()
        || matches!(
            tokio::time::timeout_at(deadline, connected).await,
            Ok(Ok(true))
        )
}

fn is_android_advertisement(name: &str) -> bool {
    name.trim().to_ascii_uppercase().ends_with("(ANDROID)")
}

#[cfg(target_os = "linux")]
type BluezObjects = std::collections::HashMap<
    dbus::Path<'static>,
    std::collections::HashMap<String, dbus::arg::PropMap>,
>;

#[cfg(target_os = "linux")]
fn bluez_write_mtu(objects: &BluezObjects, device_path: &str) -> Option<u16> {
    use dbus::arg::prop_cast;
    let device = objects
        .get(&dbus::Path::new(device_path).ok()?)?
        .get("org.bluez.Device1")?;
    if !*prop_cast::<bool>(device, "Connected")? {
        return None;
    }
    let mut services = objects.iter().filter_map(|(path, interfaces)| {
        let service = interfaces.get("org.bluez.GattService1")?;
        if &**prop_cast::<dbus::Path<'static>>(service, "Device")? != device_path
            || !path.starts_with(&format!("{device_path}/"))
            || Uuid::parse_str(prop_cast::<String>(service, "UUID")?).ok()? != SERVICE_UUID
        {
            return None;
        }
        Some(path)
    });
    // btleplug indexes services by UUID as well; duplicate services make its
    // choice ambiguous even when only one exports a writable characteristic.
    let selected_service = services.next()?;
    if services.next().is_some() {
        return None;
    }
    let mut matches = objects.iter().filter_map(|(path, interfaces)| {
        let characteristic = interfaces.get("org.bluez.GattCharacteristic1")?;
        let uuid = Uuid::parse_str(prop_cast::<String>(characteristic, "UUID")?).ok()?;
        if uuid != WRITE_CHAR_UUID {
            return None;
        }
        let service_path = prop_cast::<dbus::Path<'static>>(characteristic, "Service")?;
        // Verify path ancestry and explicit parent properties; a matching UUID
        // on another adapter/device/service must never select this Printer's MTU.
        if service_path != selected_service || !path.starts_with(&format!("{service_path}/")) {
            return None;
        }
        Some(characteristic)
    });
    // Duplicate identities are ambiguous even if one lacks Flags or MTU.
    let characteristic = matches.next()?;
    if matches.next().is_some() {
        return None;
    }
    let flags = prop_cast::<Vec<String>>(characteristic, "Flags")?;
    if !flags.iter().any(|flag| flag == "write-without-response") {
        return None;
    }
    prop_cast::<u16>(characteristic, "MTU").copied()
}

struct AbortOnDrop(Option<JoinHandle<()>>);

impl Drop for AbortOnDrop {
    fn drop(&mut self) {
        if let Some(handle) = self.0.take() {
            handle.abort();
        }
    }
}

#[cfg(target_os = "linux")]
async fn negotiated_write_mtu(
    peripheral: &Peripheral,
    characteristic: &Characteristic,
) -> Option<u16> {
    use dbus::nonblock::stdintf::org_freedesktop_dbus::ObjectManager;
    if characteristic.uuid != WRITE_CHAR_UUID || characteristic.service_uuid != SERVICE_UUID {
        return None;
    }
    let device_path = format!("/org/bluez/{}", peripheral.id());
    let discovery = async {
        // libdbus opens the bus synchronously. Its late result owns its resource
        // without spawning a task, so timeout/cancellation cannot leak an IO task.
        let permit = MTU_BUS_OPEN.try_acquire().ok()?;
        let (resource, connection) = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            dbus_tokio::connection::new_system_sync()
        })
        .await
        .ok()?
        .ok()?;
        let _resource_guard = AbortOnDrop(Some(tokio::spawn(async move {
            let error = resource.await;
            log::debug!("MTU discovery D-Bus resource ended: {error}");
        })));
        let proxy = dbus::nonblock::Proxy::new("org.bluez", "/", MTU_DISCOVERY_TIMEOUT, connection);
        let objects = proxy.get_managed_objects().await.ok()?;
        bluez_write_mtu(&objects, &device_path)
    };
    match tokio::time::timeout(MTU_DISCOVERY_TIMEOUT, discovery).await {
        Ok(mtu) => mtu,
        Err(_) => {
            log::debug!("MTU discovery timed out; using established BLE payload fallback");
            None
        }
    }
}

#[cfg(not(target_os = "linux"))]
async fn negotiated_write_mtu(
    _peripheral: &Peripheral,
    _characteristic: &Characteristic,
) -> Option<u16> {
    None
}

/// Read already-published MTU metadata while the notification listener settles.
/// The minimum settle interval is unchanged, including on platforms without MTU
/// metadata. If publication races the early query, retry after that interval;
/// both queries share the original settle-plus-discovery budget. No query or
/// resource task survives cancellation of this setup future.
async fn settle_and_read_mtu<Q, F>(mut query: Q) -> Option<u16>
where
    Q: FnMut() -> F,
    F: Future<Output = Option<u16>>,
{
    let settle = Duration::from_millis(200);
    let deadline = tokio::time::Instant::now() + settle + MTU_DISCOVERY_TIMEOUT;
    let (_, early_mtu) = tokio::join!(
        tokio::time::sleep(settle),
        tokio::time::timeout_at(deadline, query())
    );
    if tokio::time::Instant::now() >= deadline {
        return early_mtu.ok().flatten();
    }
    let early_mtu = early_mtu.ok().flatten();
    match early_mtu {
        // ATT's default MTU may be published before the exchange completes.
        // Refresh it after settling, but keep the known small limit if that
        // query fails rather than replacing it with the larger legacy fallback.
        Some(23) | None => tokio::time::timeout_at(deadline, query())
            .await
            .ok()
            .flatten()
            .or(early_mtu),
        Some(mtu) => Some(mtu),
    }
}

fn diagnostic_command_allowed(command: &Command) -> bool {
    matches!(
        command,
        Command::ImageSupportInfo
            | Command::BatteryStatus
            | Command::PrinterFunctionInfo
            | Command::HistoryInfo
            | Command::DownloadStart { .. }
            | Command::Data { .. }
            | Command::DownloadEnd
            | Command::DownloadCancel
    )
}

/// Real BLE transport backed by btleplug.
pub struct BleTransport {
    peripheral: Peripheral,
    write_char: Characteristic,
    rx: tokio::sync::Mutex<mpsc::Receiver<Vec<u8>>>,
    assembler: tokio::sync::Mutex<PacketAssembler>,
    command_lock: Mutex<()>,
    write_session: WriteSession,
    pacing_session: PacingSession,
    diagnostic_payload_size: NonZeroUsize,
    /// DIS Model Number string, if available.
    dis_model_number: Option<String>,
    /// Cancellation token signalled during `disconnect()` to stop the listener.
    cancel_token: CancellationToken,
    /// Confirmed link loss wakes response waits and prevents further writes.
    closed: CancellationToken,
    /// Join handle for the notification listener task.
    listener_handle: Mutex<Option<JoinHandle<()>>>,
}

impl BleTransport {
    /// Connect to a peripheral and set up characteristics and notifications.
    pub async fn connect(peripheral: Peripheral) -> Result<Self> {
        Self::connect_with_progress(peripheral, None).await
    }

    /// Connect to a peripheral and emit setup stages as progress events.
    pub async fn connect_with_progress(
        peripheral: Peripheral,
        progress: Option<&ConnectProgressCallback>,
    ) -> Result<Self> {
        let device_key = peripheral.id().to_string();
        let conservative = conservative_device(&device_key);
        let reset_required = FALLBACK_DEVICES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .requires_reset(&device_key);
        // A retained reset marker may originate from this very status RPC
        // wedging during teardown. Do not ask it again before the physical reset.
        let mut already_connected = if reset_required {
            false
        } else {
            tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, peripheral.is_connected())
                .await
                .ok()
                .and_then(|result| result.ok())
                .unwrap_or(false)
        };
        if reset_required {
            // Always attempt a bounded disconnect and require authoritative
            // disconnected state, even if the initial connection query failed.
            let _ =
                tokio::time::timeout(DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT, peripheral.disconnect())
                    .await;
            tokio::time::sleep(Duration::from_millis(250)).await;
            match tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, peripheral.is_connected()).await
            {
                Ok(Ok(false)) => already_connected = false,
                _ => {
                    return Err(PrinterError::Ble(
                        "could not reset BLE link after interrupted delivery".into(),
                    ));
                }
            }
        }
        if !already_connected {
            emit_connect_progress(progress, ConnectStage::BleConnecting, None::<String>);
            if let Err(error) = peripheral.connect().await {
                // A "connect failed: In Progress" here is the active-scan background connect still
                // completing — do NOT cancel it; the next poll cycle finds it connected. Only fall
                // back to bluetoothctl when BlueZ did not mark the device connected.
                if !peripheral.is_connected().await.unwrap_or(false) {
                    let _ = connect_with_bluez_cli(&peripheral).await;
                }
                if peripheral.is_connected().await.unwrap_or(false) {
                    log::debug!(
                        "BLE connect returned an error after BlueZ marked the device connected: {}",
                        error
                    );
                } else {
                    return Err(PrinterError::Ble(format!("connect failed: {error}")));
                }
            }
        } else {
            log::debug!("BLE peripheral already connected; reusing existing BlueZ link");
        }

        emit_connect_progress(progress, ConnectStage::ServiceDiscovery, None::<String>);
        if let Err(e) = peripheral.discover_services().await {
            log::debug!("Initial service discovery failed: {}", e);
            Self::disconnect_quietly(&peripheral, None).await;
            emit_connect_progress(progress, ConnectStage::BleConnecting, None::<String>);
            if let Err(connect_error) = peripheral.connect().await {
                if !peripheral.is_connected().await.unwrap_or(false) {
                    let _ = connect_with_bluez_cli(&peripheral).await;
                }
                if peripheral.is_connected().await.unwrap_or(false) {
                    log::debug!(
                        "BLE reconnect returned an error after BlueZ marked the device connected: {}",
                        connect_error
                    );
                } else {
                    return Err(PrinterError::Ble(format!(
                        "connect failed after service discovery retry: {connect_error}"
                    )));
                }
            }
            emit_connect_progress(progress, ConnectStage::ServiceDiscovery, None::<String>);
            if let Err(retry_error) = peripheral.discover_services().await {
                Self::disconnect_quietly(&peripheral, None).await;
                return Err(PrinterError::Ble(format!(
                    "service discovery failed: {retry_error}"
                )));
            }
        }

        emit_connect_progress(progress, ConnectStage::CharacteristicLookup, None::<String>);
        let mut chars = peripheral.characteristics();
        if !has_instax_characteristics(&chars) {
            // BlueZ exports characteristics incrementally, so a single discovery
            // pass can race ahead of the OS and miss the Instax characteristics.
            // Poll service discovery on a bounded loop until both are present,
            // the link drops, or the resolve deadline elapses.
            log::debug!(
                "Instax characteristics missing after discovery; polling characteristic lookup. chars={}",
                format_characteristic_uuids(&chars)
            );
            let deadline = tokio::time::Instant::now() + CHARACTERISTIC_RESOLVE_TIMEOUT;
            while tokio::time::Instant::now() < deadline {
                // Bail out early if the link dropped — let the upper layer reconnect.
                if !peripheral.is_connected().await.unwrap_or(false) {
                    log::debug!("BLE link dropped during characteristic resolution");
                    break;
                }

                tokio::time::sleep(CHARACTERISTIC_RESOLVE_POLL_INTERVAL).await;

                if let Err(error) = peripheral.discover_services().await {
                    // A single transient discover error must not abort the loop;
                    // BlueZ may still finish exporting on a later poll.
                    log::debug!(
                        "Characteristic lookup rediscovery failed (transient): {}",
                        error
                    );
                }

                chars = peripheral.characteristics();
                if has_instax_characteristics(&chars) {
                    break;
                }
            }
            log::debug!(
                "Instax characteristic poll result. chars={}",
                format_characteristic_uuids(&chars)
            );
        }

        let write_char = match chars
            .iter()
            .find(|c| c.uuid == WRITE_CHAR_UUID && c.service_uuid == SERVICE_UUID)
            .cloned()
        {
            Some(characteristic) => characteristic,
            None => {
                Self::disconnect_quietly(&peripheral, None).await;
                return Err(PrinterError::Ble("write characteristic not found".into()));
            }
        };

        let notify_char = match chars
            .iter()
            .find(|c| c.uuid == NOTIFY_CHAR_UUID && c.service_uuid == SERVICE_UUID)
            .cloned()
        {
            Some(characteristic) => characteristic,
            None => {
                Self::disconnect_quietly(&peripheral, None).await;
                return Err(PrinterError::Ble("notify characteristic not found".into()));
            }
        };

        // Try to read DIS Model Number characteristic for Link 3 detection
        let dis_model_number = Self::read_dis_model_number(&peripheral, &chars).await;
        if let Some(ref model) = dis_model_number {
            log::debug!("DIS Model Number: {}", model);
        }

        // Subscribe to notifications BEFORE spawning the listener task
        // so that a failed subscribe() doesn't leak a spawned task.
        emit_connect_progress(
            progress,
            ConnectStage::NotificationSubscribe,
            None::<String>,
        );
        Self::unsubscribe_quietly(&peripheral, &notify_char).await;
        tokio::time::sleep(Duration::from_millis(100)).await;
        if let Err(e) = Self::subscribe_with_retry(&peripheral, &notify_char).await {
            Self::disconnect_quietly(&peripheral, Some(&notify_char)).await;
            return Err(e);
        }

        let (tx, rx) = mpsc::channel(64);
        let mut notification_stream = match peripheral.notifications().await {
            Ok(stream) => stream,
            Err(e) => {
                Self::disconnect_quietly(&peripheral, Some(&notify_char)).await;
                return Err(PrinterError::Ble(format!(
                    "notification stream failed: {e}"
                )));
            }
        };

        let cancel_token = CancellationToken::new();
        let token_clone = cancel_token.clone();

        let handle = tokio::spawn(async move {
            log::debug!("Notification listener task started");
            loop {
                tokio::select! {
                    biased;
                    _ = token_clone.cancelled() => {
                        log::debug!("Notification listener task cancelled");
                        break;
                    }
                    item = notification_stream.next() => {
                        match item {
                            Some(notification) => {
                                log::debug!(
                                    "Got notification: {} bytes: {:02x?}",
                                    notification.value.len(),
                                    &notification.value[..notification.value.len().min(20)]
                                );
                                if tx.send(notification.value).await.is_err() {
                                    log::debug!("Notification channel closed");
                                    break;
                                }
                            }
                            None => {
                                log::debug!("Notification stream ended");
                                break;
                            }
                        }
                    }
                }
            }
            log::debug!("Notification listener task exited");
        });
        let mut listener_guard = AbortOnDrop(Some(handle));

        let negotiated_mtu =
            settle_and_read_mtu(|| negotiated_write_mtu(&peripheral, &write_char)).await;
        let payload_size = protocol::fragment_payload_size(negotiated_mtu, conservative);
        let diagnostic_payload_size =
            protocol::diagnostic_fragment_payload_size(negotiated_mtu, conservative);
        log::info!(
            "BLE write payload selected: device={} mtu={:?} payload={} conservative={}",
            device_key,
            negotiated_mtu,
            payload_size,
            conservative
        );

        if reset_required {
            FALLBACK_DEVICES
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .reset_completed(&device_key);
        }

        Ok(Self {
            peripheral,
            write_char,
            rx: tokio::sync::Mutex::new(rx),
            assembler: tokio::sync::Mutex::new(PacketAssembler::new()),
            command_lock: Mutex::new(()),
            pacing_session: PacingSession::new(device_key.clone()),
            write_session: WriteSession {
                device: device_key,
                payload_size: NonZeroUsize::new(payload_size).expect("selected payload is nonzero"),
                poisoned: AtomicBool::new(false),
                enlarged_attempted: AtomicBool::new(false),
            },
            diagnostic_payload_size: NonZeroUsize::new(diagnostic_payload_size)
                .expect("selected diagnostic payload is nonzero"),
            dis_model_number,
            cancel_token,
            closed: CancellationToken::new(),
            listener_handle: Mutex::new(listener_guard.0.take()),
        })
    }

    /// Caller holds command_lock through the entire protocol transaction.
    async fn send_bytes(&self, data: &[u8]) -> Result<()> {
        self.send_bytes_with_session(data, &self.write_session)
            .await
    }

    async fn send_bytes_with_session(&self, data: &[u8], session: &WriteSession) -> Result<()> {
        log::debug!(
            "Sending {} bytes: {:02x?}",
            data.len(),
            &data[..data.len().min(20)]
        );
        let result =
            write_fragments_on_open_link(data, session, &self.closed, |fragment| async move {
                self.peripheral
                    .write(&self.write_char, &fragment, WriteType::WithoutResponse)
                    .await
                    .map_err(|e| PrinterError::Ble(format!("write failed: {e}")))
            })
            .await;
        // A vanished link may reject the write before there is any ACK to
        // await. Check only this failure path; never probe successful chunks.
        // Unknown OS state preserves the original write error and no-replay
        // policy rather than assuming that the Printer is disconnected.
        if result.is_err() && !self.closed.is_cancelled() {
            let _ = self.query_connected().await;
        }
        result
    }

    fn mark_disconnected(&self) {
        // Invalidate before waking readers; an old Arc must never resume an
        // uncertain transfer or print actuator command on a replacement link.
        close_link(&self.write_session, &self.closed, &self.cancel_token);
    }

    async fn query_connected(&self) -> Result<bool> {
        if self.closed.is_cancelled() {
            return Ok(false);
        }
        let connected =
            tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, self.peripheral.is_connected())
                .await
                .map_err(|_| PrinterError::Timeout)?
                .map_err(|error| {
                    PrinterError::Ble(format!("connection state query failed: {error}"))
                })?;
        if !connected {
            self.mark_disconnected();
        }
        Ok(connected && !self.closed.is_cancelled())
    }

    /// Immutable payload used by ordinary production commands on this connection.
    pub fn production_payload_limit(&self) -> NonZeroUsize {
        self.write_session.payload_size
    }

    /// Current negotiated ATT write ceiling for explicit download-only diagnostics.
    /// This includes previous device-specific downgrade, but allows comparison
    /// above the production preference without changing normal sends.
    pub fn diagnostic_payload_limit(&self) -> NonZeroUsize {
        self.diagnostic_payload_size
    }

    /// Compare fragments within this connection's negotiated diagnostic ceiling
    /// without changing its production preference.
    /// Printing and other actuator commands are rejected before any write. The
    /// whole command and ACK are serialized; errors/cancellation poison the real
    /// transport and preserve the same no-replay recovery policy as normal sends.
    pub async fn diagnostic_command_with_payload_limit(
        &self,
        command: &Command,
        payload_limit: NonZeroUsize,
    ) -> Result<protocol::Packet> {
        self.diagnostic_command_with_expectation(
            command,
            payload_limit,
            command.response_expectation(),
        )
        .await
    }

    pub async fn diagnostic_command_for_model_with_payload_limit(
        &self,
        command: &Command,
        payload_limit: NonZeroUsize,
        model: PrinterModel,
    ) -> Result<protocol::Packet> {
        self.diagnostic_command_with_expectation(
            command,
            payload_limit,
            command.response_expectation_for_model(model),
        )
        .await
    }

    async fn diagnostic_command_with_expectation(
        &self,
        command: &Command,
        payload_limit: NonZeroUsize,
        expectation: Option<ResponseExpectation>,
    ) -> Result<protocol::Packet> {
        if !diagnostic_command_allowed(command) {
            return Err(PrinterError::Ble(
                "command is not allowed in download-only diagnostics".into(),
            ));
        }
        let encoded = command.encode()?;
        let expectation = expectation.ok_or_else(|| {
            PrinterError::UnexpectedResponse("diagnostic command has no response".into())
        })?;
        let _guard = self.command_lock.lock().await;
        let real_delivery = self.write_session.delivery()?;
        let session = WriteSession {
            device: self.write_session.device.clone(),
            payload_size: payload_limit.min(self.diagnostic_payload_size),
            poisoned: AtomicBool::new(false),
            enlarged_attempted: AtomicBool::new(false),
        };
        let diagnostic_delivery = session.delivery()?;
        self.send_bytes_with_session(&encoded, &session).await?;
        let packet = receive_expected_from_transport(self, DEFAULT_TIMEOUT, expectation).await?;
        self.pacing_session.record_ack(&packet);
        diagnostic_delivery.complete();
        real_delivery.complete();
        Ok(packet)
    }

    /// Try to read the DIS Model Number characteristic from the peripheral.
    async fn read_dis_model_number(
        peripheral: &Peripheral,
        chars: &std::collections::BTreeSet<Characteristic>,
    ) -> Option<String> {
        let dis_char = chars.iter().find(|c| c.uuid == DIS_MODEL_NUMBER_UUID)?;
        match peripheral.read(dis_char).await {
            Ok(data) => {
                let s = String::from_utf8_lossy(&data).trim().to_string();
                if s.is_empty() { None } else { Some(s) }
            }
            Err(e) => {
                log::debug!("Failed to read DIS Model Number: {e}");
                None
            }
        }
    }

    async fn disconnect_quietly(peripheral: &Peripheral, notify_char: Option<&Characteristic>) {
        if let Some(notify_char) = notify_char {
            Self::unsubscribe_quietly(peripheral, notify_char).await;
        }
        let is_connected =
            tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, peripheral.is_connected())
                .await
                .ok()
                .and_then(|result| result.ok())
                .unwrap_or(false);
        if is_connected {
            let _ =
                tokio::time::timeout(DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT, peripheral.disconnect())
                    .await;
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
    }

    async fn subscribe_with_retry(
        peripheral: &Peripheral,
        notify_char: &Characteristic,
    ) -> Result<()> {
        if let Err(first_error) = peripheral.subscribe(notify_char).await {
            let first_error_text = first_error.to_string();
            log::debug!(
                "notification subscribe failed once; clearing stale notify state before retry: {}",
                first_error_text
            );
            Self::unsubscribe_quietly(peripheral, notify_char).await;
            tokio::time::sleep(Duration::from_millis(500)).await;
            if let Err(retry_error) = peripheral.subscribe(notify_char).await {
                return Err(PrinterError::Ble(format!(
                    "notification subscribe failed: {retry_error}; first attempt: {first_error_text}"
                )));
            }
        }
        Ok(())
    }

    async fn unsubscribe_quietly(peripheral: &Peripheral, notify_char: &Characteristic) {
        let _ = tokio::time::timeout(
            DEFAULT_DISCONNECT_TIMEOUT,
            peripheral.unsubscribe(notify_char),
        )
        .await;
    }

    /// Cancel the listener task and wait for it to exit, aborting if it takes too long.
    async fn shutdown_listener(&self) {
        self.cancel_token.cancel();
        let handle = self.listener_handle.lock().await.take();
        if let Some(mut handle) = handle {
            match tokio::time::timeout(LISTENER_SHUTDOWN_TIMEOUT, &mut handle).await {
                Ok(_) => log::debug!("Notification listener exited gracefully"),
                Err(_) => {
                    log::debug!("Notification listener did not exit in time; aborting");
                    handle.abort();
                }
            }
        }
    }
}

fn has_instax_characteristics(chars: &std::collections::BTreeSet<Characteristic>) -> bool {
    chars
        .iter()
        .any(|c| c.uuid == WRITE_CHAR_UUID && c.service_uuid == SERVICE_UUID)
        && chars
            .iter()
            .any(|c| c.uuid == NOTIFY_CHAR_UUID && c.service_uuid == SERVICE_UUID)
}

fn format_characteristic_uuids(chars: &std::collections::BTreeSet<Characteristic>) -> String {
    if chars.is_empty() {
        return "none".to_string();
    }
    chars
        .iter()
        .map(|c| c.uuid.to_string())
        .collect::<Vec<_>>()
        .join(",")
}

#[cfg(target_os = "linux")]
async fn connect_with_bluez_cli(peripheral: &Peripheral) -> bool {
    let device_id = bluetoothctl_device_id(peripheral);
    let child = tokio::process::Command::new("bluetoothctl")
        .arg("connect")
        .arg(&device_id)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .spawn();

    let output = match child {
        Ok(child) => {
            match tokio::time::timeout(BLUETOOTHCTL_CONNECT_TIMEOUT, child.wait_with_output()).await
            {
                Ok(Ok(output)) => output,
                Ok(Err(error)) => {
                    log::debug!(
                        "failed to run bluetoothctl connect for {}: {}",
                        device_id,
                        error
                    );
                    return false;
                }
                Err(_) => {
                    log::debug!("bluetoothctl connect timed out for {}", device_id);
                    return false;
                }
            }
        }
        Err(error) => {
            log::debug!(
                "failed to run bluetoothctl connect for {}: {}",
                device_id,
                error
            );
            return false;
        }
    };

    if output.status.success() {
        log::debug!("bluetoothctl connected BLE device {}", device_id);
        true
    } else {
        log::debug!(
            "bluetoothctl connect failed for {}: status={} stdout={} stderr={}",
            device_id,
            output.status,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        false
    }
}

#[cfg(target_os = "linux")]
fn bluetoothctl_device_id(peripheral: &Peripheral) -> String {
    let id = peripheral.id().to_string();
    if let Some((_prefix, address)) = id.rsplit_once("dev_") {
        return address.replace('_', ":");
    }
    id
}

#[cfg(not(target_os = "linux"))]
async fn connect_with_bluez_cli(_peripheral: &Peripheral) -> bool {
    false
}

impl Drop for BleTransport {
    fn drop(&mut self) {
        // Signal cancellation as a last-resort safety net. If the listener task
        // is still running it will see the token and exit on its next select poll.
        self.cancel_token.cancel();
        // Abort the task immediately if still running — this is synchronous and
        // safe to call from Drop even outside an async context.
        if let Ok(mut guard) = self.listener_handle.try_lock()
            && let Some(handle) = guard.take()
        {
            handle.abort();
        }
    }
}

#[async_trait]
impl Transport for BleTransport {
    fn known_disconnected(&self) -> bool {
        self.closed.is_cancelled()
    }

    async fn send(&self, data: &[u8]) -> Result<()> {
        let _guard = self.command_lock.lock().await;
        self.send_bytes(data).await
    }

    async fn receive(&self, timeout: Duration) -> Result<protocol::Packet> {
        let mut rx = self.rx.lock().await;
        let mut assembler = self.assembler.lock().await;
        let result =
            receive_packet_with_link_checks(&mut rx, &mut assembler, timeout, &self.closed, || {
                self.query_connected()
            })
            .await;
        // An ended notification channel also makes this local session unusable,
        // even when the OS has not yet reported physical disconnection.
        if matches!(&result, Err(PrinterError::Ble(_))) {
            self.mark_disconnected();
        }
        result
    }

    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<protocol::Packet> {
        let _guard = self.command_lock.lock().await;
        let delivery = self.write_session.delivery()?;
        self.send_bytes(data).await?;
        let packet = self.receive(timeout).await?;
        self.pacing_session.record_ack(&packet);
        delivery.complete();
        Ok(packet)
    }

    async fn send_and_receive_expected(
        &self,
        data: &[u8],
        timeout: Duration,
        expectation: ResponseExpectation,
    ) -> Result<protocol::Packet> {
        let _guard = self.command_lock.lock().await;
        let delivery = self.write_session.delivery()?;
        self.send_bytes(data).await?;
        let packet = receive_expected_from_transport(self, timeout, expectation).await?;
        self.pacing_session.record_ack(&packet);
        delivery.complete();
        Ok(packet)
    }

    async fn disconnect(&self) -> Result<()> {
        // Close this transport before any await. Even cancellation by the FFI
        // deadline must not allow its old session to send or be blindly reused.
        let reset_guard = LinkResetGuard {
            session: &self.write_session,
            armed: true,
        };
        self.mark_disconnected();
        // Shut down the listener before touching the peripheral so it doesn't
        // try to forward notifications after the BLE connection is gone.
        self.shutdown_listener().await;

        // Prioritize physical disconnect over StopNotify within the outer FFI
        // deadline. BlueZ may retain notification ownership across a disconnect;
        // setup clears it before every subsequent subscription.
        disconnect_and_verify(
            || async {
                self.peripheral
                    .disconnect()
                    .await
                    .map_err(|e| PrinterError::Ble(format!("disconnect failed: {e}")))
            },
            || async {
                self.peripheral
                    .is_connected()
                    .await
                    .map_err(|e| PrinterError::Ble(format!("disconnect verification failed: {e}")))
            },
        )
        .await?;
        FALLBACK_DEVICES
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .reset_completed(&self.write_session.device);
        reset_guard.complete();
        Ok(())
    }

    fn data_packet_delay_ms(&self, model: PrinterModel) -> u64 {
        data_packet_delay_ms_for_context(
            model,
            cfg!(target_os = "linux"),
            self.write_session.payload_size.get(),
            self.pacing_session.legacy_ack_seen.load(Ordering::Acquire),
            self.pacing_session.disabled.load(Ordering::Acquire),
        )
    }
    fn image_transfer_started(&self) {
        self.pacing_session.started();
    }
    fn image_transfer_completed(&self) {
        self.pacing_session.completed();
    }
    fn image_transfer_failed(&self) {
        self.pacing_session.failed(&self.write_session);
    }
    fn image_transfer_rejected(&self) {
        self.write_session.require_link_reset();
        self.pacing_session.completed();
    }
    fn fast_chunk_gap_used(&self) {
        self.pacing_session
            .fast_gap_used
            .store(true, Ordering::Release);
    }

    fn model_number_hint(&self) -> Option<&str> {
        self.dis_model_number.as_deref()
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;

    fn make_char(uuid: Uuid) -> Characteristic {
        Characteristic {
            uuid,
            service_uuid: SERVICE_UUID,
            properties: btleplug::api::CharPropFlags::empty(),
            descriptors: std::collections::BTreeSet::new(),
        }
    }

    #[tokio::test(start_paused = true)]
    async fn mtu_metadata_lookup_overlaps_but_preserves_minimum_settle() {
        let queries = AtomicUsize::new(0);
        let started = tokio::time::Instant::now();
        let mtu = settle_and_read_mtu(|| async {
            queries.fetch_add(1, Ordering::Relaxed);
            tokio::time::sleep(Duration::from_millis(75)).await;
            Some(247)
        })
        .await;
        assert_eq!(mtu, Some(247));
        assert_eq!(queries.load(Ordering::Relaxed), 1);
        assert_eq!(started.elapsed(), Duration::from_millis(200));
    }

    #[tokio::test(start_paused = true)]
    async fn mtu_publication_race_retries_only_after_settle() {
        let queries = AtomicUsize::new(0);
        let started = tokio::time::Instant::now();
        let mtu = settle_and_read_mtu(|| async {
            let attempt = queries.fetch_add(1, Ordering::Relaxed);
            if attempt == 0 {
                assert_eq!(started.elapsed(), Duration::ZERO);
                None
            } else {
                assert_eq!(started.elapsed(), Duration::from_millis(200));
                tokio::time::sleep(Duration::from_millis(25)).await;
                Some(247)
            }
        })
        .await;
        assert_eq!(mtu, Some(247));
        assert_eq!(queries.load(Ordering::Relaxed), 2);
        assert_eq!(started.elapsed(), Duration::from_millis(225));
    }

    #[tokio::test(start_paused = true)]
    async fn default_att_mtu_is_refreshed_but_never_replaced_by_larger_fallback() {
        for late_mtu in [Some(247), None] {
            let queries = AtomicUsize::new(0);
            let started = tokio::time::Instant::now();
            let mtu = settle_and_read_mtu(|| async {
                if queries.fetch_add(1, Ordering::Relaxed) == 0 {
                    Some(23)
                } else {
                    assert_eq!(started.elapsed(), Duration::from_millis(200));
                    late_mtu
                }
            })
            .await;
            assert_eq!(mtu, late_mtu.or(Some(23)));
            assert_eq!(queries.load(Ordering::Relaxed), 2);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn slower_mtu_query_finishes_within_original_budget_without_extra_settle() {
        let started = tokio::time::Instant::now();
        let mtu = settle_and_read_mtu(|| async {
            tokio::time::sleep(Duration::from_millis(300)).await;
            Some(247)
        })
        .await;
        assert_eq!(mtu, Some(247));
        assert_eq!(started.elapsed(), Duration::from_millis(300));
    }

    #[tokio::test(start_paused = true)]
    async fn mtu_missing_or_unavailable_retains_safe_fallback_and_one_total_budget() {
        let queries = AtomicUsize::new(0);
        let started = tokio::time::Instant::now();
        let mtu = settle_and_read_mtu(|| async {
            queries.fetch_add(1, Ordering::Relaxed);
            tokio::time::sleep(MTU_DISCOVERY_TIMEOUT).await;
            None
        })
        .await;
        assert_eq!(mtu, None);
        assert_eq!(queries.load(Ordering::Relaxed), 2);
        assert_eq!(started.elapsed(), Duration::from_millis(1200));

        let started = tokio::time::Instant::now();
        assert_eq!(settle_and_read_mtu(|| async { None }).await, None);
        assert_eq!(started.elapsed(), Duration::from_millis(200));
    }

    #[tokio::test(start_paused = true)]
    async fn cancelling_mtu_setup_drops_query_without_background_work() {
        struct QueryDrop<'a>(&'a AtomicUsize);
        impl Drop for QueryDrop<'_> {
            fn drop(&mut self) {
                self.0.fetch_sub(1, Ordering::Relaxed);
            }
        }
        for cancel_after in [50, 300] {
            let active = AtomicUsize::new(0);
            let queries = AtomicUsize::new(0);
            let result = tokio::time::timeout(
                Duration::from_millis(cancel_after),
                settle_and_read_mtu(|| async {
                    let attempt = queries.fetch_add(1, Ordering::Relaxed);
                    if cancel_after == 300 && attempt == 0 {
                        return None;
                    }
                    active.fetch_add(1, Ordering::Relaxed);
                    let _owned = QueryDrop(&active);
                    std::future::pending::<Option<u16>>().await
                }),
            )
            .await;
            assert!(result.is_err());
            assert_eq!(active.load(Ordering::Relaxed), 0);
            assert_eq!(
                queries.load(Ordering::Relaxed),
                usize::from(cancel_after == 300) + 1
            );
        }
    }

    #[tokio::test(start_paused = true)]
    async fn wedged_early_mtu_query_is_bounded_without_starting_late_retry() {
        let queries = AtomicUsize::new(0);
        let started = tokio::time::Instant::now();
        let mtu = settle_and_read_mtu(|| async {
            queries.fetch_add(1, Ordering::Relaxed);
            std::future::pending::<Option<u16>>().await
        })
        .await;
        assert_eq!(mtu, None);
        assert_eq!(queries.load(Ordering::Relaxed), 1);
        assert_eq!(started.elapsed(), Duration::from_millis(1200));
    }

    #[tokio::test(start_paused = true)]
    async fn fast_response_does_not_query_link_state() {
        let (tx, mut rx) = mpsc::channel(1);
        tx.send(protocol::build_packet(0x1234, &[1]).unwrap())
            .await
            .unwrap();
        let packet = receive_packet_with_link_checks(
            &mut rx,
            &mut PacketAssembler::new(),
            DEFAULT_TIMEOUT,
            &CancellationToken::new(),
            || async { panic!("successful ACK must not query BlueZ") },
        )
        .await
        .unwrap();
        assert_eq!(packet.opcode, 0x1234);
    }

    #[tokio::test(start_paused = true)]
    async fn outstanding_response_fails_on_confirmed_disconnect_after_one_second() {
        let (_tx, mut rx) = mpsc::channel(1);
        let calls = AtomicUsize::new(0);
        let started = tokio::time::Instant::now();
        let error = receive_packet_with_link_checks(
            &mut rx,
            &mut PacketAssembler::new(),
            DEFAULT_TIMEOUT,
            &CancellationToken::new(),
            || async {
                calls.fetch_add(1, Ordering::SeqCst);
                Ok(false)
            },
        )
        .await
        .unwrap_err();
        assert!(matches!(error, PrinterError::Ble(_)));
        assert_eq!(started.elapsed(), Duration::from_secs(1));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test(start_paused = true)]
    async fn query_errors_and_live_links_keep_original_response_deadline() {
        let (_tx, mut rx) = mpsc::channel(1);
        let calls = AtomicUsize::new(0);
        let started = tokio::time::Instant::now();
        let error = receive_packet_with_link_checks(
            &mut rx,
            &mut PacketAssembler::new(),
            Duration::from_millis(3500),
            &CancellationToken::new(),
            || async {
                if calls.fetch_add(1, Ordering::SeqCst) == 0 {
                    Err(PrinterError::Ble("state unavailable".into()))
                } else {
                    Ok(true)
                }
            },
        )
        .await
        .unwrap_err();
        assert!(matches!(error, PrinterError::Timeout));
        assert_eq!(started.elapsed(), Duration::from_millis(3500));
        assert_eq!(calls.load(Ordering::SeqCst), 3);
    }

    #[tokio::test(start_paused = true)]
    async fn wedged_query_neither_extends_deadline_nor_leaks_after_ack() {
        let (tx, mut rx) = mpsc::channel(1);
        let active = Arc::new(AtomicUsize::new(0));
        struct ActiveQuery(Arc<AtomicUsize>);
        impl Drop for ActiveQuery {
            fn drop(&mut self) {
                self.0.fetch_sub(1, Ordering::SeqCst);
            }
        }
        let sender = tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(1500)).await;
            tx.send(protocol::build_packet(0x5678, &[2]).unwrap())
                .await
                .unwrap();
        });
        let packet = receive_packet_with_link_checks(
            &mut rx,
            &mut PacketAssembler::new(),
            DEFAULT_TIMEOUT,
            &CancellationToken::new(),
            || async {
                active.fetch_add(1, Ordering::SeqCst);
                let _guard = ActiveQuery(Arc::clone(&active));
                std::future::pending::<Result<bool>>().await
            },
        )
        .await
        .unwrap();
        sender.await.unwrap();
        assert_eq!(packet.opcode, 0x5678);
        assert_eq!(active.load(Ordering::SeqCst), 0);

        let (_tx, mut rx) = mpsc::channel(1);
        let started = tokio::time::Instant::now();
        let error = receive_packet_with_link_checks(
            &mut rx,
            &mut PacketAssembler::new(),
            Duration::from_millis(4500),
            &CancellationToken::new(),
            std::future::pending::<Result<bool>>,
        )
        .await
        .unwrap_err();
        assert!(matches!(error, PrinterError::Timeout));
        assert_eq!(started.elapsed(), Duration::from_millis(4500));
    }

    #[tokio::test(start_paused = true)]
    async fn closed_session_wakes_waiters_but_queued_ack_wins() {
        let closed = CancellationToken::new();
        closed.cancel();
        let (tx, mut rx) = mpsc::channel(1);
        let mut assembler = PacketAssembler::new();
        tx.send(protocol::build_packet(0x4321, &[3]).unwrap())
            .await
            .unwrap();
        let packet = receive_packet_with_link_checks(
            &mut rx,
            &mut assembler,
            DEFAULT_TIMEOUT,
            &closed,
            || async { panic!("closed session must not probe") },
        )
        .await
        .unwrap();
        assert_eq!(packet.opcode, 0x4321);
        let started = tokio::time::Instant::now();
        let error = receive_packet_with_link_checks(
            &mut rx,
            &mut assembler,
            DEFAULT_TIMEOUT,
            &closed,
            || async { panic!("closed session must not probe") },
        )
        .await
        .unwrap_err();
        assert!(matches!(error, PrinterError::Ble(_)));
        assert!(started.elapsed().is_zero());
    }

    #[tokio::test(start_paused = true)]
    async fn cancellation_drops_pending_state_query_without_background_work() {
        let (_tx, mut rx) = mpsc::channel(1);
        let active = Arc::new(AtomicUsize::new(0));
        struct ActiveQuery(Arc<AtomicUsize>);
        impl Drop for ActiveQuery {
            fn drop(&mut self) {
                self.0.fetch_sub(1, Ordering::SeqCst);
            }
        }
        let mut assembler = PacketAssembler::new();
        let closed = CancellationToken::new();
        let result = tokio::time::timeout(
            Duration::from_millis(1500),
            receive_packet_with_link_checks(
                &mut rx,
                &mut assembler,
                DEFAULT_TIMEOUT,
                &closed,
                || async {
                    active.fetch_add(1, Ordering::SeqCst);
                    let _guard = ActiveQuery(Arc::clone(&active));
                    std::future::pending::<Result<bool>>().await
                },
            ),
        )
        .await;
        assert!(result.is_err());
        assert_eq!(active.load(Ordering::SeqCst), 0);
        assert!(
            !closed.is_cancelled(),
            "cancelled query cannot assert a lost link"
        );
    }

    #[tokio::test]
    async fn scan_evidence_accepts_rssi_without_polling_connected_state() {
        let deadline = tokio::time::Instant::now();
        let connected = async {
            panic!("RSSI evidence must not spend a connected-state query");
            #[allow(unreachable_code)]
            Ok::<bool, &str>(false)
        };
        assert!(linux_scan_candidate_has_evidence(Some(-70), connected, deadline).await);
    }

    #[tokio::test]
    async fn scan_evidence_keeps_connected_printer_without_rssi() {
        let deadline = tokio::time::Instant::now() + Duration::from_millis(250);
        assert!(
            linux_scan_candidate_has_evidence(None, async { Ok::<_, &str>(true) }, deadline).await
        );
    }

    #[tokio::test]
    async fn scan_evidence_excludes_known_disconnected_and_unknown_records() {
        let deadline = tokio::time::Instant::now() + Duration::from_millis(250);
        assert!(
            !linux_scan_candidate_has_evidence(None, async { Ok::<_, &str>(false) }, deadline)
                .await
        );
        assert!(
            !linux_scan_candidate_has_evidence(
                None,
                async { Err::<bool, _>("query failed") },
                deadline
            )
            .await
        );
    }

    #[tokio::test(start_paused = true)]
    async fn scan_evidence_cached_queries_share_deadline_instead_of_multiplying_waits() {
        let started = tokio::time::Instant::now();
        let deadline = started + Duration::from_millis(250);
        for _ in 0..3 {
            assert!(
                !linux_scan_candidate_has_evidence(
                    None,
                    std::future::pending::<std::result::Result<bool, &str>>(),
                    deadline,
                )
                .await
            );
        }
        assert_eq!(
            tokio::time::Instant::now() - started,
            Duration::from_millis(250)
        );
    }

    #[test]
    fn has_instax_characteristics_requires_both_write_and_notify() {
        use std::collections::BTreeSet;

        // Empty set: neither present.
        let empty: BTreeSet<Characteristic> = BTreeSet::new();
        assert!(!has_instax_characteristics(&empty));

        // Only the write characteristic exported so far.
        let mut write_only = BTreeSet::new();
        write_only.insert(make_char(WRITE_CHAR_UUID));
        assert!(!has_instax_characteristics(&write_only));

        // Only the notify characteristic exported so far.
        let mut notify_only = BTreeSet::new();
        notify_only.insert(make_char(NOTIFY_CHAR_UUID));
        assert!(!has_instax_characteristics(&notify_only));

        // Unrelated characteristic only.
        let mut other = BTreeSet::new();
        other.insert(make_char(DIS_MODEL_NUMBER_UUID));
        assert!(!has_instax_characteristics(&other));

        // Both Instax characteristics present (plus an unrelated one).
        let mut both = BTreeSet::new();
        both.insert(make_char(WRITE_CHAR_UUID));
        both.insert(make_char(NOTIFY_CHAR_UUID));
        both.insert(make_char(DIS_MODEL_NUMBER_UUID));
        assert!(has_instax_characteristics(&both));
    }

    #[test]
    fn detects_android_spp_advertisement_names() {
        assert!(is_android_advertisement("INSTAX-52006924 (ANDROID)"));
        assert!(is_android_advertisement(" INSTAX-52006924(ANDROID) "));
        assert!(!is_android_advertisement("INSTAX-52006924 (IOS)"));
        assert!(!is_android_advertisement("INSTAX-52006924"));
    }

    #[tokio::test(start_paused = true)]
    async fn receive_packet_from_channel_uses_total_deadline_across_fragments() {
        let (tx, mut rx) = mpsc::channel(4);
        let mut assembler = PacketAssembler::new();
        let packet = protocol::build_packet(0x1234, &[0xAB; 176]).unwrap();
        let fragments = protocol::fragment(&packet);
        assert!(
            fragments.len() > 1,
            "test packet must span multiple fragments"
        );

        let sender = tokio::spawn(async move {
            tx.send(fragments[0].clone()).await.unwrap();
            tokio::time::sleep(Duration::from_millis(40)).await;
            tx.send(fragments[1].clone()).await.unwrap();
        });

        let start = tokio::time::Instant::now();
        let err = receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(25))
            .await
            .unwrap_err();
        sender.await.unwrap();

        assert!(matches!(err, PrinterError::Timeout));
        assert!(start.elapsed() < Duration::from_millis(60));
    }

    #[tokio::test]
    async fn receive_packet_from_channel_returns_packet_when_fragments_arrive_in_time() {
        let (tx, mut rx) = mpsc::channel(4);
        let mut assembler = PacketAssembler::new();
        let packet = protocol::build_packet(0x1234, &[0xAA, 0xBB]).unwrap();
        let fragments = protocol::fragment(&packet);

        let sender = tokio::spawn(async move {
            for fragment in fragments {
                tx.send(fragment).await.unwrap();
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        });

        let received =
            receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(100))
                .await
                .unwrap();
        sender.await.unwrap();

        assert_eq!(received.opcode, 0x1234);
        assert_eq!(received.payload, vec![0xAA, 0xBB]);
    }

    #[tokio::test]
    async fn receive_packet_from_channel_returns_buffered_packet_without_waiting() {
        let (_tx, mut rx) = mpsc::channel(1);
        let first = protocol::build_packet(0x1111, &[0x00]).unwrap();
        let second = protocol::build_packet(0x4321, &[0x01, 0x02, 0x03]).unwrap();
        let mut assembler = PacketAssembler::new();
        let mut combined = first;
        combined.extend_from_slice(&second);
        let initial = assembler
            .feed(&combined)
            .expect("should not error")
            .unwrap();
        assert_eq!(initial.opcode, 0x1111);

        let received =
            receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(10))
                .await
                .unwrap();

        assert_eq!(received.opcode, 0x4321);
        assert_eq!(received.payload, vec![0x01, 0x02, 0x03]);
    }

    #[tokio::test]
    async fn receive_packet_from_channel_errors_when_notification_channel_closes() {
        let (tx, mut rx) = mpsc::channel::<Vec<u8>>(1);
        let mut assembler = PacketAssembler::new();
        drop(tx);

        let err = receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(20))
            .await
            .unwrap_err();

        assert!(
            matches!(err, PrinterError::Ble(message) if message == "notification channel closed")
        );
    }

    /// Corrupt data (bad header) must not abort the receive loop — the next
    /// valid packet should still arrive.
    #[tokio::test]
    async fn receive_packet_from_channel_logs_corruption_then_resumes() {
        let (tx, mut rx) = mpsc::channel(8);
        let mut assembler = PacketAssembler::new();

        // Corrupt fragment: invalid header bytes followed by a valid packet.
        let corrupt: Vec<u8> = vec![0xDE, 0xAD, 0x00, 0x07, 0x00, 0x00, 0x00];
        let valid = protocol::build_packet(0xCAFE, &[0x42]).unwrap();

        let sender = tokio::spawn(async move {
            tx.send(corrupt).await.unwrap();
            tokio::time::sleep(Duration::from_millis(5)).await;
            tx.send(valid).await.unwrap();
        });

        let received =
            receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(200))
                .await
                .expect("should receive valid packet after corruption");
        sender.await.unwrap();

        assert_eq!(received.opcode, 0xCAFE);
        assert_eq!(received.payload, vec![0x42]);
    }

    /// Persistent corruption with no valid packet in sight must ultimately
    /// time out rather than loop forever.
    #[tokio::test(start_paused = true)]
    async fn receive_packet_from_channel_surfaces_persistent_corruption() {
        let (tx, mut rx) = mpsc::channel(8);
        let mut assembler = PacketAssembler::new();

        // Keep sending corrupt data; never send a valid packet.
        let sender = tokio::spawn(async move {
            for _ in 0..5u8 {
                tx.send(vec![0xDE, 0xAD, 0x00, 0x07]).await.unwrap();
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
        });

        let err = receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(10))
            .await
            .unwrap_err();
        sender.await.unwrap();

        assert!(matches!(err, PrinterError::Timeout));
    }

    #[tokio::test]
    async fn receive_packet_from_channel_resets_partial_buffer_after_timeout() {
        let (tx, mut rx) = mpsc::channel(8);
        let mut assembler = PacketAssembler::new();

        // Valid response header + huge declared length. Without a reset on
        // timeout, this partial frame poisons the assembler for every later
        // receive call.
        tx.send(vec![
            protocol::RESPONSE_HEADER[0],
            protocol::RESPONSE_HEADER[1],
            0xFF,
            0xFF,
        ])
        .await
        .unwrap();

        let err = receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(10))
            .await
            .unwrap_err();
        assert!(matches!(err, PrinterError::Timeout));

        let valid = protocol::build_packet(0xCAFE, &[0x42]).unwrap();
        tx.send(valid).await.unwrap();

        let received =
            receive_packet_from_channel(&mut rx, &mut assembler, Duration::from_millis(100))
                .await
                .expect(
                    "valid packet after timeout should not be hidden behind stale partial data",
                );
        assert_eq!(received.opcode, 0xCAFE);
        assert_eq!(received.payload, vec![0x42]);
    }

    /// A fake "never-ending" notification source: a task that loops forever
    /// sending to a channel, paired with the receive end as the "stream".
    ///
    /// Returns `(cancel_token, join_handle, task_active_flag)`.
    /// The task increments a counter each iteration and only stops when the
    /// token is cancelled.
    fn spawn_infinite_listener(
        token: CancellationToken,
        active_counter: Arc<AtomicUsize>,
    ) -> JoinHandle<()> {
        tokio::spawn(async move {
            active_counter.fetch_add(1, Ordering::SeqCst);
            loop {
                tokio::select! {
                    biased;
                    _ = token.cancelled() => break,
                    _ = tokio::time::sleep(Duration::from_millis(10)) => {}
                }
            }
            active_counter.fetch_sub(1, Ordering::SeqCst);
        })
    }

    /// Listener exits within a bounded time after the cancellation token is fired.
    #[tokio::test]
    async fn listener_exits_promptly_after_cancellation() {
        let token = CancellationToken::new();
        let active = Arc::new(AtomicUsize::new(0));
        let handle = spawn_infinite_listener(token.clone(), Arc::clone(&active));

        // Give the task a moment to start.
        tokio::time::sleep(Duration::from_millis(20)).await;
        assert_eq!(active.load(Ordering::SeqCst), 1, "task should be active");

        token.cancel();

        // Should finish well within the 250 ms shutdown timeout.
        tokio::time::timeout(LISTENER_SHUTDOWN_TIMEOUT, handle)
            .await
            .expect("listener task did not exit within the shutdown timeout")
            .expect("listener task panicked");

        assert_eq!(active.load(Ordering::SeqCst), 0, "task should have exited");
    }

    /// A listener that ignores the cancel token is aborted by `shutdown_listener`
    /// after the timeout elapses.
    #[tokio::test]
    async fn shutdown_listener_aborts_non_cancellable_task() {
        let cancel_token = CancellationToken::new();
        let listener_handle: Arc<Mutex<Option<JoinHandle<()>>>> = Arc::new(Mutex::new(None));

        // Spawn a task that deliberately ignores the cancel token.
        let handle = tokio::spawn(async {
            loop {
                tokio::time::sleep(Duration::from_secs(60)).await;
            }
        });
        *listener_handle.lock().await = Some(handle);

        // Build a minimal BleTransport-like struct to call shutdown_listener.
        // Since BleTransport fields are private we replicate the shutdown logic directly.
        cancel_token.cancel();
        let handle = listener_handle.lock().await.take();
        if let Some(mut handle) = handle {
            match tokio::time::timeout(LISTENER_SHUTDOWN_TIMEOUT, &mut handle).await {
                Ok(_) => {}
                Err(_) => {
                    handle.abort();
                }
            }
            // Give the runtime a moment to process the abort.
            tokio::time::sleep(Duration::from_millis(10)).await;
            assert!(handle.is_finished(), "task must be finished after abort");
        } else {
            panic!("handle was not stored");
        }
    }

    /// Repeated connect/disconnect cycles (simulated) do not pile up live tasks.
    #[tokio::test]
    async fn repeated_cycles_do_not_accumulate_tasks() {
        let active = Arc::new(AtomicUsize::new(0));

        for _ in 0..10 {
            let token = CancellationToken::new();
            let handle = spawn_infinite_listener(token.clone(), Arc::clone(&active));

            // Simulate a brief "connected" window.
            tokio::time::sleep(Duration::from_millis(5)).await;

            // Simulate disconnect: cancel + join with timeout, abort on timeout.
            token.cancel();
            match tokio::time::timeout(LISTENER_SHUTDOWN_TIMEOUT, handle).await {
                Ok(_) => {}
                Err(_elapsed) => {
                    // In real code the handle would be aborted here; for this test
                    // the token cancellation is always fast enough, so we just fail.
                    panic!("task did not exit within shutdown timeout on a cycle");
                }
            }
        }

        // All tasks must be gone by now.
        assert_eq!(
            active.load(Ordering::SeqCst),
            0,
            "no listener tasks should remain after all cycles"
        );
    }
}

#[cfg(test)]
#[path = "transport_adversarial_tests.rs"]
mod adversarial_tests;
