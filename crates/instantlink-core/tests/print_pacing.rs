//! Independent tests of real device ACK pacing with a hardware-free transport.
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use image::codecs::jpeg::JpegEncoder;
use image::{ExtendedColorType, Rgb, RgbImage};
use instantlink_core::commands::{
    INFO_IMAGE_SUPPORT, OP_DATA, OP_DOWNLOAD_CANCEL, OP_DOWNLOAD_END, OP_DOWNLOAD_START,
    OP_LED_PATTERN_SETTINGS, OP_PRINT_IMAGE, OP_SUPPORT_FUNCTION_INFO,
};
use instantlink_core::device::BlePrinterDevice;
use instantlink_core::protocol::{self, Packet};
use instantlink_core::transport::{Transport, data_packet_delay_ms_for_context};
use instantlink_core::{PrinterDevice, PrinterError, PrinterModel, Result};
use tokio::sync::Notify;
use tokio::time::Instant;

#[derive(Clone)]
struct Event {
    packet: Packet,
    sent: bool,
    at: Instant,
}

#[derive(Clone, Copy)]
enum Fault {
    Reject,
    Timeout,
    Write,
}

struct State {
    pending: Option<Packet>,
    events: Vec<Event>,
    hooks: Vec<&'static str>,
}

#[derive(Default)]
struct Options {
    delay: Option<u64>,
    fault_index: u32,
    failure_opcode: Option<u16>,
    rejected_opcode: Option<u16>,
    rejection_status: Option<u8>,
}

struct TimedTransport {
    model: PrinterModel,
    state: Arc<Mutex<State>>,
    gate_data: AtomicBool,
    entered: Arc<Notify>,
    released: Arc<Notify>,
    fault: Option<Fault>,
    options: Options,
}

#[async_trait]
impl Transport for TimedTransport {
    async fn send(&self, bytes: &[u8]) -> Result<()> {
        let packet = protocol::parse_packet(bytes).unwrap();
        let is_data = packet.opcode == OP_DATA;
        let at_fault_index = is_data
            && u32::from_be_bytes(packet.payload[..4].try_into().unwrap())
                == self.options.fault_index;
        let failure_opcode = self.options.failure_opcode == Some(packet.opcode);
        {
            let mut state = self.state.lock().unwrap();
            state.events.push(Event {
                packet: packet.clone(),
                sent: true,
                at: Instant::now(),
            });
            state.pending = Some(packet);
        }
        if failure_opcode || (at_fault_index && matches!(self.fault, Some(Fault::Write))) {
            return Err(PrinterError::Ble("injected write failure".into()));
        }
        Ok(())
    }

    async fn receive(&self, _timeout: Duration) -> Result<Packet> {
        let request = self.state.lock().unwrap().pending.take().unwrap();
        if request.opcode == OP_DATA && self.gate_data.swap(false, Ordering::SeqCst) {
            self.entered.notify_one();
            self.released.notified().await;
        }
        let at_fault_index = request.opcode == OP_DATA
            && u32::from_be_bytes(request.payload[..4].try_into().unwrap())
                == self.options.fault_index;
        if at_fault_index && matches!(self.fault, Some(Fault::Timeout)) {
            return Err(PrinterError::Timeout);
        }
        let payload = match request.opcode {
            OP_SUPPORT_FUNCTION_INFO => {
                let spec = self.model.spec();
                let mut data = vec![0, INFO_IMAGE_SUPPORT];
                data.extend_from_slice(&(spec.width as u16).to_be_bytes());
                data.extend_from_slice(&(spec.height as u16).to_be_bytes());
                data
            }
            OP_DATA => {
                let mut data = vec![
                    if at_fault_index && matches!(self.fault, Some(Fault::Reject)) {
                        self.options.rejection_status.unwrap_or(178)
                    } else {
                        0
                    },
                ];
                data.extend_from_slice(&request.payload[..4]);
                data
            }
            _ => vec![if self.options.rejected_opcode == Some(request.opcode) {
                self.options.rejection_status.unwrap_or(178)
            } else {
                0
            }],
        };
        tokio::time::sleep(Duration::from_millis(if request.opcode == OP_DATA {
            17
        } else {
            3
        }))
        .await;
        let response = Packet {
            opcode: request.opcode,
            payload,
        };
        self.state.lock().unwrap().events.push(Event {
            packet: response.clone(),
            sent: false,
            at: Instant::now(),
        });
        Ok(response)
    }

