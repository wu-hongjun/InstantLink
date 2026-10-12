//! Independent fault-injection tests of the production write/query helpers.
use super::*;
use std::sync::Arc;
use tokio::sync::Notify;

fn make_session(payload_size: usize) -> WriteSession {
    WriteSession {
        device: format!("independent-test-{}", Uuid::new_v4()),
        payload_size: NonZeroUsize::new(payload_size).unwrap(),
        poisoned: AtomicBool::new(false),
        enlarged_attempted: AtomicBool::new(false),
    }
}

fn policy(session: &WriteSession) -> (bool, bool) {
    let devices = FALLBACK_DEVICES.lock().unwrap();
    (
        devices.requires_reset(&session.device),
        devices.contains(&session.device),
    )
}

#[tokio::test]
async fn small_control_failure_at_large_cap_requires_reset_without_downgrading() {
    let session = make_session(236);
    let error = write_fragments(&[0x41; 15], &session, |_| async {
        Err(PrinterError::Ble("idle connection ended".into()))
    })
    .await
    .unwrap_err();
    assert!(matches!(error, PrinterError::Ble(_)));
    assert!(session.poisoned.load(Ordering::Acquire));
    assert_eq!(policy(&session), (true, false));
    let calls = AtomicBool::new(false);
    assert!(
        write_fragments(&[0x42; 15], &session, |_| {
            calls.store(true, Ordering::Release);
            async { Ok(()) }
        })
        .await
        .is_err()
    );
    assert!(
        !calls.load(Ordering::Acquire),
        "Poisoned transport cannot send a cleanup or another packet"
    );
}

#[tokio::test]
async fn actual_enlarged_failure_downgrades_only_that_device_after_reset() {
    let session = make_session(236);
    let unrelated = make_session(236);
    let calls = StdMutex::new(Vec::new());
    assert!(
        write_fragments(&[0x81; 1819], &session, |fragment| {
            let mut calls = calls.lock().unwrap();
            calls.push(fragment);
            let fail = calls.len() == 2;
            async move {
                if fail {
                    Err(PrinterError::Ble("second write failed".into()))
                } else {
                    Ok(())
                }
            }
        })
        .await
        .is_err()
    );
    assert_eq!(
        calls
            .lock()
            .unwrap()
            .iter()
            .map(Vec::len)
            .collect::<Vec<_>>(),
        [236, 236]
    );
    assert_eq!(policy(&session), (true, true));
    assert_eq!(policy(&unrelated), (false, false));
    let fallback = protocol::fragment_payload_size(Some(247), conservative_device(&session.device));
    assert_eq!(fallback, 182);
    let fresh = WriteSession {
        device: session.device.clone(),
        ..make_session(fallback)
    };
    let delivered = StdMutex::new(Vec::new());
    write_fragments(&[0x19; 1819], &fresh, |fragment| {
        delivered.lock().unwrap().push(fragment);
        async { Ok(()) }
    })
    .await
    .unwrap();
    assert_eq!(delivered.lock().unwrap().len(), 10);
    assert_eq!(delivered.lock().unwrap().concat(), vec![0x19; 1819]);
}

#[tokio::test]
async fn interrupted_small_mtu_and_legacy_writes_both_require_reset_without_large_cap_fallback() {
    for size in [20, 182] {
        let session = make_session(size);
        let count = std::sync::atomic::AtomicUsize::new(0);
        assert!(
            write_fragments(&[0x81; 900], &session, |_| {
                let count = count.fetch_add(1, Ordering::SeqCst) + 1;
                async move {
                    if count == 2 {
                        Err(PrinterError::Ble("partial packet failed".into()))
                    } else {
                        Ok(())
                    }
                }
            })
            .await
            .is_err()
        );
        assert_eq!(count.load(Ordering::SeqCst), 2);
        assert_eq!(policy(&session), (true, false));
        assert!(
            write_fragments(&[0; 7], &session, |_| {
                count.fetch_add(1, Ordering::SeqCst);
                async { Ok(()) }
            })
            .await
            .is_err()
        );
        assert_eq!(count.load(Ordering::SeqCst), 2);
    }
}

