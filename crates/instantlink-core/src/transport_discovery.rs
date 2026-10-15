//! Linux bulk discovery prefilter. Candidate and liveness checks remain in btleplug.
//!
//! `Adapter::peripherals()` is one ObjectManager query, while every `properties()`
//! reads Device1 again. A fresh bulk snapshot skips only definitely unrelated
//! records; missing or uncertain data retains the original per-device checks.

use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use dbus::arg::prop_cast;
use dbus::nonblock::SyncConnection;
use dbus::nonblock::stdintf::org_freedesktop_dbus::ObjectManager;
use futures::future::BoxFuture;
use tokio::sync::{Mutex, Semaphore};
use tokio::time::{Instant, timeout_at};
use uuid::Uuid;

use super::{AbortOnDrop, BluezObjects, SERVICE_UUID};

const SNAPSHOT_TIMEOUT: Duration = Duration::from_millis(500);
static BUS: Mutex<Option<SnapshotBus>> = Mutex::const_new(None);
static BUS_OPEN: Semaphore = Semaphore::const_new(1);

struct SnapshotBus {
    connection: Arc<SyncConnection>,
    resource: AbortOnDrop,
}

impl SnapshotBus {
    fn running(&self) -> bool {
        self.resource
            .0
            .as_ref()
            .is_some_and(|task| !task.is_finished())
    }
}

/// Reuse one connection, but never retain snapshots or an abandoned query.
/// The mutex and bus open share the same bounded budget as the query. Moving
/// the bus out of the cache during a query makes cancellation abort its owned
/// resource; the next caller opens a clean connection instead of reusing it.
pub(super) async fn snapshot() -> Option<BluezObjects> {
    let deadline = Instant::now() + SNAPSHOT_TIMEOUT;
    let result = cached_query(&BUS, deadline, SnapshotBus::running, open_bus, |bus| {
        Box::pin(async move {
            let proxy = dbus::nonblock::Proxy::new(
                "org.bluez",
                "/",
                SNAPSHOT_TIMEOUT,
                Arc::clone(&bus.connection),
            );
            proxy.get_managed_objects().await.ok()
        })
    })
    .await;
    if result.is_none() {
        log::debug!("discovery snapshot unavailable; retaining per-device checks");
    }
    result
}

async fn open_bus() -> Option<SnapshotBus> {
    let (resource, connection) =
        guarded_open(&BUS_OPEN, || dbus_tokio::connection::new_system_sync().ok()).await?;
    let resource = AbortOnDrop(Some(tokio::spawn(async move {
        let error = resource.await;
        log::debug!("discovery snapshot D-Bus resource ended: {error}");
    })));
    Some(SnapshotBus {
        connection,
        resource,
    })
}

async fn guarded_open<R: Send + 'static>(
    semaphore: &'static Semaphore,
    open: impl FnOnce() -> Option<R> + Send + 'static,
) -> Option<R> {
    // The worker owns the permit and its late result. Cancelling its waiter
    // neither permits more blocking opens nor spawns an orphan resource task.
    let permit = semaphore.try_acquire().ok()?;
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        open()
    })
    .await
    .ok()?
}

async fn cached_query<R, V, O, F, U, Q>(
    cache: &Mutex<Option<R>>,
    deadline: Instant,
    usable: U,
    open: O,
    query: Q,
) -> Option<V>
where
    O: FnOnce() -> F,
    F: Future<Output = Option<R>>,
    U: Fn(&R) -> bool,
    Q: for<'a> FnOnce(&'a R) -> BoxFuture<'a, Option<V>>,
{
    let mut cached = timeout_at(deadline, cache.lock()).await.ok()?;
    let resource = match cached.take().filter(&usable) {
        Some(resource) => resource,
        None => timeout_at(deadline, open()).await.ok()??,
    };
    let result = timeout_at(deadline, query(&resource)).await.ok()??;
    if usable(&resource) {
        *cached = Some(resource);
    }
    Some(result)
}