    async fn send_and_receive(&self, bytes: &[u8], timeout: Duration) -> Result<Packet> {
        self.send(bytes).await?;
        self.receive(timeout).await
    }
    async fn disconnect(&self) -> Result<()> {
        Ok(())
    }
    fn data_packet_delay_ms(&self, model: PrinterModel) -> u64 {
        self.options.delay.unwrap_or(model.spec().packet_delay_ms)
    }
    fn image_transfer_started(&self) {
        self.state.lock().unwrap().hooks.push("started");
    }
    fn image_transfer_completed(&self) {
        self.state.lock().unwrap().hooks.push("completed");
    }
    fn image_transfer_failed(&self) {
        self.state.lock().unwrap().hooks.push("failed");
    }
    fn image_transfer_rejected(&self) {
        self.state.lock().unwrap().hooks.push("rejected");
    }
    fn fast_chunk_gap_used(&self) {
        self.state.lock().unwrap().hooks.push("short-gap");
    }
    fn model_number_hint(&self) -> Option<&str> {
        (self.model == PrinterModel::MiniLink3).then_some("FI033")
    }
}

async fn device(
    model: PrinterModel,
    gate: bool,
    fault: Option<Fault>,
) -> (
    BlePrinterDevice,
    Arc<Mutex<State>>,
    Arc<Notify>,
    Arc<Notify>,
) {
    device_with_options(model, gate, fault, Options::default()).await
}

async fn device_with_options(
    model: PrinterModel,
    gate: bool,
    fault: Option<Fault>,
    options: Options,
) -> (
    BlePrinterDevice,
    Arc<Mutex<State>>,
    Arc<Notify>,
    Arc<Notify>,
) {
    let state = Arc::new(Mutex::new(State {
        pending: None,
        events: vec![],
        hooks: vec![],
    }));
    let entered = Arc::new(Notify::new());
    let released = Arc::new(Notify::new());
    let transport = TimedTransport {
        model,
        state: Arc::clone(&state),
        gate_data: AtomicBool::new(gate),
        entered: Arc::clone(&entered),
        released: Arc::clone(&released),
        fault,
        options,
    };
    let device = BlePrinterDevice::new(Box::new(transport), "Pacing test Printer".into())
        .await
        .unwrap();
    state.lock().unwrap().events.clear();
    (device, state, entered, released)
}

fn jpeg(model: PrinterModel) -> Vec<u8> {
    let spec = model.spec();
    let image = RgbImage::from_fn(spec.width, spec.height, |x, y| {
        if x < spec.width / 3 && y < spec.height / 3 {
            Rgb([210, 40, 20])
        } else {
            Rgb([40, 110, 190])
        }
    });
    let mut data = vec![];
    JpegEncoder::new_with_quality(&mut data, 80)
        .encode(
            image.as_raw(),
            spec.width,
            spec.height,
            ExtendedColorType::Rgb8,
        )
        .unwrap();
    assert!(data.len() <= spec.max_image_size);
    data
}

fn sent_opcodes(state: &Arc<Mutex<State>>) -> Vec<u16> {
    state
        .lock()
        .unwrap()
        .events
        .iter()
        .filter(|event| event.sent)
        .map(|event| event.packet.opcode)
        .collect()
}