#[tokio::test(start_paused = true)]
async fn hanging_write_has_bounded_timeout_and_never_replays() {
    let session = make_session(236);
    let calls = std::sync::atomic::AtomicUsize::new(0);
    let start = tokio::time::Instant::now();
    let error = write_fragments(&[0x81; 1819], &session, |_| {
        calls.fetch_add(1, Ordering::SeqCst);
        std::future::pending::<Result<()>>()
    })
    .await
    .unwrap_err();
    assert!(matches!(error, PrinterError::Timeout));
    assert_eq!(start.elapsed(), DEFAULT_WRITE_TIMEOUT);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(policy(&session), (true, true));
}

#[tokio::test]
async fn dropping_running_write_poisons_session_before_any_following_send() {
    let session = Arc::new(make_session(236));
    let entered = Arc::new(Notify::new());
    let writer_session = Arc::clone(&session);
    let writer_entered = Arc::clone(&entered);
    let write = tokio::spawn(async move {
        write_fragments(&[0x41; 1819], &writer_session, |_| {
            writer_entered.notify_one();
            std::future::pending::<Result<()>>()
        })
        .await
    });
    entered.notified().await;
    write.abort();
    assert!(write.await.unwrap_err().is_cancelled());
    assert_eq!(policy(&session), (true, true));
    assert!(
        write_fragments(&[0x42; 15], &session, |_| async {
            panic!("Cancelled transport must not call the physical writer again")
        })
        .await
        .is_err()
    );
}

#[tokio::test]
async fn successful_large_packet_does_not_attribute_a_later_small_failure_to_large_writes() {
    let session = make_session(236);
    write_fragments(&[0x81; 1819], &session, |_| async { Ok(()) })
        .await
        .unwrap();
    assert_eq!(policy(&session), (false, false));
    assert!(
        write_fragments(&[0x41; 7], &session, |_| async {
            Err(PrinterError::Ble("later small control failure".into()))
        })
        .await
        .is_err()
    );
    assert_eq!(policy(&session), (true, false));
}

#[tokio::test]
async fn missing_ack_after_large_write_poisons_and_downgrades_without_rewriting() {
    let session = make_session(244);
    let ack_guard = session.delivery().unwrap();
    write_fragments(&[0x81; 1819], &session, |_| async { Ok(()) })
        .await
        .unwrap();
    assert_eq!(policy(&session), (false, false));
    drop(ack_guard);
    assert_eq!(policy(&session), (true, true));
}

#[test]
fn completing_link_reset_clears_reset_only_failure_and_retains_only_actual_large_write_downgrade() {
    let mut devices = FallbackDevices::default();
    devices.insert("small-control-failed", false);
    assert!(devices.requires_reset("small-control-failed"));
    devices.reset_completed("small-control-failed");
    assert!(!devices.requires_reset("small-control-failed"));
    assert!(!devices.contains("small-control-failed"));
    assert!(!devices.devices.contains_key("small-control-failed"));
    devices.insert("large-fragment-failed", true);
    devices.reset_completed("large-fragment-failed");
    assert!(!devices.requires_reset("large-fragment-failed"));
    assert!(devices.contains("large-fragment-failed"));
    devices.insert("large-fragment-failed", false);
    assert!(devices.requires_reset("large-fragment-failed"));
    assert!(devices.contains("large-fragment-failed"));
    devices.reset_completed("unrelated-device");
    assert!(devices.contains("large-fragment-failed"));
    assert!(devices.requires_reset("large-fragment-failed"));
}

#[test]
fn reset_and_conservative_policy_stay_separate_and_capacity_never_evicts_a_failure() {
    let mut devices = FallbackDevices::default();
    devices.insert("small-failure", false);
    assert!(devices.requires_reset("small-failure"));
    assert!(!devices.contains("small-failure"));
    devices.insert("small-failure", true);
    devices.insert("small-failure", false);
    assert!(devices.contains("small-failure"));
    for index in 1..MAX_FALLBACK_DEVICES {
        devices.insert(&format!("device-{index}"), index % 2 == 0);
    }
    assert!(!devices.requires_reset("outside-capacity"));
    devices.insert("outside-capacity", true);
    assert!(devices.saturated);
    assert_eq!(devices.devices.len(), MAX_FALLBACK_DEVICES);
    assert!(devices.contains("small-failure"));
    assert!(devices.contains("unseen-device"));
    assert!(devices.requires_reset("unseen-device"));
}

