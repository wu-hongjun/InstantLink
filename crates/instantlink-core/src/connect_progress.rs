#[repr(i32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectStage {
    ScanStarted = 0,
    ScanFinished = 1,
    DeviceMatched = 2,
    BleConnecting = 3,
    ServiceDiscovery = 4,
    CharacteristicLookup = 5,
    NotificationSubscribe = 6,
    ModelDetecting = 7,
    StatusFetching = 8,
    Connected = 9,
    Failed = 10,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConnectProgressEvent {
    pub stage: ConnectStage,
    pub detail: Option<String>,
}

pub type ConnectProgressCallback = dyn Fn(ConnectProgressEvent) + Send + Sync;

pub fn emit_connect_progress(
    progress: Option<&ConnectProgressCallback>,
    stage: ConnectStage,
    detail: Option<impl Into<String>>,
) {
    if let Some(progress) = progress {
        progress(ConnectProgressEvent {
            stage,
            detail: detail.map(Into::into),
        });
    }
}

#[cfg(test)]
mod tests {
    use super::ConnectStage;

    #[test]
    fn connect_stage_codes_are_stable() {
        assert_eq!(ConnectStage::ScanStarted as i32, 0);
        assert_eq!(ConnectStage::ScanFinished as i32, 1);
        assert_eq!(ConnectStage::DeviceMatched as i32, 2);
        assert_eq!(ConnectStage::BleConnecting as i32, 3);
        assert_eq!(ConnectStage::ServiceDiscovery as i32, 4);
        assert_eq!(ConnectStage::CharacteristicLookup as i32, 5);
        assert_eq!(ConnectStage::NotificationSubscribe as i32, 6);
        assert_eq!(ConnectStage::ModelDetecting as i32, 7);
        assert_eq!(ConnectStage::StatusFetching as i32, 8);
        assert_eq!(ConnectStage::Connected as i32, 9);
        assert_eq!(ConnectStage::Failed as i32, 10);
    }
}
