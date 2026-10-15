//! Independent safety checks for the real download-only benchmark flow.
#[allow(dead_code)]
#[path = "../examples/download_only_benchmark.rs"]
mod probe;

use std::num::NonZeroUsize;
use std::sync::Mutex;

use async_trait::async_trait;
use image::codecs::jpeg::JpegEncoder;
use image::{ExtendedColorType, Rgb, RgbImage};
use instantlink_core::commands::{
    Command, OP_DATA, OP_DOWNLOAD_CANCEL, OP_DOWNLOAD_END, OP_DOWNLOAD_START, OP_PRINT_IMAGE,
};
use instantlink_core::protocol::{self, Packet};
use instantlink_core::{PrinterError, PrinterModel, Result};
use probe::ProbeCommands;

struct MockProbe {
    ceiling: NonZeroUsize,
    commands: Mutex<Vec<(Vec<u8>, usize)>>,
    reject_opcode: Option<u16>,
    failure_opcode: Option<u16>,
    wrong_ack_opcode: Option<u16>,
}

impl MockProbe {
    fn new(ceiling: usize) -> Self {
        Self {
            ceiling: NonZeroUsize::new(ceiling).unwrap(),
            commands: Mutex::new(Vec::new()),
            reject_opcode: None,
            failure_opcode: None,
            wrong_ack_opcode: None,
        }
    }
    fn opcodes(&self) -> Vec<u16> {
        self.commands
            .lock()
            .unwrap()
            .iter()
            .map(|(bytes, _)| protocol::parse_packet(bytes).unwrap().opcode)
            .collect()
    }
}

#[async_trait]
impl ProbeCommands for MockProbe {
    fn payload_ceiling(&self) -> NonZeroUsize {
        self.ceiling
    }
    async fn command(&self, command: Command, payload: NonZeroUsize) -> Result<Packet> {
        let encoded = command.encode()?;
        let opcode = protocol::parse_packet(&encoded).unwrap().opcode;
        assert_ne!(
            opcode, OP_PRINT_IMAGE,
            "Benchmark must never execute a physical print"
        );
        assert!(matches!(
            command,
            Command::DownloadStart { .. }
                | Command::Data { .. }
                | Command::DownloadEnd
                | Command::DownloadCancel
        ));
        assert!(payload.get() <= self.ceiling.get());
        self.commands.lock().unwrap().push((encoded, payload.get()));
        if self.failure_opcode == Some(opcode) {
            return Err(PrinterError::Ble("injected diagnostic failure".into()));
        }
        Ok(Packet {
            opcode: if self.wrong_ack_opcode == Some(opcode) {
                OP_DATA
            } else {
                opcode
            },
            payload: vec![if self.reject_opcode == Some(opcode) {
                178
            } else {
                0
            }],
        })
    }
}

fn jpeg(model: PrinterModel) -> Vec<u8> {
    let spec = model.spec();
    let image = RgbImage::from_fn(spec.width, spec.height, |x, y| {
        if x < spec.width / 3 && y < spec.height / 3 {
            Rgb([210, 30, 80])
        } else {
            Rgb([50, 160, 230])
        }
    });
    let mut encoded = Vec::new();
    JpegEncoder::new_with_quality(&mut encoded, 80)
        .encode(
            image.as_raw(),
            spec.width,
            spec.height,
            ExtendedColorType::Rgb8,
        )
        .unwrap();
    encoded
}