#[tokio::test(start_paused = true)]
async fn every_model_waits_after_matching_chunk_ack_and_preserves_pre_execute_delay() {
    for &model in PrinterModel::all() {
        let (baseline_delay, pre_execute_delay) = match model {
            PrinterModel::Mini => (0, 0),
            PrinterModel::MiniLink3 => (75, 1000),
            PrinterModel::Square => (150, 1000),
            PrinterModel::Wide => (150, 0),
        };
        assert_eq!(model.spec().packet_delay_ms, baseline_delay);
        assert_eq!(model.spec().pre_execute_delay_ms, pre_execute_delay);
        let preferred_delay = data_packet_delay_ms_for_context(model, true, 236, false, false);
        let jpeg = jpeg(model);
        let (device, state, _, _) = device_with_options(
            model,
            false,
            None,
            Options {
                delay: Some(preferred_delay),
                ..Options::default()
            },
        )
        .await;
        device
            .print_prepared_jpeg(&jpeg, model, model.spec().flip_vertical, 0, None)
            .await
            .unwrap();
        let state = state.lock().unwrap();
        let data_sent: Vec<_> = state
            .events
            .iter()
            .filter(|event| event.sent && event.packet.opcode == OP_DATA)
            .collect();
        let data_acked: Vec<_> = state
            .events
            .iter()
            .filter(|event| !event.sent && event.packet.opcode == OP_DATA)
            .collect();
        assert!(data_sent.len() > 1);
        assert_eq!(data_sent.len(), data_acked.len());
        for (index, (sent, acked)) in data_sent.iter().zip(&data_acked).enumerate() {
            assert_eq!(
                u32::from_be_bytes(sent.packet.payload[..4].try_into().unwrap()),
                index as u32
            );
            assert_eq!(
                u32::from_be_bytes(acked.packet.payload[1..5].try_into().unwrap()),
                index as u32
            );
            assert_eq!(acked.at - sent.at, Duration::from_millis(17));
            if index + 1 < data_sent.len() {
                assert_eq!(
                    data_sent[index + 1].at - acked.at,
                    Duration::from_millis(preferred_delay)
                );
            }
        }
        let end = state
            .events
            .iter()
            .find(|event| event.sent && event.packet.opcode == OP_DOWNLOAD_END)
            .unwrap();
        assert_eq!(
            end.at - data_acked.last().unwrap().at,
            Duration::from_millis(baseline_delay)
        );
        let led = state
            .events
            .iter()
            .find(|event| !event.sent && event.packet.opcode == OP_LED_PATTERN_SETTINGS)
            .unwrap();
        let print = state
            .events
            .iter()
            .find(|event| event.sent && event.packet.opcode == OP_PRINT_IMAGE)
            .unwrap();
        assert_eq!(print.at - led.at, Duration::from_millis(pre_execute_delay));
        assert_eq!(
            state
                .events
                .iter()
                .filter(|event| event.sent && event.packet.opcode == OP_PRINT_IMAGE)
                .count(),
            1
        );
        let transferred: Vec<_> = data_sent
            .iter()
            .flat_map(|event| event.packet.payload[4..].iter().copied())
            .collect();
        assert_eq!(&transferred[..jpeg.len()], jpeg);
        assert!(transferred[jpeg.len()..].iter().all(|byte| *byte == 0));
    }
}

#[tokio::test(start_paused = true)]
async fn held_chunk_ack_blocks_next_chunks_and_other_device_operations() {
    let model = PrinterModel::Square;
    let jpeg = jpeg(model);
    let (device, state, entered, released) = device(model, true, None).await;
    let device = Arc::new(device);
    let printing_device = Arc::clone(&device);
    let print = tokio::spawn(async move {
        printing_device
            .print_prepared_jpeg(&jpeg, model, false, 0, None)
            .await
    });
    entered.notified().await;
    let led_device = Arc::clone(&device);
    let led = tokio::spawn(async move { led_device.set_led(1, 2, 3, 0).await });
    tokio::time::advance(Duration::from_millis(500)).await;
    assert_eq!(sent_opcodes(&state), [OP_DOWNLOAD_START, OP_DATA]);
    released.notify_one();
    print.await.unwrap().unwrap();
    led.await.unwrap().unwrap();
    let opcodes = sent_opcodes(&state);
    assert_eq!(
        &opcodes[opcodes.len() - 2..],
        [OP_PRINT_IMAGE, OP_LED_PATTERN_SETTINGS]
    );
}

#[tokio::test(start_paused = true)]
async fn rejection_write_failure_or_timeout_never_advances_replays_or_waits_for_chunk_pacing() {
    let model = PrinterModel::Square;
    for fault in [Fault::Reject, Fault::Timeout, Fault::Write] {
        let jpeg = jpeg(model);
        let (device, state, _, _) = device(model, false, Some(fault)).await;
        let started = Instant::now();
        assert!(
            device
                .print_prepared_jpeg(&jpeg, model, false, 0, None)
                .await
                .is_err()
        );
        assert_eq!(
            sent_opcodes(&state),
            [OP_DOWNLOAD_START, OP_DATA, OP_DOWNLOAD_CANCEL]
        );
        //3ms successful DownloadStart ACK, then at most17ms for a rejected Data ACK.
        assert!(started.elapsed() <= Duration::from_millis(20));
    }
}

#[tokio::test(start_paused = true)]
async fn cancelled_post_ack_wait_never_continues_with_next_chunk_or_physical_print() {
    let model = PrinterModel::Square;
    let jpeg = jpeg(model);
    let (device, state, _, _) = device(model, false, None).await;
    let task = tokio::spawn(async move {
        device
            .print_prepared_jpeg(&jpeg, model, false, 0, None)
            .await
    });
    loop {
        if state
            .lock()
            .unwrap()
            .events
            .iter()
            .any(|event| !event.sent && event.packet.opcode == OP_DATA)
        {
            break;
        }
        tokio::time::advance(Duration::from_millis(1)).await;
    }
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    tokio::time::advance(Duration::from_secs(2)).await;
    assert_eq!(sent_opcodes(&state), [OP_DOWNLOAD_START, OP_DATA]);
}

