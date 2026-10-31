import Foundation

// Compatibility executable. Every command goes to the isolated engine.
// No AppKit, Accessibility, HID, desktop capture or foreground fallback.
let configURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".blacklabel/isolated-browser/runtime.json")
do {
    let data = try Data(contentsOf: configURL)
    guard let config = try JSONSerialization.jsonObject(with: data) as? [String: String],
          let node = config["node"], let worker = config["worker"],
          let playwright = config["playwright"] else { throw NSError(domain: "runtime", code: 1) }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: node)
    process.arguments = [worker]
    var environment = ProcessInfo.processInfo.environment
    environment["BL_BROWSER_PLAYWRIGHT"] = playwright
    environment["BL_BROWSER_SESSION"] = environment["CODEX_THREAD_ID"] ?? "legacy-\(getppid())"
    process.environment = environment
    process.standardInput = FileHandle.standardInput
    process.standardOutput = FileHandle.standardOutput
    process.standardError = FileHandle.nullDevice
    try process.run()
    process.waitUntilExit()
} catch {
    print("{\"ok\":false,\"error\":\"ISOLATED_BROWSER_NOT_INSTALLED: run install.py; desktop fallback is disabled\"}")
}
