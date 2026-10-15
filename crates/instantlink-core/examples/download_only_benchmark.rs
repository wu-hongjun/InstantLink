//! Same-connection fragment/pacing comparison. Downloads and cancels; never executes a print.
//! Usage: <exact Printer name or BLE address> <prepared.jpg> [182,244,236|status-only|production] [rounds] [intermediate-delay-ms-list]
use async_trait::async_trait;
use btleplug::api::Peripheral as _;
use instantlink_core::commands::{Command, Response, ResponseExpectation};
use instantlink_core::commands::{
    OP_DATA, OP_DOWNLOAD_CANCEL, OP_DOWNLOAD_END, OP_DOWNLOAD_START, OP_SUPPORT_FUNCTION_INFO,
};
use instantlink_core::device::BlePrinterDevice;
use instantlink_core::protocol::{self, Packet};
use instantlink_core::transport::{self, BleTransport, Transport};
use instantlink_core::{PrinterDevice, PrinterError, PrinterModel, Result, image};
use serde::Serialize;
use std::error::Error;
use std::num::NonZeroUsize;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[async_trait]
pub trait ProbeCommands: Send + Sync {
    fn payload_ceiling(&self) -> NonZeroUsize;
    async fn command(&self, command: Command, payload: NonZeroUsize) -> Result<Packet>;
    async fn command_for_model(
        &self,
        command: Command,
        payload: NonZeroUsize,
        _model: PrinterModel,
    ) -> Result<Packet> {
        self.command(command, payload).await
    }
}

#[async_trait]
impl ProbeCommands for BleTransport {
    fn payload_ceiling(&self) -> NonZeroUsize {
        self.diagnostic_payload_limit()
    }
    async fn command(&self, command: Command, payload: NonZeroUsize) -> Result<Packet> {
        self.diagnostic_command_with_payload_limit(&command, payload)
            .await
    }
    async fn command_for_model(
        &self,
        command: Command,
        payload: NonZeroUsize,
        model: PrinterModel,
    ) -> Result<Packet> {
        self.diagnostic_command_for_model_with_payload_limit(&command, payload, model)
            .await
    }
}

#[derive(Serialize)]
pub struct RoundReport {
    pub requested_payload: usize,
    pub effective_payload: usize,
    pub jpeg_bytes: usize,
    pub chunks: usize,
    pub data_gatt_writes: usize,
    pub start_ms: f64,
    pub chunk_command_ms: Vec<f64>,
    pub pacing_ms: u64,
    pub chunk_delay_ms: u64,
    pub final_settle_ms: u64,
    pub legacy_ack_seen: bool,
    pub benchmark_round: Option<usize>,
    pub position_in_round: Option<usize>,
    pub end_ms: f64,
    pub cancel_ms: f64,
    pub total_ms: f64,
}

pub struct ProbeReport {
    pub model: Option<PrinterModel>,
    pub before: Option<(u8, u16)>,
    pub after: Option<(u8, u16)>,
    pub available_payload: usize,
    pub rounds: Vec<RoundReport>,
}

impl ProbeReport {
    pub fn to_json(&self, benchmark: &Result<()>, cleanup: &Result<()>) -> serde_json::Value {
        serde_json::json!({
            "mode": "download-only; no print execution",
            "model": self.model.map(|model| format!("{model:?}")),
            "film_before": self.before.map(|(film, _)| film),
            "film_after": self.after.map(|(film, _)| film),
            "history_before": self.before.map(|(_, history)| history),
            "history_after": self.after.map(|(_, history)| history),
            "available_payload": self.available_payload,
            "rounds": self.rounds,
            "benchmark_complete": benchmark.is_ok(),
            "benchmark_error": benchmark.as_ref().err().map(ToString::to_string),
            "disconnected": cleanup.is_ok(),
            "cleanup_error": cleanup.as_ref().err().map(ToString::to_string),
        })
    }
}

pub struct ProbeOptions {
    pub payloads: Vec<NonZeroUsize>,
    pub delays_ms: Vec<Option<u64>>,
    pub rounds: usize,
    pub production: bool,
}