#[tokio::test(start_paused = true)]
async fn wrong_model_or_flip_declaration_never_reaches_download_even_with_fast_models() {
    for &model in PrinterModel::all() {
        let jpeg = jpeg(model);
        let (device, state, _, _) = device(model, false, None).await;
        assert!(
            device
                .print_prepared_jpeg(&jpeg, model, !model.spec().flip_vertical, 0, None)
                .await
                .is_err()
        );
        assert!(sent_opcodes(&state).is_empty());
        let wrong = if model == PrinterModel::Mini {
            PrinterModel::MiniLink3
        } else {
            PrinterModel::Mini
        };
        assert!(
            device
                .print_prepared_jpeg(&jpeg, wrong, model.spec().flip_vertical, 0, None)
                .await
                .is_err()
        );
        assert!(sent_opcodes(&state).is_empty());
    }
}

#[tokio::test(start_paused = true)]
async fn shared_production_download_preserves_final_settle_and_cancel_ack_without_led_or_print() {
    let model = PrinterModel::Square;
    let bytes = jpeg(model);
    let preferred_delay = data_packet_delay_ms_for_context(model, true, 236, false, false);
    let (device, state, _, _) = device_with_options(
        model,
        false,
        None,
        Options {
            delay: Some(preferred_delay),
            ..Options::default()
        },
    )
    .await;
    let started = Instant::now();
    device
        .download_prepared_jpeg_and_cancel(&bytes, model, false, None)
        .await
        .unwrap();
    let state = state.lock().unwrap();
    let sent: Vec<_> = state
        .events
        .iter()
        .filter(|event| event.sent && event.packet.opcode == OP_DATA)
        .collect();
    let acked: Vec<_> = state
        .events
        .iter()
        .filter(|event| !event.sent && event.packet.opcode == OP_DATA)
        .collect();
    for index in 0..sent.len() - 1 {
        assert_eq!(
            sent[index + 1].at - acked[index].at,
            Duration::from_millis(preferred_delay)
        );
    }
    let end = state
        .events
        .iter()
        .find(|event| event.sent && event.packet.opcode == OP_DOWNLOAD_END)
        .unwrap();
    assert_eq!(
        end.at - acked.last().unwrap().at,
        Duration::from_millis(150)
    );
    assert_eq!(
        started.elapsed(),
        Duration::from_millis(
            (sent.len() as u64 - 1) * preferred_delay + 150 + sent.len() as u64 * 17 + 9
        )
    );
    assert_eq!(state.hooks.first(), Some(&"started"));
    assert_eq!(state.hooks.last(), Some(&"completed"));
    assert_eq!(
        state
            .hooks
            .iter()
            .filter(|hook| **hook == "short-gap")
            .count(),
        if preferred_delay < 150 {
            sent.len() - 1
        } else {
            0
        }
    );
    assert!(!state.hooks.contains(&"failed"));
    let opcodes: Vec<_> = state
        .events
        .iter()
        .filter(|event| event.sent)
        .map(|event| event.packet.opcode)
        .collect();
    assert_eq!(
        &opcodes[opcodes.len() - 2..],
        [OP_DOWNLOAD_END, OP_DOWNLOAD_CANCEL]
    );
    assert!(!opcodes.contains(&OP_LED_PATTERN_SETTINGS));
    assert!(!opcodes.contains(&OP_PRINT_IMAGE));
    assert!(
        state
            .events
            .iter()
            .any(|event| !event.sent && event.packet.opcode == OP_DOWNLOAD_CANCEL)
    );
    let transferred: Vec<_> = sent
        .iter()
        .flat_map(|event| event.packet.payload[4..].iter().copied())
        .collect();
    assert_eq!(&transferred[..bytes.len()], bytes);
    assert!(transferred[bytes.len()..].iter().all(|byte| *byte == 0));
}