/// Look up the exact path from a handle already scoped by the chosen Adapter.
/// No adapter-name inference, address deduplication, or candidate caching occurs.
pub(super) fn definitely_non_instax(objects: &BluezObjects, device_path: &str) -> bool {
    let Ok(path) = dbus::Path::new(device_path) else {
        return false;
    };
    let Some(properties) = objects
        .get(&path)
        .and_then(|interfaces| interfaces.get("org.bluez.Device1"))
    else {
        return false;
    };

    // Connected is required by btleplug's DeviceInfo parser. A missing or
    // malformed record must take its existing fresh per-device query path.
    if prop_cast::<bool>(properties, "Connected").is_none()
        || (properties.contains_key("RSSI") && prop_cast::<i16>(properties, "RSSI").is_none())
    {
        return false;
    }
    let name = prop_cast::<String>(properties, "Name");
    if properties.contains_key("Name") && name.is_none() {
        return false;
    }
    if name.is_some_and(|name| name.starts_with("INSTAX")) {
        return false;
    }

    let services = prop_cast::<Vec<String>>(properties, "UUIDs");
    if properties.contains_key("UUIDs") && services.is_none() {
        return false;
    }
    for service in services.into_iter().flatten() {
        match Uuid::parse_str(service) {
            Ok(uuid) if uuid == SERVICE_UUID => return false,
            Ok(_) => {}
            // Be conservative about malformed snapshots rather than guessing.
            Err(_) => return false,
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    use dbus::arg::{PropMap, RefArg, Variant};

    use super::*;

    const DEVICE: &str = "/org/bluez/hci0/dev_FA_AB_BC_C7_95_64";

    struct FakeResource {
        id: u8,
        resource: AbortOnDrop,
    }

    struct Live(Arc<AtomicBool>);
    impl Drop for Live {
        fn drop(&mut self) {
            self.0.store(false, Ordering::Release);
        }
    }

    impl FakeResource {
        fn new(id: u8) -> (Self, Arc<AtomicBool>) {
            let active = Arc::new(AtomicBool::new(true));
            let live = Live(Arc::clone(&active));
            let task = tokio::spawn(async move {
                let _live = live;
                std::future::pending::<()>().await;
            });
            (
                Self {
                    id,
                    resource: AbortOnDrop(Some(task)),
                },
                active,
            )
        }

        fn usable(&self) -> bool {
            self.resource
                .0
                .as_ref()
                .is_some_and(|task| !task.is_finished())
        }
    }

    fn query_id(resource: &FakeResource) -> BoxFuture<'_, Option<u8>> {
        Box::pin(async move { Some(resource.id) })
    }

    #[tokio::test]
    async fn successful_queries_reuse_resource_but_fetch_fresh_results() {
        let cache = Mutex::new(None);
        let opens = AtomicUsize::new(0);
        let queries = Arc::new(AtomicUsize::new(0));
        for expected in 1..=3 {
            let query_count = Arc::clone(&queries);
            let result = cached_query(
                &cache,
                Instant::now() + SNAPSHOT_TIMEOUT,
                FakeResource::usable,
                || async {
                    opens.fetch_add(1, Ordering::Relaxed);
                    Some(FakeResource::new(7).0)
                },
                move |_| {
                    Box::pin(async move { Some(query_count.fetch_add(1, Ordering::Relaxed) + 1) })
                },
            )
            .await;
            assert_eq!(result, Some(expected));
        }
        assert_eq!(opens.load(Ordering::Relaxed), 1);
        assert_eq!(queries.load(Ordering::Relaxed), 3);
    }

    #[tokio::test]
    async fn cancelling_inflight_query_drops_owned_resource_and_clears_cache() {
        let (resource, active) = FakeResource::new(1);
        let cache = Mutex::new(Some(resource));
        {
            let future = cached_query(
                &cache,
                Instant::now() + SNAPSHOT_TIMEOUT,
                FakeResource::usable,
                || async { panic!("cached resource must be reused") },
                |_| Box::pin(std::future::pending::<Option<u8>>()),
            );
            tokio::pin!(future);
            tokio::select! {
                result = &mut future => panic!("query unexpectedly ended: {result:?}"),
                _ = tokio::task::yield_now() => {}
            }
        }
        assert!(cache.lock().await.is_none());
        tokio::task::yield_now().await;
        assert!(!active.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn mutex_wait_timeout_does_not_clear_another_callers_resource() {
        let (resource, active) = FakeResource::new(1);
        let cache = Mutex::new(Some(resource));
        let owner = cache.lock().await;
        assert_eq!(
            cached_query(
                &cache,
                Instant::now() + SNAPSHOT_TIMEOUT,
                FakeResource::usable,
                || async { panic!("waiter must not open a bus") },
                query_id
            )
            .await,
            None
        );
        assert_eq!(owner.as_ref().unwrap().id, 1);
        assert!(active.load(Ordering::Acquire));
    }

    #[tokio::test(start_paused = true)]
    async fn query_error_and_timeout_clear_resource_and_allow_retry() {
        for pending in [false, true] {
            let (resource, active) = FakeResource::new(1);
            let cache = Mutex::new(Some(resource));
            assert_eq!(
                cached_query(
                    &cache,
                    Instant::now() + SNAPSHOT_TIMEOUT,
                    FakeResource::usable,
                    || async { panic!("cached resource must be reused") },
                    |_| Box::pin(async move {
                        if pending {
                            std::future::pending::<()>().await;
                        }
                        None::<u8>
                    })
                )
                .await,
                None
            );
            assert!(cache.lock().await.is_none());
            tokio::task::yield_now().await;
            assert!(!active.load(Ordering::Acquire));
            assert_eq!(
                cached_query(
                    &cache,
                    Instant::now() + SNAPSHOT_TIMEOUT,
                    FakeResource::usable,
                    || async { Some(FakeResource::new(2).0) },
                    query_id
                )
                .await,
                Some(2)
            );
        }
    }

    #[tokio::test]
    async fn finished_resource_reopens_instead_of_reusing_dead_bus() {
        let (resource, active) = FakeResource::new(1);
        resource.resource.0.as_ref().unwrap().abort();
        tokio::task::yield_now().await;
        assert!(!active.load(Ordering::Acquire));
        let cache = Mutex::new(Some(resource));
        assert_eq!(
            cached_query(
                &cache,
                Instant::now() + SNAPSHOT_TIMEOUT,
                FakeResource::usable,
                || async { Some(FakeResource::new(2).0) },
                query_id
            )
            .await,
            Some(2)
        );
    }

    #[tokio::test]
    async fn cancelled_blocking_open_retains_semaphore_until_worker_finishes() {
        static OPEN: Semaphore = Semaphore::const_new(1);
        let started = Arc::new(tokio::sync::Notify::new());
        let worker_started = Arc::clone(&started);
        let late_result_alive = Arc::new(AtomicBool::new(true));
        let worker_result_alive = Arc::clone(&late_result_alive);
        let (release, wait) = std::sync::mpsc::channel::<()>();
        let waiter = tokio::spawn(guarded_open(&OPEN, move || {
            worker_started.notify_one();
            wait.recv().unwrap();
            Some(Live(worker_result_alive))
        }));
        started.notified().await;
        waiter.abort();
        let _ = waiter.await;
        assert_eq!(OPEN.available_permits(), 0);
        assert_eq!(
            guarded_open(&OPEN, || panic!("a second open must not run")).await,
            None::<u8>
        );
        release.send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(1), async {
            while OPEN.available_permits() == 0 || late_result_alive.load(Ordering::Acquire) {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(guarded_open(&OPEN, || Some(2_u8)).await, Some(2));
    }

    fn record(name: Option<&str>, services: Option<Vec<String>>, connected: bool) -> BluezObjects {
        let mut properties = PropMap::new();
        properties.insert("Connected".into(), Variant(Box::new(connected)));
        if let Some(name) = name {
            properties.insert("Name".into(), Variant(Box::new(name.to_owned())));
        }
        if let Some(services) = services {
            properties.insert("UUIDs".into(), Variant(Box::new(services)));
        }
        HashMap::from([(
            dbus::Path::new(DEVICE).unwrap(),
            HashMap::from([("org.bluez.Device1".into(), properties)]),
        )])
    }

    fn set(objects: &mut BluezObjects, key: &str, value: Box<dyn RefArg>) {
        objects
            .get_mut(&dbus::Path::new(DEVICE).unwrap())
            .unwrap()
            .get_mut("org.bluez.Device1")
            .unwrap()
            .insert(key.to_owned(), Variant(value));
    }

    #[test]
    fn names_without_advertised_service_remain_candidates() {
        for name in [
            "INSTAX-52006924",
            "INSTAX-52006924 (Android)",
            "INSTAX (ANDROID)  ",
        ] {
            assert!(!definitely_non_instax(
                &record(Some(name), None, false),
                DEVICE
            ));
        }
    }

    #[test]
    fn service_candidate_keeps_unnamed_and_unusual_names() {
        for name in [None, Some("other name"), Some("instax-52006924")] {
            assert!(!definitely_non_instax(
                &record(
                    name,
                    Some(vec![SERVICE_UUID.to_string().to_uppercase()]),
                    false
                ),
                DEVICE,
            ));
        }
    }

    #[test]
    fn unrelated_records_skip_independent_of_liveness() {
        for connected in [false, true] {
            for name in [None, Some("Headphones"), Some("instax-52006924")] {
                let mut objects = record(name, None, connected);
                assert!(definitely_non_instax(&objects, DEVICE));
                set(&mut objects, "RSSI", Box::new(-70_i16));
                assert!(definitely_non_instax(&objects, DEVICE));
            }
        }
    }

    #[test]
    fn instax_liveness_is_left_to_existing_fresh_queries() {
        for connected in [false, true] {
            let mut objects = record(Some("INSTAX-52006924"), None, connected);
            assert!(!definitely_non_instax(&objects, DEVICE));
            set(&mut objects, "RSSI", Box::new(-70_i16));
            assert!(!definitely_non_instax(&objects, DEVICE));
        }
    }

    #[test]
    fn missing_removed_and_other_adapter_records_use_existing_queries() {
        let objects = record(Some("Headphones"), None, false);
        assert!(!definitely_non_instax(
            &objects,
            "/org/bluez/hci1/dev_FA_AB_BC_C7_95_64"
        ));
        assert!(!definitely_non_instax(&BluezObjects::new(), DEVICE));
        assert!(!definitely_non_instax(&objects, "invalid path"));
        let mut wrong_interface = objects;
        wrong_interface
            .get_mut(&dbus::Path::new(DEVICE).unwrap())
            .unwrap()
            .clear();
        assert!(!definitely_non_instax(&wrong_interface, DEVICE));
    }

    #[test]
    fn malformed_fields_never_exclude_a_handle() {
        let mutations: Vec<(&str, Box<dyn RefArg>)> = vec![
            ("Name", Box::new(1_u32)),
            ("UUIDs", Box::new("bad type".to_owned())),
            ("UUIDs", Box::new(vec!["malformed uuid".to_owned()])),
            ("Connected", Box::new("false".to_owned())),
            ("RSSI", Box::new(-70_i32)),
        ];
        for (key, value) in mutations {
            let mut objects = record(Some("Headphones"), None, false);
            set(&mut objects, key, value);
            assert!(!definitely_non_instax(&objects, DEVICE), "{key}");
        }
        let mut missing_connected = record(Some("Headphones"), None, false);
        missing_connected
            .get_mut(&dbus::Path::new(DEVICE).unwrap())
            .unwrap()
            .get_mut("org.bluez.Device1")
            .unwrap()
            .remove("Connected");
        assert!(!definitely_non_instax(&missing_connected, DEVICE));
    }

    #[test]
    fn alias_cannot_replace_real_advertised_name() {
        let mut objects = record(Some("Headphones"), None, false);
        set(
            &mut objects,
            "Alias",
            Box::new("INSTAX-52006924".to_owned()),
        );
        assert!(definitely_non_instax(&objects, DEVICE));
    }

    #[test]
    fn dbus_wire_roundtrip_preserves_dynamic_uuid_arrays_and_property_types() {
        for (services, expected_skip) in [
            (
                vec!["0000180f-0000-1000-8000-00805f9b34fb".to_owned()],
                true,
            ),
            (vec![SERVICE_UUID.to_string()], false),
        ] {
            let mut objects = record(None, Some(services), false);
            set(&mut objects, "RSSI", Box::new(-65_i16));
            let message = dbus::Message::new_signal("/", "test.Discovery", "Snapshot")
                .unwrap()
                .append1(objects);
            let decoded: BluezObjects = message.read1().unwrap();
            assert_eq!(definitely_non_instax(&decoded, DEVICE), expected_skip);
        }
    }
}