#[tokio::test]
async fn abandoned_discovery_listener_guard_stops_owned_resource_task() {
    struct ActiveResource(Arc<AtomicBool>);
    impl Drop for ActiveResource {
        fn drop(&mut self) {
            self.0.store(false, Ordering::Release);
        }
    }
    let active = Arc::new(AtomicBool::new(true));
    let resource = ActiveResource(Arc::clone(&active));
    let entered = Arc::new(Notify::new());
    let task_entered = Arc::clone(&entered);
    let handle = tokio::spawn(async move {
        let _resource = resource;
        task_entered.notify_one();
        std::future::pending::<()>().await;
    });
    let guard = AbortOnDrop(Some(handle));
    entered.notified().await;
    drop(guard);
    tokio::task::yield_now().await;
    assert!(
        !active.load(Ordering::Acquire),
        "Abandoned query/startup must release its owned listener task"
    );
}

#[cfg(target_os = "linux")]
mod linux_query {
    use super::*;
    use dbus::arg::{PropMap, RefArg, Variant};
    use std::collections::HashMap;

    const DEVICE: &str = "/org/bluez/hci0/dev_FA_AB_BC_C7_95_64";
    const SERVICE: &str = "/org/bluez/hci0/dev_FA_AB_BC_C7_95_64/service001";
    const CHAR: &str = "/org/bluez/hci0/dev_FA_AB_BC_C7_95_64/service001/char002";

    fn put<T: RefArg + 'static>(props: &mut PropMap, name: &str, value: T) {
        props.insert(name.to_owned(), Variant(Box::new(value)));
    }

    fn add_object(objects: &mut BluezObjects, path: &str, interface: &str, props: PropMap) {
        objects.insert(
            dbus::Path::new(path.to_owned()).unwrap(),
            HashMap::from([(interface.to_owned(), props)]),
        );
    }

    fn add_service(objects: &mut BluezObjects, path: &str, device: &str) {
        let mut props = PropMap::new();
        put(&mut props, "UUID", SERVICE_UUID.to_string());
        put(
            &mut props,
            "Device",
            dbus::Path::new(device.to_owned()).unwrap(),
        );
        add_object(objects, path, "org.bluez.GattService1", props);
    }

    fn add_char(objects: &mut BluezObjects, path: &str, service: &str, mtu: Option<u16>) {
        let mut props = PropMap::new();
        put(&mut props, "UUID", WRITE_CHAR_UUID.to_string());
        put(
            &mut props,
            "Service",
            dbus::Path::new(service.to_owned()).unwrap(),
        );
        put(
            &mut props,
            "Flags",
            vec!["write-without-response".to_owned()],
        );
        if let Some(mtu) = mtu {
            put(&mut props, "MTU", mtu);
        }
        add_object(objects, path, "org.bluez.GattCharacteristic1", props);
    }

    fn fixture() -> BluezObjects {
        let mut objects = BluezObjects::new();
        let mut device = PropMap::new();
        put(&mut device, "Connected", true);
        add_object(&mut objects, DEVICE, "org.bluez.Device1", device);
        add_service(&mut objects, SERVICE, DEVICE);
        add_char(&mut objects, CHAR, SERVICE, Some(247));
        objects
    }

    fn props<'a>(objects: &'a mut BluezObjects, path: &str, interface: &str) -> &'a mut PropMap {
        objects
            .get_mut(&dbus::Path::new(path.to_owned()).unwrap())
            .unwrap()
            .get_mut(interface)
            .unwrap()
    }

    #[test]
    fn query_requires_exact_connected_device_and_never_reuses_another_device_mtu() {
        let mut objects = fixture();
        assert_eq!(bluez_write_mtu(&objects, DEVICE), Some(247));
        assert_eq!(
            bluez_write_mtu(&objects, "/org/bluez/hci1/dev_FA_AB_BC_C7_95_64"),
            None
        );
        put(
            props(&mut objects, DEVICE, "org.bluez.Device1"),
            "Connected",
            false,
        );
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
        put(
            props(&mut objects, DEVICE, "org.bluez.Device1"),
            "Connected",
            true,
        );
        put(
            props(&mut objects, CHAR, "org.bluez.GattCharacteristic1"),
            "MTU",
            185u16,
        );
        assert_eq!(
            bluez_write_mtu(&objects, DEVICE),
            Some(185),
            "Reconnection must read the newly exported value"
        );
        assert_eq!(
            protocol::fragment_payload_size(bluez_write_mtu(&objects, DEVICE), false),
            182
        );
    }

    #[test]
    fn malformed_duplicate_characteristic_cannot_select_valid_sibling_mtu() {
        let mut objects = fixture();
        add_char(&mut objects, &format!("{SERVICE}/char003"), SERVICE, None);
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
        let duplicate = props(
            &mut objects,
            &format!("{SERVICE}/char003"),
            "org.bluez.GattCharacteristic1",
        );
        duplicate.remove("Flags");
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
    }

    #[test]
    fn duplicate_instax_service_is_ambiguous_even_without_its_write_characteristic() {
        let mut objects = fixture();
        add_service(&mut objects, &format!("{DEVICE}/service009"), DEVICE);
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
    }

    #[test]
    fn query_rejects_wrong_service_parent_flags_and_malformed_mtu_type() {
        let mut objects = fixture();
        put(
            props(&mut objects, CHAR, "org.bluez.GattCharacteristic1"),
            "MTU",
            247u32,
        );
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
        let mut objects = fixture();
        put(
            props(&mut objects, CHAR, "org.bluez.GattCharacteristic1"),
            "Flags",
            vec!["write".to_owned()],
        );
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
        let mut objects = fixture();
        put(
            props(&mut objects, SERVICE, "org.bluez.GattService1"),
            "Device",
            dbus::Path::new("/org/bluez/hci1/dev_FA_AB_BC_C7_95_64").unwrap(),
        );
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
        let mut objects = fixture();
        put(
            props(&mut objects, SERVICE, "org.bluez.GattService1"),
            "UUID",
            NOTIFY_CHAR_UUID.to_string(),
        );
        assert_eq!(bluez_write_mtu(&objects, DEVICE), None);
    }
}