#[tokio::test(start_paused = true)]
async fn complete_round_for_every_model_preserves_bytes_pacing_and_never_prints() {
    for &model in PrinterModel::all() {
        let jpeg = jpeg(model);
        let mut previous_packets = None;
        for payload in [182, 236, 244] {
            let mock = MockProbe::new(244);
            let start = tokio::time::Instant::now();
            let report = probe::download_round(
                &mock,
                &jpeg,
                model,
                model.spec().flip_vertical,
                NonZeroUsize::new(payload).unwrap(),
            )
            .await
            .unwrap();
            assert_eq!(report.jpeg_bytes, jpeg.len());
            assert_eq!(report.effective_payload, payload);
            assert_eq!(
                report.pacing_ms,
                model.spec().packet_delay_ms * report.chunks as u64
            );
            assert_eq!(start.elapsed().as_millis() as u64, report.pacing_ms);
            let commands = mock.commands.lock().unwrap();
            let packets: Vec<_> = commands
                .iter()
                .map(|(bytes, _)| protocol::parse_packet(bytes).unwrap())
                .collect();
            assert_eq!(packets.first().unwrap().opcode, OP_DOWNLOAD_START);
            assert_eq!(
                &packets[packets.len() - 2..]
                    .iter()
                    .map(|packet| packet.opcode)
                    .collect::<Vec<_>>(),
                &[OP_DOWNLOAD_END, OP_DOWNLOAD_CANCEL]
            );
            assert_eq!(
                packets
                    .iter()
                    .filter(|packet| packet.opcode == OP_DOWNLOAD_START)
                    .count(),
                1
            );
            assert_eq!(
                packets
                    .iter()
                    .filter(|packet| packet.opcode == OP_DOWNLOAD_CANCEL)
                    .count(),
                1
            );
            let transferred: Vec<_> = packets
                .iter()
                .filter(|packet| packet.opcode == OP_DATA)
                .flat_map(|packet| packet.payload[4..].iter().copied())
                .collect();
            assert_eq!(&transferred[..jpeg.len()], jpeg);
            assert!(transferred[jpeg.len()..].iter().all(|byte| *byte == 0));
            assert_eq!(
                report.data_gatt_writes,
                commands
                    .iter()
                    .filter(|(bytes, _)| protocol::parse_packet(bytes).unwrap().opcode == OP_DATA)
                    .map(|(bytes, limit)| bytes.len().div_ceil(*limit))
                    .sum::<usize>()
            );
            let encoded: Vec<_> = commands.iter().map(|(bytes, _)| bytes.clone()).collect();
            if let Some(previous) = &previous_packets {
                assert_eq!(&encoded, previous);
            } else {
                previous_packets = Some(encoded);
            }
        }
    }
}

#[tokio::test(start_paused = true)]
async fn cap_is_bounded_by_current_connection_and_does_not_mutate_transport_ceiling() {
    let jpeg = jpeg(PrinterModel::Square);
    for ceiling in [20, 182, 244] {
        let mock = MockProbe::new(ceiling);
        for requested in [20, 182, 244, usize::MAX] {
            let report = probe::download_round(
                &mock,
                &jpeg,
                PrinterModel::Square,
                false,
                NonZeroUsize::new(requested).unwrap(),
            )
            .await
            .unwrap();
            assert_eq!(report.effective_payload, requested.min(ceiling));
            assert_eq!(mock.payload_ceiling().get(), ceiling);
        }
    }
}

#[tokio::test]
async fn invalid_jpeg_wrong_dimensions_or_flip_reject_before_any_download() {
    for (jpeg, model, flip) in [
        (vec![], PrinterModel::Square, false),
        (vec![0xff, 0xd8, 0xff, 0xd9], PrinterModel::Square, false),
        (jpeg(PrinterModel::Mini), PrinterModel::Square, false),
        (
            jpeg(PrinterModel::MiniLink3),
            PrinterModel::MiniLink3,
            false,
        ),
        (jpeg(PrinterModel::Square), PrinterModel::Square, true),
    ] {
        let mock = MockProbe::new(244);
        assert!(
            probe::download_round(&mock, &jpeg, model, flip, NonZeroUsize::new(244).unwrap())
                .await
                .is_err()
        );
        assert!(mock.opcodes().is_empty());
    }
}

#[tokio::test(start_paused = true)]
async fn each_rejected_ack_or_transport_error_stops_without_replay_or_print() {
    let jpeg = jpeg(PrinterModel::Square);
    for target in [
        OP_DOWNLOAD_START,
        OP_DATA,
        OP_DOWNLOAD_END,
        OP_DOWNLOAD_CANCEL,
    ] {
        for transport_error in [false, true] {
            let mut mock = MockProbe::new(244);
            if transport_error {
                mock.failure_opcode = Some(target);
            } else {
                mock.reject_opcode = Some(target);
            }
            assert!(
                probe::download_round(
                    &mock,
                    &jpeg,
                    PrinterModel::Square,
                    false,
                    NonZeroUsize::new(244).unwrap()
                )
                .await
                .is_err()
            );
            let opcodes = mock.opcodes();
            assert_eq!(opcodes.last(), Some(&target));
            assert_eq!(
                opcodes
                    .iter()
                    .filter(|opcode| **opcode == OP_DOWNLOAD_START)
                    .count(),
                1
            );
            assert!(!opcodes.contains(&OP_PRINT_IMAGE));
            if target == OP_DATA {
                assert_eq!(
                    opcodes.iter().filter(|opcode| **opcode == OP_DATA).count(),
                    1
                );
            }
        }
    }
}

#[tokio::test(start_paused = true)]
async fn cancellation_ack_cannot_be_substituted_by_a_stale_data_ack() {
    let mut mock = MockProbe::new(244);
    mock.wrong_ack_opcode = Some(OP_DOWNLOAD_CANCEL);
    assert!(
        probe::download_round(
            &mock,
            &jpeg(PrinterModel::Square),
            PrinterModel::Square,
            false,
            NonZeroUsize::new(244).unwrap()
        )
        .await
        .is_err()
    );
    assert_eq!(mock.opcodes().last(), Some(&OP_DOWNLOAD_CANCEL));
}

