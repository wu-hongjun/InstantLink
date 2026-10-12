//! Independent no-film checks of explicit download-only pacing comparisons.
#[allow(dead_code)]
#[path = "../examples/download_only_benchmark.rs"]
mod probe;

use std::num::NonZeroUsize;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use image::codecs::jpeg::JpegEncoder;
use image::{ExtendedColorType, Rgb, RgbImage};
use instantlink_core::commands::{
    Command, OP_DATA, OP_DOWNLOAD_CANCEL, OP_DOWNLOAD_END, OP_DOWNLOAD_START, OP_PRINT_IMAGE,
};
use instantlink_core::protocol::{self, Packet};
use instantlink_core::{PrinterError, PrinterModel, Result};
use probe::ProbeCommands;
use tokio::time::Instant;

struct Event {
    packet: Packet,
    sent: bool,
    at: Instant,
}
struct Probe {
    events: Mutex<Vec<Event>>,
    legacy_index: Option<u32>,
    failure: Option<u16>,
}
impl Probe {
    fn new() -> Self {
        Self {
            events: Mutex::new(vec![]),
            legacy_index: None,
            failure: None,
        }
    }
}

#[async_trait]
impl ProbeCommands for Probe {
    fn payload_ceiling(&self) -> NonZeroUsize {
        NonZeroUsize::new(236).unwrap()
    }
    async fn command(&self, command: Command, payload: NonZeroUsize) -> Result<Packet> {
        assert!(payload.get() <= 236);
        assert!(matches!(
            command,
            Command::DownloadStart { .. }
                | Command::Data { .. }
                | Command::DownloadEnd
                | Command::DownloadCancel
        ));
        let packet = protocol::parse_packet(&command.encode()?).unwrap();
        assert_ne!(packet.opcode, OP_PRINT_IMAGE);
        self.events.lock().unwrap().push(Event {
            packet: packet.clone(),
            sent: true,
            at: Instant::now(),
        });
        if self.failure == Some(packet.opcode) {
            return Err(PrinterError::Ble("injected download-only error".into()));
        }
        let mut response = Packet {
            opcode: packet.opcode,
            payload: vec![0],
        };
        if let Command::Data { index, .. } = command
            && self.legacy_index != Some(index)
        {
            response.payload.extend_from_slice(&index.to_be_bytes());
        }
        tokio::time::sleep(Duration::from_millis(7)).await;
        self.events.lock().unwrap().push(Event {
            packet: response.clone(),
            sent: false,
            at: Instant::now(),
        });
        Ok(response)
    }
}

fn jpeg(model: PrinterModel) -> Vec<u8> {
    let spec = model.spec();
    let image = RgbImage::from_fn(spec.width, spec.height, |x, y| {
        if x < spec.width / 3 && y < spec.height / 3 {
            Rgb([230, 70, 40])
        } else {
            Rgb([50, 120, 220])
        }
    });
    let mut bytes = vec![];
    JpegEncoder::new_with_quality(&mut bytes, 80)
        .encode(
            image.as_raw(),
            spec.width,
            spec.height,
            ExtendedColorType::Rgb8,
        )
        .unwrap();
    assert!(bytes.len() <= spec.max_image_size);
    bytes
}

