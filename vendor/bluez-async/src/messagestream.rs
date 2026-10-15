use dbus::Message;
use dbus::channel::MatchingReceiver;
use dbus::nonblock::{MsgMatch, SyncConnection};
use futures::Stream;
use futures::channel::mpsc::UnboundedReceiver;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::task::JoinHandle;

/// Wrapper for a stream of D-Bus messages which automatically removes the `MsgMatch` from the D-Bus
/// connection when it is dropped.
pub struct MessageStream {
    msg_match: Option<MsgMatch>,
    events: UnboundedReceiver<Message>,
    connection: Arc<SyncConnection>,
    match_rule: String,
}

impl MessageStream {
    pub fn new(msg_match: MsgMatch, connection: Arc<SyncConnection>, match_rule: String) -> Self {
        let (msg_match, events) = msg_match.msg_stream();
        Self {
            msg_match: Some(msg_match),
            events,
            connection,
            match_rule,
        }
    }
}

impl Stream for MessageStream {
    type Item = Message;

    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        Pin::new(&mut self.events).poll_next(cx)
    }
}

// Keep the receiver and match alive until local removal: closing the receiver
// first makes dbus's callback self-remove, racing remove_match(token). The
// dispatcher can also temporarily extract the filter while delivering a signal;
// retry local removal briefly and remove the captured daemon rule exactly once.
fn cleanup_match(
    connection: Arc<SyncConnection>,
    msg_match: MsgMatch,
    events: UnboundedReceiver<Message>,
    match_rule: String,
) -> Option<JoinHandle<()>> {
    let token = msg_match.token();
    let detached = connection.stop_receive(token).is_some();
    let Ok(runtime) = tokio::runtime::Handle::try_current() else {
        // No executor can service asynchronous RemoveMatch. Local detachment is
        // best effort if dispatch currently owns the filter; dropping MsgMatch
        // makes any later callback return false. The daemon releases its rule
        // when this connection closes.
        log::debug!("D-Bus stream dropped outside a Tokio runtime; local detach={detached}");
        return None;
    };
    Some(runtime.spawn(async move {
        let _owned = (msg_match, events);
        if !detached {
            let deadline = tokio::time::Instant::now() + Duration::from_millis(100);
            while connection.stop_receive(token).is_none() {
                if tokio::time::Instant::now() >= deadline {
                    log::debug!("D-Bus local match unavailable during bounded stream cleanup");
                    break;
                }
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        }
        match tokio::time::timeout(
            Duration::from_secs(1),
            connection.remove_match_no_cb(&match_rule),
        )
        .await
        {
            Ok(Ok(())) => {}
            Ok(Err(error)) => log::debug!("D-Bus stream match removal failed: {error}"),
            Err(_) => log::debug!("D-Bus stream match removal timed out"),
        }
        // Also catch a filter reinserted during daemon cleanup. On executor
        // shutdown, ownership drops naturally; a weak match callback cannot
        // deliver into an abandoned stream.
        let _ = connection.stop_receive(token);
    }))
}

impl Drop for MessageStream {
    fn drop(&mut self) {
        if let Some(msg_match) = self.msg_match.take() {
            let events = std::mem::replace(&mut self.events, futures::channel::mpsc::unbounded().1);
            let _cleanup = cleanup_match(
                Arc::clone(&self.connection),
                msg_match,
                events,
                std::mem::take(&mut self.match_rule),
            );
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use dbus::message::MatchRule;
    use dbus::nonblock::Process;
    use std::sync::atomic::{AtomicBool, Ordering};

    fn rule(member: &str) -> MatchRule<'static> {
        MatchRule::new_signal("org.instantlink.CleanupTest", member).static_clone()
    }

    async fn bus() -> (Arc<SyncConnection>, JoinHandle<()>) {
        let (resource, connection) = dbus_tokio::connection::new_session_sync().unwrap();
        let resource = tokio::spawn(async move {
            let _ = resource.await;
        });
        (connection, resource)
    }

    async fn assert_daemon_rule_removed(connection: &SyncConnection, match_rule: &str) {
        let error = connection.remove_match_no_cb(match_rule).await.unwrap_err();
        assert_eq!(
            error.name(),
            Some("org.freedesktop.DBus.Error.MatchRuleNotFound")
        );
    }

    #[tokio::test]
    #[ignore = "Requires an isolated dbus-run-session; no BlueZ or Printer"]
    async fn dropped_stream_signal_before_cleanup_does_not_panic_or_leak_rule() {
        let (connection, resource) = bus().await;
        let mr = rule("ReceiverRace");
        let msg_match = connection.add_match(mr.clone()).await.unwrap();
        let token = msg_match.token();
        let (msg_match, events) = msg_match.msg_stream();
        let cleanup = cleanup_match(connection.clone(), msg_match, events, mr.match_str()).unwrap();
        // Deterministically deliver a local signal before the spawned cleanup
        // gets any executor time. Previously the closed receiver removed its
        // own token, making remove_match(token).unwrap() panic on its next poll.
        connection.process_one(
            Message::new_signal(
                "/org/instantlink/test",
                "org.instantlink.CleanupTest",
                "ReceiverRace",
            )
            .unwrap(),
        );
        cleanup.await.unwrap();
        assert!(connection.stop_receive(token).is_none());
        assert_daemon_rule_removed(&connection, &mr.match_str()).await;
        resource.abort();
    }

    #[tokio::test]
    #[ignore = "Requires an isolated dbus-run-session; no BlueZ or Printer"]
    async fn in_flight_dispatch_filter_is_removed_after_it_is_reinserted() {
        let (connection, resource) = bus().await;
        let mr = rule("DispatchRace");
        let entered = Arc::new(AtomicBool::new(false));
        let entered_callback = Arc::clone(&entered);
        let (release, receive_release) = std::sync::mpsc::channel::<()>();
        let msg_match = connection
            .add_match(mr.clone())
            .await
            .unwrap()
            .msg_cb(move |_| {
                entered_callback.store(true, Ordering::Release);
                receive_release
                    .recv_timeout(Duration::from_secs(2))
                    .unwrap();
                true
            });
        let token = msg_match.token();
        let dispatch_connection = Arc::clone(&connection);
        let dispatch = std::thread::spawn(move || {
            dispatch_connection.process_one(
                Message::new_signal(
                    "/org/instantlink/test",
                    "org.instantlink.CleanupTest",
                    "DispatchRace",
                )
                .unwrap(),
            );
        });
        tokio::time::timeout(Duration::from_secs(2), async {
            while !entered.load(Ordering::Acquire) {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        let cleanup = cleanup_match(
            connection.clone(),
            msg_match,
            futures::channel::mpsc::unbounded().1,
            mr.match_str(),
        )
        .unwrap();
        // Give cleanup a poll while process_one temporarily owns the filter.
        tokio::time::sleep(Duration::from_millis(3)).await;
        release.send(()).unwrap();
        dispatch.join().unwrap();
        cleanup.await.unwrap();
        assert!(connection.stop_receive(token).is_none());
        assert_daemon_rule_removed(&connection, &mr.match_str()).await;
        resource.abort();
    }

    #[tokio::test]
    #[ignore = "Requires an isolated dbus-run-session; no BlueZ or Printer"]
    async fn daemon_removal_error_is_non_panicking_and_duplicate_rule_is_preserved() {
        let (connection, resource) = bus().await;
        let mr = rule("DuplicateRule");
        let first = connection.add_match(mr.clone()).await.unwrap();
        let second = connection.add_match(mr.clone()).await.unwrap();
        let (first, events) = first.msg_stream();
        cleanup_match(connection.clone(), first, events, mr.match_str())
            .unwrap()
            .await
            .unwrap();
        // Removing one owned stream must leave the duplicate subscription intact.
        connection
            .remove_match_no_cb(&mr.match_str())
            .await
            .unwrap();
        let (second, events) = second.msg_stream();
        // The daemon rule is already gone: the error must not panic this task.
        cleanup_match(connection.clone(), second, events, mr.match_str())
            .unwrap()
            .await
            .unwrap();
        resource.abort();
    }

    #[test]
    #[ignore = "Requires an isolated dbus-run-session; no BlueZ or Printer"]
    fn drop_outside_entered_runtime_detaches_local_match_without_panicking() {
        let runtime = tokio::runtime::Runtime::new().unwrap();
        let (connection, resource, stream, token, match_rule) = runtime.block_on(async {
            let (connection, resource) = bus().await;
            let mr = rule("OutsideRuntime");
            let msg_match = connection.add_match(mr.clone()).await.unwrap();
            let token = msg_match.token();
            let stream = MessageStream::new(msg_match, connection.clone(), mr.match_str());
            (connection, resource, stream, token, mr.match_str())
        });
        drop(stream);
        assert!(connection.stop_receive(token).is_none());
        // Without an entered executor daemon cleanup is deferred to bus closure;
        // explicitly release the test rule before terminating our test bus.
        runtime
            .block_on(connection.remove_match_no_cb(&match_rule))
            .unwrap();
        resource.abort();
    }
}
