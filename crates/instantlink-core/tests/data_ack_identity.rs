//! Independent stale-notification and total-deadline checks for indexed Data ACKs.
use std::collections::VecDeque;
use std::sync::Mutex;
use std::time::Duration;

use async_trait::async_trait;
use instantlink_core::commands::{Command, OP_DATA, OP_DOWNLOAD_CANCEL};
use instantlink_core::protocol::Packet;
use instantlink_core::transport::Transport;
use instantlink_core::{PrinterError, PrinterModel, Result};
use tokio::time::Instant;

fn ack(index: u32) -> Packet {
    let mut payload = vec![0];
    payload.extend_from_slice(&index.to_be_bytes());
    Packet {
        opcode: OP_DATA,
        payload,
    }
}

#[test]
fn data_ack_matches_exact_index_or_explicit_one_byte_legacy_status() {
    let command = Command::Data {
        index: 42,
        data: vec![0x81; 1808],
    };
    let expected = command
        .response_expectation_for_model(PrinterModel::Square)
        .unwrap();
    assert!(expected.matches(&ack(42)));
    assert!(!expected.matches(&ack(41)));
    assert!(!expected.matches(&ack(43)));
    for status in [0, 12, 178, 255] {
        assert!(expected.matches(&Packet {
            opcode: OP_DATA,
            payload: vec![status]
        }));
    }
    for length in [0, 2, 3, 4, 6, 8] {
        assert!(!expected.matches(&Packet {
            opcode: OP_DATA,
            payload: vec![0; length]
        }));
    }
    let mut wrong_opcode = ack(42);
    wrong_opcode.opcode = OP_DOWNLOAD_CANCEL;
    assert!(!expected.matches(&wrong_opcode));
}

struct Notifications {
    sent: Mutex<Vec<Vec<u8>>>,
    replies: Mutex<VecDeque<(Duration, Packet)>>,
}

impl Notifications {
    fn new(replies: Vec<(Duration, Packet)>) -> Self {
        Self {
            sent: Mutex::new(vec![]),
            replies: Mutex::new(replies.into()),
        }
    }
}

#[async_trait]
impl Transport for Notifications {
    async fn send(&self, data: &[u8]) -> Result<()> {
        self.sent.lock().unwrap().push(data.to_vec());
        Ok(())
    }
    async fn receive(&self, timeout: Duration) -> Result<Packet> {
        let next = self.replies.lock().unwrap().pop_front();
        let (delay, packet) = next.ok_or(PrinterError::Timeout)?;
        tokio::time::timeout(timeout, tokio::time::sleep(delay))
            .await
            .map_err(|_| PrinterError::Timeout)?;
        Ok(packet)
    }
    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<Packet> {
        self.send(data).await?;
        self.receive(timeout).await
    }
    async fn disconnect(&self) -> Result<()> {
        Ok(())
    }
}

#[tokio::test(start_paused = true)]
async fn stale_and_future_acks_are_skipped_without_retransmitting_current_chunk() {
    let transport = Notifications::new(vec![
        (Duration::from_millis(5), ack(0)),
        (Duration::from_millis(5), ack(2)),
        (Duration::from_millis(5), ack(1)),
    ]);
    let command = Command::Data {
        index: 1,
        data: vec![0x81; 1808],
    };
    let encoded = command.encode().unwrap();
    let start = Instant::now();
    let response = transport
        .send_and_receive_expected(
            &encoded,
            Duration::from_millis(20),
            command
                .response_expectation_for_model(PrinterModel::Square)
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response, ack(1));
    assert_eq!(start.elapsed(), Duration::from_millis(15));
    assert_eq!(*transport.sent.lock().unwrap(), vec![encoded]);
}

#[tokio::test(start_paused = true)]
async fn unmatched_acks_share_one_total_deadline_instead_of_extending_timeout() {
    let transport = Notifications::new(
        (0..10)
            .map(|_| (Duration::from_millis(6), ack(0)))
            .collect(),
    );
    let command = Command::Data {
        index: 1,
        data: vec![0x81; 1808],
    };
    let encoded = command.encode().unwrap();
    let start = Instant::now();
    let error = transport
        .send_and_receive_expected(
            &encoded,
            Duration::from_millis(20),
            command
                .response_expectation_for_model(PrinterModel::Square)
                .unwrap(),
        )
        .await
        .unwrap_err();
    assert!(matches!(error, PrinterError::Timeout));
    assert_eq!(start.elapsed(), Duration::from_millis(20));
    assert_eq!(*transport.sent.lock().unwrap(), vec![encoded]);
}

#[tokio::test(start_paused = true)]
async fn malformed_ack_lengths_are_skipped_before_valid_identity_and_never_trigger_replay() {
    let mut replies: Vec<_> = [0, 2, 3, 4, 6, 8]
        .into_iter()
        .map(|length| {
            (
                Duration::from_millis(1),
                Packet {
                    opcode: OP_DATA,
                    payload: vec![0; length],
                },
            )
        })
        .collect();
    replies.push((Duration::from_millis(1), ack(u32::MAX)));
    let transport = Notifications::new(replies);
    let command = Command::Data {
        index: u32::MAX,
        data: vec![0x81; 900],
    };
    let encoded = command.encode().unwrap();
    let response = transport
        .send_and_receive_expected(
            &encoded,
            Duration::from_millis(20),
            command
                .response_expectation_for_model(PrinterModel::Square)
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response, ack(u32::MAX));
    assert_eq!(*transport.sent.lock().unwrap(), vec![encoded]);
}

#[test]
fn unverified_models_preserve_existing_status_tail_compatibility() {
    let command = Command::Data {
        index: 42,
        data: vec![0x81; 900],
    };
    for model in [
        PrinterModel::Mini,
        PrinterModel::MiniLink3,
        PrinterModel::Wide,
    ] {
        let expected = command.response_expectation_for_model(model).unwrap();
        for payload in [
            vec![0],
            vec![0, 99],
            vec![0, 0, 0, 0],
            vec![0, 99, 98, 97, 96],
            vec![0, 1, 2, 3, 4, 5, 6, 7],
        ] {
            assert!(
                expected.matches(&Packet {
                    opcode: OP_DATA,
                    payload
                }),
                "Unverified response-tail layouts keep opcode compatibility"
            );
        }
        assert!(expected.matches(&ack(41)));
        assert!(expected.matches(&ack(43)));
        let mut other = ack(42);
        other.opcode = OP_DOWNLOAD_CANCEL;
        assert!(!expected.matches(&other));
    }
    assert!(
        command.response_expectation().unwrap().matches(&ack(41)),
        "Model-unknown generic transport retains old behavior"
    );
}