#[tokio::test(start_paused = true)]
async fn explicit_delay_only_changes_intermediate_pacing_and_preserves_final_model_settle() {
    for &model in PrinterModel::all() {
        let jpeg = jpeg(model);
        let mut original_commands = None;
        for delay in [0, 25, 50, 100, 150] {
            let transport = Probe::new();
            let start = Instant::now();
            let report = probe::download_round_with_delay(
                &transport,
                &jpeg,
                model,
                model.spec().flip_vertical,
                NonZeroUsize::new(236).unwrap(),
                delay,
            )
            .await
            .unwrap();
            let effective_delay = if model == PrinterModel::Square {
                delay
            } else {
                delay.max(model.spec().packet_delay_ms)
            };
            assert!(!report.legacy_ack_seen);
            assert_eq!(report.chunk_delay_ms, delay);
            assert_eq!(report.final_settle_ms, model.spec().packet_delay_ms);
            assert_eq!(
                report.pacing_ms,
                (report.chunks as u64 - 1) * effective_delay + model.spec().packet_delay_ms
            );
            assert_eq!(
                start.elapsed(),
                Duration::from_millis(report.pacing_ms + (report.chunks as u64 + 3) * 7)
            );
            let events = transport.events.lock().unwrap();
            let sent: Vec<_> = events
                .iter()
                .filter(|event| event.sent && event.packet.opcode == OP_DATA)
                .collect();
            let acked: Vec<_> = events
                .iter()
                .filter(|event| !event.sent && event.packet.opcode == OP_DATA)
                .collect();
            for (index, ack) in acked.iter().enumerate() {
                if index + 1 < sent.len() {
                    assert_eq!(
                        sent[index + 1].at - ack.at,
                        Duration::from_millis(effective_delay)
                    );
                }
            }
            let end = events
                .iter()
                .find(|event| event.sent && event.packet.opcode == OP_DOWNLOAD_END)
                .unwrap();
            assert_eq!(
                end.at - acked.last().unwrap().at,
                Duration::from_millis(model.spec().packet_delay_ms)
            );
            let transferred: Vec<_> = sent
                .iter()
                .flat_map(|event| event.packet.payload[4..].iter().copied())
                .collect();
            assert_eq!(&transferred[..jpeg.len()], jpeg);
            assert!(transferred[jpeg.len()..].iter().all(|byte| *byte == 0));
            let commands: Vec<_> = events
                .iter()
                .filter(|event| event.sent)
                .map(|event| event.packet.clone())
                .collect();
            assert_eq!(commands.first().unwrap().opcode, OP_DOWNLOAD_START);
            assert_eq!(commands.last().unwrap().opcode, OP_DOWNLOAD_CANCEL);
            if let Some(original) = &original_commands {
                assert_eq!(&commands, original);
            } else {
                original_commands = Some(commands);
            }
        }
    }
}

#[tokio::test(start_paused = true)]
async fn one_legacy_ack_latches_baseline_pacing_even_after_indexed_acks_resume() {
    let model = PrinterModel::Square;
    let mut transport = Probe::new();
    transport.legacy_index = Some(1);
    let report = probe::download_round_with_delay(
        &transport,
        &jpeg(model),
        model,
        false,
        NonZeroUsize::new(236).unwrap(),
        0,
    )
    .await
    .unwrap();
    assert!(report.chunks > 3);
    assert!(report.legacy_ack_seen);
    assert_eq!(
        report.pacing_ms,
        (report.chunks as u64 - 1) * model.spec().packet_delay_ms
    );
    let events = transport.events.lock().unwrap();
    let sent: Vec<_> = events
        .iter()
        .filter(|event| event.sent && event.packet.opcode == OP_DATA)
        .collect();
    let acked: Vec<_> = events
        .iter()
        .filter(|event| !event.sent && event.packet.opcode == OP_DATA)
        .collect();
    assert_eq!(sent[1].at - acked[0].at, Duration::ZERO);
    for index in 1..sent.len() - 1 {
        assert_eq!(
            sent[index + 1].at - acked[index].at,
            Duration::from_millis(model.spec().packet_delay_ms)
        );
    }
}

#[tokio::test]
async fn invalid_explicit_delay_or_prepared_jpeg_reject_before_any_download() {
    let valid = jpeg(PrinterModel::Square);
    for delay in [151, u64::MAX] {
        let transport = Probe::new();
        assert!(
            probe::download_round_with_delay(
                &transport,
                &valid,
                PrinterModel::Square,
                false,
                NonZeroUsize::new(236).unwrap(),
                delay
            )
            .await
            .is_err()
        );
        assert!(transport.events.lock().unwrap().is_empty());
    }
    for (bytes, model, flip) in [
        (vec![], PrinterModel::Square, false),
        (jpeg(PrinterModel::Mini), PrinterModel::Square, false),
        (valid, PrinterModel::Square, true),
    ] {
        let transport = Probe::new();
        assert!(
            probe::download_round_with_delay(
                &transport,
                &bytes,
                model,
                flip,
                NonZeroUsize::new(236).unwrap(),
                0
            )
            .await
            .is_err()
        );
        assert!(transport.events.lock().unwrap().is_empty());
    }
}