pub fn parse_probe_options(
    payloads: Option<&str>,
    rounds: Option<&str>,
    delays: Option<&str>,
) -> std::result::Result<ProbeOptions, &'static str> {
    let production = payloads == Some("production");
    let payloads = if payloads == Some("status-only") || production {
        if delays.is_some() {
            return Err("status-only does not accept a delay list");
        }
        Vec::new()
    } else {
        payloads
            .unwrap_or("182,244,236")
            .split(',')
            .map(|value| {
                value
                    .parse::<usize>()
                    .ok()
                    .and_then(NonZeroUsize::new)
                    .filter(|value| (20..=244).contains(&value.get()))
                    .ok_or("diagnostic payload must be 20..244")
            })
            .collect::<std::result::Result<Vec<_>, _>>()?
    };
    if payloads.len() > 8 {
        return Err("at most eight payload sizes are allowed");
    }
    let rounds = rounds
        .unwrap_or("1")
        .parse::<usize>()
        .map_err(|_| "rounds must be 1..2")?;
    if !(1..=2).contains(&rounds) {
        return Err("rounds must be 1..2");
    }
    let delays_ms = match delays {
        None => vec![None],
        Some(values) => values
            .split(',')
            .map(|value| {
                value
                    .parse::<u64>()
                    .ok()
                    .filter(|value| *value <= 150)
                    .map(Some)
                    .ok_or("diagnostic delay must be 0..150ms")
            })
            .collect::<std::result::Result<Vec<_>, _>>()?,
    };
    if delays_ms.len() > 8 {
        return Err("at most eight delays are allowed");
    }
    if payloads.len() * delays_ms.len() * rounds > 16 {
        return Err("at most sixteen total download comparisons are allowed");
    }
    Ok(ProbeOptions {
        payloads,
        delays_ms,
        rounds,
        production,
    })
}

struct CheckedDownload {
    elapsed_ms: f64,
    indexed_data_ack: bool,
}

async fn checked_download_command(
    transport: &impl ProbeCommands,
    command: Command,
    payload: NonZeroUsize,
    model: PrinterModel,
) -> Result<CheckedDownload> {
    let start = Instant::now();
    let expectation = command
        .response_expectation_for_model(model)
        .ok_or_else(|| {
            PrinterError::UnexpectedResponse("download diagnostic has no ACK identity".into())
        })?;
    let is_data = matches!(&command, Command::Data { .. });
    let packet = transport.command_for_model(command, payload, model).await?;
    if !expectation.matches(&packet) {
        return Err(PrinterError::UnexpectedResponse(
            "download-only ACK identity mismatch".into(),
        ));
    }
    match Response::decode(&packet) {
        Response::DownloadAck { status } if status == 0 || status == model.spec().success_code => {
            Ok(CheckedDownload {
                elapsed_ms: start.elapsed().as_secs_f64() * 1000.0,
                indexed_data_ack: is_data && packet.payload.len() == 5,
            })
        }
        response => Err(PrinterError::UnexpectedResponse(format!(
            "download-only ACK rejected: {response:?}"
        ))),
    }
}

pub async fn download_round(
    transport: &impl ProbeCommands,
    jpeg: &[u8],
    model: PrinterModel,
    flip: bool,
    requested: NonZeroUsize,
) -> Result<RoundReport> {
    download_round_with_delay(
        transport,
        jpeg,
        model,
        flip,
        requested,
        model.spec().packet_delay_ms,
    )
    .await
}

