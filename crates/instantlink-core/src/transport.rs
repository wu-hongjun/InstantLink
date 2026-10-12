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

use crate::commands::{Command, ResponseExpectation};
use crate::connect_progress::{ConnectProgressCallback, ConnectStage, emit_connect_progress};
use crate::error::{PrinterError, Result};
use crate::protocol::{self, PacketAssembler};

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
/// Timeout for BLE disconnect/cleanup operations.
pub const DEFAULT_DISCONNECT_TIMEOUT: Duration = Duration::from_secs(2);

/// Timeout to wait for the listener task to exit gracefully after cancellation.
const LISTENER_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(250);
#[cfg(target_os = "linux")]
const MTU_DISCOVERY_TIMEOUT: Duration = Duration::from_secs(1);
#[cfg(target_os = "linux")]
static MTU_BUS_OPEN: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(1);
const MAX_FALLBACK_DEVICES: usize = 128;

#[derive(Default)]
struct FallbackDevices {
    devices: BTreeMap<String, bool>,
    reset_required: std::collections::BTreeSet<String>,
    /// Once capacity is reached, use conservative fragments for all new devices
    /// rather than evicting a device whose larger writes were unsafe.
    saturated: bool,
}

static FALLBACK_DEVICES: LazyLock<StdMutex<FallbackDevices>> =
    LazyLock::new(|| StdMutex::new(FallbackDevices::default()));

impl FallbackDevices {
    fn contains(&self, device: &str) -> bool {
        self.saturated || self.devices.get(device).copied().unwrap_or(false)
    }

    fn requires_reset(&self, device: &str) -> bool {
        self.saturated || self.reset_required.contains(device)
    }

    fn reset_completed(&mut self, device: &str) {
        self.reset_required.remove(device);
        if self.devices.get(device) == Some(&false) {
            self.devices.remove(device);
        }
    }

    fn insert(&mut self, device: &str, enlarged: bool) {
        if let Some(conservative) = self.devices.get_mut(device) {
            *conservative |= enlarged;
            self.reset_required.insert(device.to_owned());
        } else if self.devices.len() < MAX_FALLBACK_DEVICES {
            self.devices.insert(device.to_owned(), enlarged);
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
        match tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, disconnect()).await {
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
/// scan started by [`start_scan`] is still running.
pub async fn collect_instax_peripherals(adapter: &Adapter) -> Result<Vec<(Peripheral, String)>> {
    let peripherals = adapter
        .peripherals()
        .await
        .map_err(|e| PrinterError::Ble(format!("failed to list peripherals: {e}")))?;

    let mut results = Vec::new();
    for p in peripherals {
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
                results.push((p, display_name));
            }
        }
    }

    Ok(results)
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
    diagnostic_payload_size: NonZeroUsize,
    /// DIS Model Number string, if available.
    dis_model_number: Option<String>,
    /// Cancellation token signalled during `disconnect()` to stop the listener.
    cancel_token: CancellationToken,
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
            let _ = tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, peripheral.disconnect()).await;
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

        // Brief delay to let the BLE connection stabilize
        tokio::time::sleep(Duration::from_millis(200)).await;

        let negotiated_mtu = negotiated_write_mtu(&peripheral, &write_char).await;
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
        write_fragments(data, session, |fragment| async move {
            self.peripheral
                .write(&self.write_char, &fragment, WriteType::WithoutResponse)
                .await
                .map_err(|e| PrinterError::Ble(format!("write failed: {e}")))
        })
        .await
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
        if !diagnostic_command_allowed(command) {
            return Err(PrinterError::Ble(
                "command is not allowed in download-only diagnostics".into(),
            ));
        }
        let encoded = command.encode()?;
        let expectation = command.response_expectation().ok_or_else(|| {
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
            let _ = tokio::time::timeout(DEFAULT_DISCONNECT_TIMEOUT, peripheral.disconnect()).await;
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
    async fn send(&self, data: &[u8]) -> Result<()> {
        let _guard = self.command_lock.lock().await;
        self.send_bytes(data).await
    }

    async fn receive(&self, timeout: Duration) -> Result<protocol::Packet> {
        let mut rx = self.rx.lock().await;
        let mut assembler = self.assembler.lock().await;
        receive_packet_from_channel(&mut rx, &mut assembler, timeout).await
    }

    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<protocol::Packet> {
        let _guard = self.command_lock.lock().await;
        let delivery = self.write_session.delivery()?;
        self.send_bytes(data).await?;
        let packet = self.receive(timeout).await?;
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
        self.write_session.require_link_reset();
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
