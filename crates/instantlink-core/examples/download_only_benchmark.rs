//! Same-connection fragment comparison. Downloads and cancels; never executes a print.
//! Usage: <exact Printer name or BLE address> <prepared.jpg> [182,244,236|status-only] [rounds]
use async_trait::async_trait;
use btleplug::api::Peripheral as _;
use instantlink_core::commands::{Command, Response, ResponseExpectation};
use instantlink_core::device::BlePrinterDevice;
use instantlink_core::protocol::Packet;
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

async fn checked_download_command(
    transport: &impl ProbeCommands,
    command: Command,
    payload: NonZeroUsize,
    model: PrinterModel,
) -> Result<f64> {
    let start = Instant::now();
    let expectation = command.response_expectation().ok_or_else(|| {
        PrinterError::UnexpectedResponse("download diagnostic has no ACK identity".into())
    })?;
    let packet = transport.command(command, payload).await?;
    if !expectation.matches(&packet) {
        return Err(PrinterError::UnexpectedResponse(
            "download-only ACK identity mismatch".into(),
        ));
    }
    match Response::decode(&packet) {
        Response::DownloadAck { status } if status == 0 || status == model.spec().success_code => {
            Ok(start.elapsed().as_secs_f64() * 1000.0)
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
    .await?;
    let mut chunk_command_ms = Vec::new();
    let mut data_gatt_writes = 0;
    for (index, chunk) in chunks.iter().enumerate() {
        let command = Command::Data {
            index: index as u32,
            data: chunk.clone(),
        };
        data_gatt_writes += command.encode()?.len().div_ceil(payload.get());
        chunk_command_ms.push(checked_download_command(transport, command, payload, model).await?);
        if model.spec().packet_delay_ms > 0 {
            tokio::time::sleep(Duration::from_millis(model.spec().packet_delay_ms)).await;
        }
    }
    let end_ms = checked_download_command(transport, Command::DownloadEnd, payload, model).await?;
    let cancel_ms =
        checked_download_command(transport, Command::DownloadCancel, payload, model).await?;
    Ok(RoundReport {
        requested_payload: requested.get(),
        effective_payload: payload.get(),
        jpeg_bytes: jpeg.len(),
        chunks: chunks.len(),
        data_gatt_writes,
        start_ms,
        chunk_command_ms,
        pacing_ms: model.spec().packet_delay_ms * chunks.len() as u64,
        end_ms,
        cancel_ms,
        total_ms: total.elapsed().as_secs_f64() * 1000.0,
    })
}

// A shared transport lets the authoritative device detect the model and query
// before/after counters without opening another BLE connection.
struct SharedTransport(Arc<BleTransport>);
#[async_trait]
impl Transport for SharedTransport {
    async fn send(&self, data: &[u8]) -> Result<()> {
        self.0.send(data).await
    }
    async fn receive(&self, timeout: Duration) -> Result<Packet> {
        self.0.receive(timeout).await
    }
    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<Packet> {
        self.0.send_and_receive(data, timeout).await
    }
    async fn send_and_receive_expected(
        &self,
        data: &[u8],
        timeout: Duration,
        expectation: ResponseExpectation,
    ) -> Result<Packet> {
        self.0
            .send_and_receive_expected(data, timeout, expectation)
            .await
    }
    async fn disconnect(&self) -> Result<()> {
        self.0.disconnect().await
    }
    fn model_number_hint(&self) -> Option<&str> {
        self.0.model_number_hint()
    }
}

#[tokio::main]
async fn main() -> std::result::Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if !(2..=4).contains(&args.len()) {
        return Err("expected Printer prepared.jpg [182,244,236|status-only] [rounds]".into());
    }
    let jpeg = std::fs::read(&args[1])?;
    let sizes: Vec<NonZeroUsize> = if args.get(2).is_some_and(|s| s == "status-only") {
        Vec::new()
    } else {
        args.get(2)
            .map_or("182,244,236", String::as_str)
            .split(',')
            .map(|s| {
                s.parse::<usize>()
                    .ok()
                    .and_then(NonZeroUsize::new)
                    .filter(|n| (20..=244).contains(&n.get()))
                    .ok_or("diagnostic payload must be 20..244")
            })
            .collect::<std::result::Result<_, _>>()?
    };
    if sizes.len() > 8 {
        return Err("at most eight sizes are allowed".into());
    }
    let rounds: usize = args.get(3).map_or(Ok(1), |s| s.parse())?;
    if !(1..=2).contains(&rounds) {
        return Err("rounds must be 1..2".into());
    }
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
    let result: Result<()> = async {
        let device =
            BlePrinterDevice::new(Box::new(SharedTransport(Arc::clone(&transport))), name).await?;
        let model = device.model();
        report.model = Some(model);
        let before = device.status().await?;
        report.before = Some((before.film_remaining, before.print_count));
        image::validate_prepared_jpeg(&jpeg, model, model, model.spec().flip_vertical)?;
        for round in 0..rounds {
            for size in &sizes {
                let completed = download_round(
                    transport.as_ref(),
                    &jpeg,
                    model,
                    model.spec().flip_vertical,
                    *size,
                )
                .await?;
                eprintln!(
                    "round={} requested={} effective={} total_ms={:.3}",
                    round + 1,
                    size,
                    completed.effective_payload,
                    completed.total_ms
                );
                report.rounds.push(completed);
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
    println!(
        "{}",
        serde_json::to_string_pretty(&report.to_json(&result, &disconnected))?
    );
    result?;
    disconnected?;
    Ok(())
}