pub async fn download_round_with_delay(
    transport: &impl ProbeCommands,
    jpeg: &[u8],
    model: PrinterModel,
    flip: bool,
    requested: NonZeroUsize,
    delay_ms: u64,
) -> Result<RoundReport> {
    if delay_ms > 150 {
        return Err(PrinterError::Ble(
            "diagnostic delay must be 0..150ms".into(),
        ));
    }
    // Validate before DownloadStart. Bytes are already prepared for the detected model.
    image::validate_prepared_jpeg(jpeg, model, model, flip)?;
    let payload = requested.min(transport.payload_ceiling());
    let chunks = image::chunk_image_data(jpeg, model);
    let total = Instant::now();
    let start_ms = checked_download_command(
        transport,
        Command::DownloadStart {
            image_size: jpeg.len() as u32,
            print_option: 0,
        },
        payload,
        model,
    )
    .await?
    .elapsed_ms;
    let mut chunk_command_ms = Vec::new();
    let mut data_gatt_writes = 0;
    let mut pacing_ms = 0;
    let mut legacy_ack_seen = false;
    let baseline_delay = model.spec().packet_delay_ms;
    for (index, chunk) in chunks.iter().enumerate() {
        let command = Command::Data {
            index: index as u32,
            data: chunk.clone(),
        };
        data_gatt_writes += command.encode()?.len().div_ceil(payload.get());
        let ack = checked_download_command(transport, command, payload, model).await?;
        chunk_command_ms.push(ack.elapsed_ms);
        legacy_ack_seen |= !ack.indexed_data_ack;
        // Protect the final DownloadEnd transition with the model baseline.
        // A status-only ACK cannot authorize faster intermediate pacing.
        let wait_ms = if index + 1 == chunks.len() {
            baseline_delay
        } else if legacy_ack_seen || model != PrinterModel::Square {
            delay_ms.max(baseline_delay)
        } else {
            delay_ms
        };
        pacing_ms += wait_ms;
        if wait_ms > 0 {
            tokio::time::sleep(Duration::from_millis(wait_ms)).await;
        }
    }
    let end_ms = checked_download_command(transport, Command::DownloadEnd, payload, model)
        .await?
        .elapsed_ms;
    let cancel_ms = checked_download_command(transport, Command::DownloadCancel, payload, model)
        .await?
        .elapsed_ms;
    Ok(RoundReport {
        requested_payload: requested.get(),
        effective_payload: payload.get(),
        jpeg_bytes: jpeg.len(),
        chunks: chunks.len(),
        data_gatt_writes,
        start_ms,
        chunk_command_ms,
        pacing_ms,
        chunk_delay_ms: delay_ms,
        final_settle_ms: baseline_delay,
        legacy_ack_seen,
        benchmark_round: None,
        position_in_round: None,
        end_ms,
        cancel_ms,
        total_ms: total.elapsed().as_secs_f64() * 1000.0,
    })
}

pub fn validate_download_only_packet(data: &[u8]) -> Result<()> {
    let packet = protocol::parse_packet(data)
        .ok_or_else(|| PrinterError::Protocol("invalid download-only command packet".into()))?;
    if matches!(
        packet.opcode,
        OP_SUPPORT_FUNCTION_INFO
            | OP_DOWNLOAD_START
            | OP_DATA
            | OP_DOWNLOAD_END
            | OP_DOWNLOAD_CANCEL
    ) {
        Ok(())
    } else {
        Err(PrinterError::Ble(
            "actuator command is forbidden in download-only probe".into(),
        ))
    }
}

// A shared transport lets the authoritative device detect the model and query
// before/after counters without opening another BLE connection.
struct SharedTransport(Arc<BleTransport>);
#[async_trait]
impl Transport for SharedTransport {
    async fn send(&self, data: &[u8]) -> Result<()> {
        validate_download_only_packet(data)?;
        self.0.send(data).await
    }
    async fn receive(&self, timeout: Duration) -> Result<Packet> {
        self.0.receive(timeout).await
    }
    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<Packet> {
        validate_download_only_packet(data)?;
        self.0.send_and_receive(data, timeout).await
    }
    async fn send_and_receive_expected(
        &self,
        data: &[u8],
        timeout: Duration,
        expectation: ResponseExpectation,
    ) -> Result<Packet> {
        validate_download_only_packet(data)?;
        self.0
            .send_and_receive_expected(data, timeout, expectation)
            .await
    }
    async fn disconnect(&self) -> Result<()> {
        self.0.disconnect().await
    }
    fn data_packet_delay_ms(&self, model: PrinterModel) -> u64 {
        self.0.data_packet_delay_ms(model)
    }
    fn image_transfer_started(&self) {
        self.0.image_transfer_started();
    }
    fn image_transfer_completed(&self) {
        self.0.image_transfer_completed();
    }
    fn image_transfer_failed(&self) {
        self.0.image_transfer_failed();
    }
    fn image_transfer_rejected(&self) {
        self.0.image_transfer_rejected();
    }
    fn fast_chunk_gap_used(&self) {
        self.0.fast_chunk_gap_used();
    }
    fn model_number_hint(&self) -> Option<&str> {
        self.0.model_number_hint()
    }
}