#[test]
fn diagnostic_command_whitelist_rejects_every_print_or_actuator_command() {
    for command in [
        Command::PrintImage,
        Command::Shutdown,
        Command::Reset,
        Command::LedPatternSettings {
            red: 1,
            green: 2,
            blue: 3,
            pattern: 0,
        },
        Command::DeviceInfo,
    ] {
        assert!(!diagnostic_command_allowed(&command));
    }
    for command in [
        Command::ImageSupportInfo,
        Command::BatteryStatus,
        Command::PrinterFunctionInfo,
        Command::HistoryInfo,
        Command::DownloadStart {
            image_size: 1000,
            print_option: 0,
        },
        Command::Data {
            index: 0,
            data: vec![0; 1808],
        },
        Command::DownloadEnd,
        Command::DownloadCancel,
    ] {
        assert!(diagnostic_command_allowed(&command));
        assert!(command.response_expectation().is_some());
    }
}

#[tokio::test]
async fn diagnostic_244_guards_preserve_preferred_236_and_keep_downgrade_when_real_guard_saw_no_large_write()
 {
    for failed_ack in [false, true] {
        let real = make_session(236);
        let diagnostic = WriteSession {
            device: real.device.clone(),
            ..make_session(244)
        };
        let real_delivery = real.delivery().unwrap();
        let diagnostic_delivery = diagnostic.delivery().unwrap();
        write_fragments(&[0x81; 1819], &diagnostic, |_| async { Ok(()) })
            .await
            .unwrap();
        assert!(!real.enlarged_attempted.load(Ordering::Acquire));
        assert!(diagnostic.enlarged_attempted.load(Ordering::Acquire));
        if failed_ack {
            drop(diagnostic_delivery);
            drop(real_delivery);
            assert!(real.poisoned.load(Ordering::Acquire));
            assert_eq!(
                policy(&real),
                (true, true),
                "Real guard's false flag must not erase actual diagnostic downgrade"
            );
            assert_eq!(
                protocol::fragment_payload_size(Some(247), conservative_device(&real.device)),
                182
            );
            assert_eq!(
                protocol::diagnostic_fragment_payload_size(
                    Some(247),
                    conservative_device(&real.device)
                ),
                182
            );
            assert!(
                write_fragments(&[0x42; 7], &real, |_| async {
                    panic!("Poisoned real session must not bypass through diagnostic cap")
                })
                .await
                .is_err()
            );
        } else {
            diagnostic_delivery.complete();
            real_delivery.complete();
            assert!(!real.poisoned.load(Ordering::Acquire));
            assert_eq!(policy(&real), (false, false));
            let accepted = StdMutex::new(Vec::new());
            write_fragments(&[0x41; 1819], &real, |fragment| {
                accepted.lock().unwrap().push(fragment);
                async { Ok(()) }
            })
            .await
            .unwrap();
            assert_eq!(accepted.lock().unwrap().len(), 8);
            assert_eq!(accepted.lock().unwrap()[0].len(), 236);
        }
        assert_eq!(real.payload_size.get(), 236);
        assert_eq!(diagnostic.payload_size.get(), 244);
    }
}