#[tokio::test(start_paused = true)]
async fn zero_delay_failure_never_replays_or_executes_uncertain_download() {
    for failing_opcode in [
        OP_DOWNLOAD_START,
        OP_DATA,
        OP_DOWNLOAD_END,
        OP_DOWNLOAD_CANCEL,
    ] {
        let mut transport = Probe::new();
        transport.failure = Some(failing_opcode);
        assert!(
            probe::download_round_with_delay(
                &transport,
                &jpeg(PrinterModel::Square),
                PrinterModel::Square,
                false,
                NonZeroUsize::new(236).unwrap(),
                0
            )
            .await
            .is_err()
        );
        let events = transport.events.lock().unwrap();
        let sent: Vec<_> = events
            .iter()
            .filter(|event| event.sent)
            .map(|event| event.packet.opcode)
            .collect();
        assert_eq!(sent.last(), Some(&failing_opcode));
        assert_eq!(
            sent.iter()
                .filter(|opcode| **opcode == OP_DOWNLOAD_START)
                .count(),
            1
        );
        if failing_opcode == OP_DATA {
            assert_eq!(sent, [OP_DOWNLOAD_START, OP_DATA]);
        }
        assert!(!sent.contains(&OP_PRINT_IMAGE));
    }
}

#[tokio::test(start_paused = true)]
async fn cancelled_explicit_pacing_wait_does_not_resume_or_send_print_command() {
    let transport = Arc::new(Probe::new());
    let task_transport = Arc::clone(&transport);
    let task = tokio::spawn(async move {
        probe::download_round_with_delay(
            task_transport.as_ref(),
            &jpeg(PrinterModel::Square),
            PrinterModel::Square,
            false,
            NonZeroUsize::new(236).unwrap(),
            100,
        )
        .await
    });
    loop {
        if transport
            .events
            .lock()
            .unwrap()
            .iter()
            .any(|event| !event.sent && event.packet.opcode == OP_DATA)
        {
            break;
        }
        tokio::time::advance(Duration::from_millis(1)).await;
    }
    task.abort();
    assert!(task.await.err().unwrap().is_cancelled());
    tokio::time::advance(Duration::from_secs(2)).await;
    let events = transport.events.lock().unwrap();
    let sent: Vec<_> = events
        .iter()
        .filter(|event| event.sent)
        .map(|event| event.packet.opcode)
        .collect();
    assert_eq!(sent, [OP_DOWNLOAD_START, OP_DATA]);
}

#[test]
fn probe_option_parser_preserves_order_and_bounds_total_no_film_comparisons() {
    let default = probe::parse_probe_options(None, None, None).unwrap();
    assert_eq!(
        default
            .payloads
            .iter()
            .map(|size| size.get())
            .collect::<Vec<_>>(),
        [182, 244, 236]
    );
    assert_eq!(default.delays_ms, [None]);
    assert_eq!(default.rounds, 1);
    let ordered =
        probe::parse_probe_options(Some("236"), Some("2"), Some("150,100,50,25,0")).unwrap();
    assert_eq!(
        ordered.delays_ms,
        [Some(150), Some(100), Some(50), Some(25), Some(0)]
    );
    assert_eq!(ordered.rounds, 2);
    assert!(probe::parse_probe_options(Some("236"), Some("2"), Some("0,1,2,3,4,5,6,7")).is_ok());
    assert!(
        probe::parse_probe_options(Some("182,236"), Some("2"), Some("0,1,2,3,4,5,6,7")).is_err()
    );
    for payload in ["0", "19", "245", "-1", ""] {
        assert!(probe::parse_probe_options(Some(payload), None, None).is_err());
    }
    for delay in ["151", "-1", "18446744073709551616", ""] {
        assert!(probe::parse_probe_options(Some("236"), None, Some(delay)).is_err());
    }
    for rounds in ["0", "3", "-1", ""] {
        assert!(probe::parse_probe_options(None, Some(rounds), None).is_err());
    }
    assert!(probe::parse_probe_options(Some("236"), None, Some("0,1,2,3,4,5,6,7,8")).is_err());
    assert!(probe::parse_probe_options(Some("20,21,22,23,24,25,26,27,28"), None, None).is_err());
    assert!(probe::parse_probe_options(Some("status-only"), None, Some("0")).is_err());
    let status = probe::parse_probe_options(Some("status-only"), Some("2"), None).unwrap();
    assert!(status.payloads.is_empty());
}