#[tokio::main]
async fn main() -> std::result::Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if !(2..=5).contains(&args.len()) {
        return Err("expected Printer prepared.jpg [182,244,236|status-only|production] [rounds] [intermediate-delay-ms-list]".into());
    }
    let jpeg = std::fs::read(&args[1])?;
    let options = parse_probe_options(
        args.get(2).map(String::as_str),
        args.get(3).map(String::as_str),
        args.get(4).map(String::as_str),
    )?;
    let adapter = transport::get_adapter().await?;
    let candidates = transport::scan(&adapter, Duration::from_secs(3)).await?;
    let mut matches = candidates.into_iter().filter(|(p, name)| {
        name == &args[0] || p.address().to_string().eq_ignore_ascii_case(&args[0])
    });
    let (peripheral, name) = matches.next().ok_or(PrinterError::PrinterNotFound)?;
    if matches.next().is_some() {
        return Err("Printer identity is ambiguous".into());
    }
    let transport = Arc::new(BleTransport::connect(peripheral).await?);
    let mut report = ProbeReport {
        model: None,
        before: None,
        after: None,
        available_payload: transport.diagnostic_payload_limit().get(),
        rounds: Vec::new(),
    };
    let mut production_rows = Vec::new();
    let result: Result<()> = async {
        let device =
            BlePrinterDevice::new(Box::new(SharedTransport(Arc::clone(&transport))), name).await?;
        let model = device.model();
        report.model = Some(model);
        let before = device.status().await?;
        report.before = Some((before.film_remaining, before.print_count));
        image::validate_prepared_jpeg(&jpeg, model, model, model.spec().flip_vertical)?;
        if options.production {
            for round in 0..options.rounds {
                let chunks = image::chunk_image_data(&jpeg, model).len();
                let delays = std::sync::Mutex::new(Vec::new());
                let progress = |completed: usize, total: usize| {
                    let delay = if completed == total { model.spec().packet_delay_ms }
                        else { transport.data_packet_delay_ms(model) };
                    delays.lock().unwrap().push(delay);
                };
                let started = Instant::now();
                device.download_prepared_jpeg_and_cancel(&jpeg, model, model.spec().flip_vertical, Some(&progress)).await?;
                let elapsed_ms = started.elapsed().as_secs_f64() * 1000.0;
                let delays = delays.into_inner().unwrap();
                eprintln!("production round={} total_ms={:.3}", round + 1, elapsed_ms);
                production_rows.push(serde_json::json!({ "round": round + 1,
                    "path": "production send_image_data + checked DownloadCancel; no PrintImage",
                    "jpeg_bytes": jpeg.len(), "chunks": chunks,
                    "payload": transport.production_payload_limit().get(),
                    "chunk_delays_ms": delays, "total_ms": elapsed_ms }));
            }
        }
        for round in 0..options.rounds {
            let mut delays = options.delays_ms.clone();
            // Reverse only explicit pacing sweeps; existing fragment comparisons
            // keep their original order.
            if args.get(4).is_some() && round % 2 == 1 { delays.reverse(); }
            let mut position = 0;
            for size in &options.payloads {
                for delay in &delays {
                    position += 1;
                    let mut completed = download_round_with_delay(
                        transport.as_ref(), &jpeg, model, model.spec().flip_vertical,
                        *size, delay.unwrap_or(model.spec().packet_delay_ms),
                    ).await?;
                    completed.benchmark_round = Some(round + 1);
                    completed.position_in_round = Some(position);
                    eprintln!(
                        "round={} position={} requested={} effective={} delay_ms={} final_ms={} legacy_ack={} total_ms={:.3}",
                        round + 1, position, size, completed.effective_payload,
                        completed.chunk_delay_ms, completed.final_settle_ms,
                        completed.legacy_ack_seen, completed.total_ms
                    );
                    report.rounds.push(completed);
                }
            }
        }
        let after = device.status().await?;
        report.after = Some((after.film_remaining, after.print_count));
        if before.film_remaining != after.film_remaining || before.print_count != after.print_count
        {
            return Err(PrinterError::UnexpectedResponse(
                "download-only probe changed film/history counters".into(),
            ));
        }
        Ok(())
    }
    .await;
    // Keep completed measurements and counters even when teardown fails. Both
    // errors remain explicit in JSON, and either failure produces a nonzero exit.
    let disconnected = transport.disconnect().await;
    let mut output = report.to_json(&result, &disconnected);
    output["production_rounds"] = serde_json::Value::Array(production_rows);
    println!("{}", serde_json::to_string_pretty(&output)?);
    result?;
    disconnected?;
    Ok(())
}