#[tokio::test(start_paused = true)]
async fn cancelled_round_never_continues_to_end_or_print_and_does_not_replay() {
    let mock = std::sync::Arc::new(MockProbe::new(244));
    let task_mock = std::sync::Arc::clone(&mock);
    let task = tokio::spawn(async move {
        probe::download_round(
            task_mock.as_ref(),
            &jpeg(PrinterModel::Square),
            PrinterModel::Square,
            false,
            NonZeroUsize::new(244).unwrap(),
        )
        .await
    });
    while !mock.opcodes().contains(&OP_DATA) {
        tokio::task::yield_now().await;
    }
    task.abort();
    assert!(task.await.err().unwrap().is_cancelled());
    tokio::task::yield_now().await;
    assert_eq!(mock.opcodes(), [OP_DOWNLOAD_START, OP_DATA]);
}

#[tokio::test(start_paused = true)]
async fn completed_measurements_and_film_counters_survive_cleanup_failure() {
    let mock = MockProbe::new(244);
    let jpeg = jpeg(PrinterModel::Square);
    let completed = probe::download_round(
        &mock,
        &jpeg,
        PrinterModel::Square,
        false,
        NonZeroUsize::new(236).unwrap(),
    )
    .await
    .unwrap();
    let report = probe::ProbeReport {
        model: Some(PrinterModel::Square),
        before: Some((1, 123)),
        after: Some((1, 123)),
        available_payload: 244,
        rounds: vec![completed],
    };
    let json = report.to_json(&Ok(()), &Err(PrinterError::Timeout));
    assert_eq!(
        json["rounds"],
        serde_json::to_value(&report.rounds).unwrap()
    );
    assert_eq!(json["rounds"].as_array().unwrap().len(), 1);
    assert_eq!(json["rounds"][0]["jpeg_bytes"], jpeg.len());
    assert_eq!(json["rounds"][0]["effective_payload"], 236);
    assert_eq!(json["film_before"], 1);
    assert_eq!(json["film_after"], 1);
    assert_eq!(json["history_before"], 123);
    assert_eq!(json["history_after"], 123);
    assert_eq!(json["benchmark_complete"], true);
    assert!(json["benchmark_error"].is_null());
    assert_eq!(json["disconnected"], false);
    assert!(
        json["cleanup_error"]
            .as_str()
            .is_some_and(|error| !error.is_empty())
    );
}

#[tokio::test(start_paused = true)]
async fn partial_benchmark_failure_and_cleanup_failure_remain_separate_with_completed_rows() {
    let mock = MockProbe::new(244);
    let completed = probe::download_round(
        &mock,
        &jpeg(PrinterModel::Square),
        PrinterModel::Square,
        false,
        NonZeroUsize::new(182).unwrap(),
    )
    .await
    .unwrap();
    let report = probe::ProbeReport {
        model: Some(PrinterModel::Square),
        before: Some((1, 123)),
        after: None,
        available_payload: 244,
        rounds: vec![completed],
    };
    let json = report.to_json(
        &Err(PrinterError::Ble("later round failed".into())),
        &Err(PrinterError::Ble("disconnect verification failed".into())),
    );
    assert_eq!(
        json["rounds"],
        serde_json::to_value(&report.rounds).unwrap()
    );
    assert_eq!(json["film_before"], 1);
    assert_eq!(json["history_before"], 123);
    assert!(json["film_after"].is_null());
    assert!(json["history_after"].is_null());
    assert_eq!(json["benchmark_complete"], false);
    assert!(
        json["benchmark_error"]
            .as_str()
            .unwrap()
            .contains("later round failed")
    );
    assert_eq!(json["disconnected"], false);
    assert!(
        json["cleanup_error"]
            .as_str()
            .unwrap()
            .contains("disconnect verification failed")
    );
}

#[test]
fn status_only_or_failure_before_first_round_reports_no_download_rows_or_false_counters() {
    let report = probe::ProbeReport {
        model: None,
        before: None,
        after: None,
        available_payload: 182,
        rounds: vec![],
    };
    let json = report.to_json(&Err(PrinterError::PrinterNotFound), &Ok(()));
    assert_eq!(json["rounds"], serde_json::json!([]));
    assert!(json["model"].is_null());
    assert!(json["film_before"].is_null());
    assert!(json["film_after"].is_null());
    assert!(json["history_before"].is_null());
    assert!(json["history_after"].is_null());
    assert_eq!(json["benchmark_complete"], false);
    assert_eq!(json["disconnected"], true);
    assert!(json["cleanup_error"].is_null());
}