#[tokio::test]
async fn aborted_large_diagnostic_poisons_real_preferred_session_and_retains_actual_downgrade() {
    let real = Arc::new(make_session(236));
    let diagnostic = Arc::new(WriteSession {
        device: real.device.clone(),
        ..make_session(244)
    });
    let task_real = Arc::clone(&real);
    let task_diagnostic = Arc::clone(&diagnostic);
    let entered = Arc::new(Notify::new());
    let task_entered = Arc::clone(&entered);
    let task = tokio::spawn(async move {
        let _real_delivery = task_real.delivery().unwrap();
        let _diagnostic_delivery = task_diagnostic.delivery().unwrap();
        write_fragments(&[0x81; 1819], &task_diagnostic, |_| {
            task_entered.notify_one();
            std::future::pending::<Result<()>>()
        })
        .await
    });
    entered.notified().await;
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert!(real.poisoned.load(Ordering::Acquire));
    assert!(diagnostic.poisoned.load(Ordering::Acquire));
    assert_eq!(policy(&real), (true, true));
    assert_eq!(real.payload_size.get(), 236);
    assert_eq!(diagnostic.payload_size.get(), 244);
}

#[tokio::test]
async fn disconnect_attempt_is_never_gated_by_a_failing_connection_query() {
    let calls = StdMutex::new(Vec::new());
    let result = disconnect_and_verify(
        || async {
            calls.lock().unwrap().push("disconnect");
            Ok(())
        },
        || async {
            calls.lock().unwrap().push("query");
            Err(PrinterError::Ble("connection query failed".into()))
        },
    )
    .await;
    assert!(result.is_err());
    assert_eq!(*calls.lock().unwrap(), ["disconnect", "query"]);
}

#[tokio::test]
async fn authoritative_disconnected_state_accepts_failed_disconnect_rpc() {
    let calls = StdMutex::new(Vec::new());
    disconnect_and_verify(
        || async {
            calls.lock().unwrap().push("disconnect");
            Err(PrinterError::Ble("RPC failed after link closed".into()))
        },
        || async {
            calls.lock().unwrap().push("query");
            Ok(false)
        },
    )
    .await
    .unwrap();
    assert_eq!(*calls.lock().unwrap(), ["disconnect", "query"]);
}

#[tokio::test(start_paused = true)]
async fn authoritative_disconnected_state_accepts_timed_out_disconnect_rpc() {
    let start = tokio::time::Instant::now();
    disconnect_and_verify(std::future::pending::<Result<()>>, || async { Ok(false) })
        .await
        .unwrap();
    assert_eq!(start.elapsed(), DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT);
}