#[tokio::test(start_paused = true)]
async fn known_external_rejections_after_fast_gap_use_rejected_hook_not_pacing_failure() {
    let model = PrinterModel::Square;
    for status in [178, 179, 180] {
        for opcode in [OP_DATA, OP_DOWNLOAD_END, OP_PRINT_IMAGE] {
            let options = Options {
                delay: Some(50),
                fault_index: 1,
                rejected_opcode: (opcode != OP_DATA).then_some(opcode),
                rejection_status: Some(status),
                ..Options::default()
            };
            let fault = (opcode == OP_DATA).then_some(Fault::Reject);
            let (device, state, _, _) = device_with_options(model, false, fault, options).await;
            assert!(
                device
                    .print_prepared_jpeg(&jpeg(model), model, false, 0, None)
                    .await
                    .is_err()
            );
            let state = state.lock().unwrap();
            assert!(state.hooks.contains(&"short-gap"));
            assert_eq!(state.hooks.last(), Some(&"rejected"));
            assert!(!state.hooks.contains(&"failed"));
            assert!(!state.hooks.contains(&"completed"));
            assert_eq!(
                state
                    .events
                    .iter()
                    .filter(|event| event.sent && event.packet.opcode == OP_PRINT_IMAGE)
                    .count(),
                usize::from(opcode == OP_PRINT_IMAGE)
            );
        }
    }
}

#[tokio::test(start_paused = true)]
async fn busy_unknown_or_transport_failure_after_fast_gap_use_failed_hook_without_replay() {
    let model = PrinterModel::Square;
    for (fault, status) in [
        (Fault::Reject, 181),
        (Fault::Reject, 199),
        (Fault::Timeout, 0),
        (Fault::Write, 0),
    ] {
        let (device, state, _, _) = device_with_options(
            model,
            false,
            Some(fault),
            Options {
                delay: Some(50),
                fault_index: 1,
                rejection_status: Some(status),
                ..Options::default()
            },
        )
        .await;
        assert!(
            device
                .print_prepared_jpeg(&jpeg(model), model, false, 0, None)
                .await
                .is_err()
        );
        let state = state.lock().unwrap();
        assert_eq!(state.hooks, ["started", "short-gap", "failed"]);
        let sent: Vec<_> = state
            .events
            .iter()
            .filter(|event| event.sent)
            .map(|event| event.packet.opcode)
            .collect();
        assert_eq!(
            sent,
            [OP_DOWNLOAD_START, OP_DATA, OP_DATA, OP_DOWNLOAD_CANCEL]
        );
    }
}

#[tokio::test(start_paused = true)]
async fn cancelling_first_shortened_wait_marks_failed_guard_and_never_continues_download() {
    let model = PrinterModel::Square;
    let (device, state, _, _) = device_with_options(
        model,
        false,
        None,
        Options {
            delay: Some(50),
            ..Options::default()
        },
    )
    .await;
    let task = tokio::spawn(async move {
        device
            .download_prepared_jpeg_and_cancel(&jpeg(model), model, false, None)
            .await
    });
    loop {
        if state.lock().unwrap().hooks.contains(&"short-gap") {
            break;
        }
        tokio::time::advance(Duration::from_millis(1)).await;
    }
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    tokio::time::advance(Duration::from_secs(1)).await;
    assert_eq!(
        state.lock().unwrap().hooks,
        ["started", "short-gap", "failed"]
    );
    assert_eq!(sent_opcodes(&state), [OP_DOWNLOAD_START, OP_DATA]);
}

#[tokio::test(start_paused = true)]
async fn shared_download_checks_cancel_ack_and_prepared_validation_before_reported_success() {
    let model = PrinterModel::Square;
    let (device, state, _, _) = device_with_options(
        model,
        false,
        None,
        Options {
            delay: Some(50),
            rejected_opcode: Some(OP_DOWNLOAD_CANCEL),
            rejection_status: Some(199),
            ..Options::default()
        },
    )
    .await;
    assert!(
        device
            .download_prepared_jpeg_and_cancel(&jpeg(model), model, false, None)
            .await
            .is_err()
    );
    assert_eq!(state.lock().unwrap().hooks.last(), Some(&"failed"));
    assert!(!state.lock().unwrap().hooks.contains(&"completed"));
    assert!(!sent_opcodes(&state).contains(&OP_PRINT_IMAGE));
    let (device, state, _, _) = device_with_options(
        model,
        false,
        None,
        Options {
            delay: Some(0),
            ..Options::default()
        },
    )
    .await;
    assert!(
        device
            .download_prepared_jpeg_and_cancel(&jpeg(model), model, true, None)
            .await
            .is_err()
    );
    assert!(sent_opcodes(&state).is_empty());
    assert!(state.lock().unwrap().hooks.is_empty());
}
