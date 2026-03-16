import Foundation

@MainActor
final class QueueEditCoordinatorTests {
    func setUp() {
        resetStoredNewPhotoDefaults()
    }

    func tearDown() {
        resetStoredNewPhotoDefaults()
    }

    func testAddItemsEnforcesQueueLimitAndReportsDroppedItems() throws {
        let coordinator = QueueEditCoordinator(newPhotoDefaults: NewPhotoDefaults())
        let items = (0..<25).map { makeQueueImportItem(name: "image-\($0).jpg") }

        let result = coordinator.addItems(items, currentEditing: nil)

        try expectEqual(coordinator.queue.count, QueueEditCoordinator.maxQueueItems)
        try expectEqual(result.addedCount, QueueEditCoordinator.maxQueueItems)
        try expectEqual(result.droppedCount, 5)
        try expectEqual(result.selection.selectedQueueIndex, QueueEditCoordinator.maxQueueItems - 1)
    }

    func testAddRemoveAndMovePreserveExpectedSelectionBehavior() throws {
        let initialQueue = (0..<3).map { index in
            QueueItem(
                url: makeTestURL("item-\(index).jpg"),
                image: makeTestImage(),
                imageDate: nil,
                imageLocation: nil,
                editState: QueueItemEditState(fitMode: "crop")
            )
        }
        let coordinator = QueueEditCoordinator(
            queue: initialQueue,
            selectedQueueIndex: 1,
            newPhotoDefaults: NewPhotoDefaults()
        )

        let added = coordinator.addItems([makeQueueImportItem(name: "new.jpg")], currentEditing: nil)
        try expectEqual(added.selection.selectedQueueIndex, 1)

        let removed = coordinator.removeQueueItem(at: 0, currentEditing: nil)
        try expectEqual(removed?.selectedQueueIndex, 0)

        let moved = coordinator.moveQueueItem(from: 0, to: 2, currentEditing: nil)
        try expectEqual(moved?.selectedQueueIndex, 2)
    }

    func testSaveTimestampOverlayAsDefaultsKeepsOnlyOneTimestampOverlay() throws {
        let coordinator = QueueEditCoordinator(newPhotoDefaults: NewPhotoDefaults())
        let timestamp = makeTimestampOverlay("contax")

        _ = coordinator.saveTimestampOverlayAsNewPhotoDefaults(timestamp)

        try expectEqual(coordinator.newPhotoDefaults.overlays.count, 1)
        try expectEqual(coordinator.newPhotoDefaults.overlays.first?.content, timestamp.content)
    }

    func testSaveCurrentLayoutAsDefaultsPersistsOnlyLayoutFields() throws {
        let coordinator = QueueEditCoordinator(newPhotoDefaults: NewPhotoDefaults(overlays: [makeTimestampOverlay("classic")]))
        let snapshot = QueueEditingSnapshot(editState: QueueItemEditState(
            fitMode: "contain",
            cropOffsetNormalized: CGSize(width: 0.2, height: -0.1),
            cropZoom: 1.8,
            exposureEV: 2.0,
            rotationAngle: 90,
            isHorizontallyFlipped: true,
            overlays: [makeTextOverlay("not-defaulted")],
            filmOrientation: "vertical"
        ))

        _ = coordinator.saveCurrentLayoutAsNewPhotoDefaults(from: snapshot)

        try expectEqual(coordinator.newPhotoDefaults.fitMode, "contain")
        try expectEqual(coordinator.newPhotoDefaults.rotationAngle, 90)
        try expectTrue(coordinator.newPhotoDefaults.isHorizontallyFlipped)
        try expectEqual(coordinator.newPhotoDefaults.filmOrientation, "vertical")
        try expectEqual(coordinator.newPhotoDefaults.overlays.count, 1)
        try expectEqual(coordinator.newPhotoDefaults.overlays.first?.kind, .timestamp)
    }

    func testCameraDraftRestoreReturnsSavedEditStateWhenQueueIsEmpty() throws {
        let coordinator = QueueEditCoordinator(newPhotoDefaults: NewPhotoDefaults())
        let snapshot = QueueEditingSnapshot(editState: QueueItemEditState(
            fitMode: "stretch",
            cropOffsetNormalized: CGSize(width: 0.1, height: 0.1),
            cropZoom: 1.3,
            exposureEV: 1.0,
            rotationAngle: 180,
            isHorizontallyFlipped: true,
            overlays: [makeTimestampOverlay()],
            filmOrientation: "vertical"
        ))

        _ = coordinator.beginCameraDraft(from: snapshot)
        let restored = coordinator.restoreFileModeAfterCamera()

        try expectEqual(restored, snapshot)
    }
}