#[tokio::test]
async fn connected_or_unknown_state_never_reports_success_after_disconnect() {
    for rpc_fails in [false, true] {
        for unknown in [false, true] {
            assert!(
                disconnect_and_verify(
                    || async move {
                        if rpc_fails {
                            Err(PrinterError::Ble("RPC failed".into()))
                        } else {
                            Ok(())
                        }
                    },
                    || async move {
                        if unknown {
                            Err(PrinterError::Ble("query unavailable".into()))
                        } else {
                            Ok(true)
                        }
                    },
                )
                .await
                .is_err()
            );
        }
    }
}

#[tokio::test(start_paused = true)]
async fn disconnect_and_verification_have_independent_bounded_deadlines() {
    let start = tokio::time::Instant::now();
    assert!(
        disconnect_and_verify(
            std::future::pending::<Result<()>>,
            std::future::pending::<Result<bool>>,
        )
        .await
        .is_err()
    );
    assert_eq!(
        start.elapsed(),
        DEFAULT_PHYSICAL_DISCONNECT_TIMEOUT + DEFAULT_DISCONNECT_TIMEOUT
    );
}

#[tokio::test]
async fn abandoned_teardown_records_reset_without_misattributing_old_large_write() {
    for cancel_during_query in [false, true] {
        let session = Arc::new(make_session(236));
        // A previous successful large write is not an enlarged delivery failure.
        session.enlarged_attempted.store(true, Ordering::Release);
        let task_session = Arc::clone(&session);
        let entered = Arc::new(Notify::new());
        let task_entered = Arc::clone(&entered);
        let task = tokio::spawn(async move {
            let _reset_guard = LinkResetGuard {
                session: &task_session,
                armed: true,
            };
            task_session.require_link_reset();
            disconnect_and_verify(
                || async {
                    if cancel_during_query {
                        Ok(())
                    } else {
                        task_entered.notify_one();
                        std::future::pending::<Result<()>>().await
                    }
                },
                || async {
                    task_entered.notify_one();
                    std::future::pending::<Result<bool>>().await
                },
            )
            .await
        });
        entered.notified().await;
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        assert!(session.poisoned.load(Ordering::Acquire));
        assert_eq!(
            policy(&session),
            (true, false),
            "Cancelled teardown requires reset but never creates an enlarged-fragment downgrade"
        );
        assert!(
            write_fragments(&[0; 7], &session, |_| async {
                panic!("Closing session must reject further writes")
            })
            .await
            .is_err()
        );
    }
}

#[tokio::test]
async fn confirmed_teardown_clears_reset_and_preserves_existing_fragment_preference() {
    for already_conservative in [false, true] {
        let session = make_session(236);
        if already_conservative {
            FALLBACK_DEVICES
                .lock()
                .unwrap()
                .insert(&session.device, true);
        }
        session.enlarged_attempted.store(true, Ordering::Release);
        let guard = LinkResetGuard {
            session: &session,
            armed: true,
        };
        session.require_link_reset();
        disconnect_and_verify(|| async { Ok(()) }, || async { Ok(false) })
            .await
            .unwrap();
        FALLBACK_DEVICES
            .lock()
            .unwrap()
            .reset_completed(&session.device);
        guard.complete();
        assert_eq!(policy(&session), (false, already_conservative));
        assert!(
            session.poisoned.load(Ordering::Acquire),
            "Closed instance stays unusable even after confirmed physical disconnect"
        );
        assert_eq!(
            protocol::fragment_payload_size(Some(247), conservative_device(&session.device)),
            if already_conservative { 182 } else { 236 }
        );
        assert_eq!(
            protocol::diagnostic_fragment_payload_size(
                Some(247),
                conservative_device(&session.device)
            ),
            if already_conservative { 182 } else { 244 }
        );
    }
}

#[cfg(target_os = "linux")]
#[tokio::test(start_paused = true)]
async fn linux_physical_disconnect_can_complete_after_bluez_two_second_timer() {
    let closed = AtomicBool::new(false);
    let start = tokio::time::Instant::now();
    disconnect_and_verify(
        || async {
            tokio::time::sleep(Duration::from_millis(2800)).await;
            closed.store(true, Ordering::Release);
            Ok(())
        },
        || async { Ok(!closed.load(Ordering::Acquire)) },
    )
    .await
    .unwrap();
    assert_eq!(start.elapsed(), Duration::from_millis(2800));
    assert!(closed.load(Ordering::Acquire));
}
