final class AppRuntimeServicesTests {
    func testCompareVersionsHandlesPrefixesSuffixesAndDifferentLengths() throws {
        try expectEqual(AppUpdateService.compareVersions("v0.1.5", "0.1.5"), 0)
        try expectEqual(AppUpdateService.compareVersions("instantlink 0.1.5", "0.1.6"), -1)
        try expectEqual(AppUpdateService.compareVersions("0.1.5-beta.1", "0.1.5"), 0)
        try expectEqual(AppUpdateService.compareVersions("0.1", "0.1.0"), 0)
        try expectEqual(AppUpdateService.compareVersions("0.2.0", "0.1.9"), 1)
        try expectNil(AppUpdateService.compareVersions("...", "0.1.5"))
        try expectNil(AppUpdateService.compareVersions("?", "0.1.5"))
    }
}
