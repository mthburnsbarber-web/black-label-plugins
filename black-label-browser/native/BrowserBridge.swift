import AppKit
import ApplicationServices
import Foundation

// Own native Accessibility client. No extension, CDP, WebDriver or Apple Events.
let bundles = ["safari": "com.apple.Safari", "chrome": "com.google.Chrome"]
var elements: [String: AXUIElement] = [:]
var snapshotBrowser = ""
var snapshotPID: pid_t = 0
var snapshotTime = Date.distantPast
var snapshotWindow: AXUIElement? = nil
var generation = ""

struct BridgeError: Error { let message: String }
func fail(_ message: String) throws -> Never { throw BridgeError(message: message) }
func attr(_ el: AXUIElement, _ key: String) -> CFTypeRef? {
    var result: CFTypeRef?
    return AXUIElementCopyAttributeValue(el, key as CFString, &result) == .success ? result : nil
}
func text(_ el: AXUIElement, _ key: String) -> String {
    guard let value = attr(el, key) else { return "" }
    if let string = value as? String { return String(string.prefix(3000)) }
    if let number = value as? NSNumber { return number.stringValue }
    if CFGetTypeID(value) == CFURLGetTypeID() { return String(describing: value) }
    return ""
}
func required(_ input: [String: Any], _ key: String) throws -> String {
    guard let value = input[key] as? String, !value.isEmpty else { try fail("Missing " + key) }
    return value
}
func app(_ browser: String) throws -> NSRunningApplication {
    guard let bundle = bundles[browser] else { try fail("Browser must be safari or chrome") }
    guard let value = NSRunningApplication.runningApplications(withBundleIdentifier: bundle).first else {
        try fail("Browser is not running. Use browser_open first.")
    }
    return value
}
func root(_ browser: String) throws -> AXUIElement {
    guard AXIsProcessTrusted() else { try fail("ACCESSIBILITY_REQUIRED: grant Accessibility to Black Label Browser Bridge, then retry this same task.") }
    let value = AXUIElementCreateApplication(try app(browser).processIdentifier)
    AXUIElementSetMessagingTimeout(value, 2)
    return value
}
func frame(_ el: AXUIElement) -> CGRect? {
    guard let p = attr(el, kAXPositionAttribute), let s = attr(el, kAXSizeAttribute),
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero, size = CGSize.zero
    guard AXValueGetValue(p as! AXValue, .cgPoint, &point), AXValueGetValue(s as! AXValue, .cgSize, &size) else { return nil }
    return CGRect(origin: point, size: size)
}
func snapshot(_ browser: String) throws -> [String: Any] {
    let application = try root(browser)
    elements.removeAll()
    snapshotBrowser = browser; snapshotPID = try app(browser).processIdentifier
    generation = String(UUID().uuidString.prefix(8)); snapshotTime = Date()
    var rows: [[String: Any]] = []
    var seen = Set<CFHashCode>()
    var queue: [(AXUIElement, Int)] = []
    func visit(_ el: AXUIElement, _ depth: Int) {
        if rows.count >= 700 || depth > 30 { return }
        let hash = CFHash(el)
        if seen.contains(hash) { return }; seen.insert(hash)
        let role = text(el, kAXRoleAttribute), subrole = text(el, kAXSubroleAttribute)
        let id = generation + ":" + String(rows.count)
        elements[id] = el
        let secure = subrole == kAXSecureTextFieldSubrole || role == "AXSecureTextField"
        var row: [String: Any] = ["id": id, "role": role, "depth": depth,
                                  "title": text(el, kAXTitleAttribute), "description": text(el, kAXDescriptionAttribute)]
        if let f = frame(el) { row["frame"] = [f.origin.x, f.origin.y, f.width, f.height] }
        row["value"] = secure ? "[secure field]" : text(el, kAXValueAttribute)
        row["url"] = text(el, kAXURLAttribute)
        if let enabled = attr(el, kAXEnabledAttribute) as? Bool { row["enabled"] = enabled }
        var actions: CFArray?
        if AXUIElementCopyActionNames(el, &actions) == .success { row["actions"] = actions as? [String] ?? [] }
        rows.append(row)
        if let children = attr(el, kAXChildrenAttribute) as? [AXUIElement] {
            for child in children { queue.append((child, depth + 1)) }
        }
    }
    // Some Chromium builds need the public AXManualAccessibility attribute.
    if browser == "chrome" { AXUIElementSetAttributeValue(application, "AXManualAccessibility" as CFString, true as CFBoolean) }
    let windows = attr(application, kAXWindowsAttribute) as? [AXUIElement] ?? []
    var focused: AXUIElement? = nil
    if let value = attr(application,kAXFocusedWindowAttribute), CFGetTypeID(value) == AXUIElementGetTypeID() { focused = (value as! AXUIElement) }
    var windowRows: [[String:Any]] = []
    for (index,window) in windows.enumerated() {
        let id = generation+":window:"+String(index);elements[id]=window
        windowRows.append(["id":id,"title":text(window,kAXTitleAttribute)])
    }
    // Breadth-first traversal of the selected window keeps native dialog buttons
    // visible before potentially thousands of file-list rows or web descendants.
    snapshotWindow = focused ?? windows.first
    if let window = snapshotWindow { queue.append((window,0)) }
    var cursor=0
    while cursor < queue.count && rows.count < 700 {
        let (el,depth)=queue[cursor];cursor += 1;visit(el,depth)
    }
    return ["browser": browser, "generation": generation, "elements": rows, "truncated": rows.count >= 700,
            "windows":windowRows,"accessibility": true, "captured_at": ISO8601DateFormatter().string(from: Date())]
}
func element(_ input: [String: Any], _ browser: String) throws -> AXUIElement {
    let id = try required(input, "element")
    guard snapshotBrowser == browser, snapshotPID == (try app(browser)).processIdentifier,
          Date().timeIntervalSince(snapshotTime) < 90, let el = elements[id] else {
        try fail("STALE_ELEMENT: take a fresh snapshot and use its element IDs.")
    }
    return el
}
func focus(_ browser: String) throws {
    _ = try root(browser)
    let running = try app(browser)
    guard running.activate() else { try fail("Could not activate requested browser") }
    if snapshotBrowser == browser, let window = snapshotWindow {
        guard AXUIElementPerformAction(window,kAXRaiseAction as CFString) == .success else { try fail("Observed window is no longer available; take a new snapshot") }
    }
    let deadline = Date().addingTimeInterval(2)
    while NSWorkspace.shared.frontmostApplication?.processIdentifier != running.processIdentifier && Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.03))
    }
    guard NSWorkspace.shared.frontmostApplication?.processIdentifier == running.processIdentifier else {
        try fail("FOCUS_CHANGED: requested browser is not frontmost")
    }
}
func key(_ key: CGKeyCode, _ flags: CGEventFlags = []) {
    let down = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: true)
    let up = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: false)
    down?.flags = flags; up?.flags = []
    down?.post(tap: .cghidEventTap); up?.post(tap: .cghidEventTap)
}
func typeUnicode(_ value: String) {
    let chars = Array(value.utf16)
    for offset in stride(from: 0, to: chars.count, by: 20) {
        let piece = Array(chars[offset..<min(offset + 20, chars.count)])
        let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true)
        down?.flags = []
        piece.withUnsafeBufferPointer { p in down?.keyboardSetUnicodeString(stringLength: piece.count, unicodeString: p.baseAddress) }
        down?.post(tap: .cghidEventTap)
        let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false)
        up?.flags = []
        up?.post(tap: .cghidEventTap)
        RunLoop.current.run(until:Date().addingTimeInterval(0.025))
    }
}
func invalidate() { elements.removeAll(); snapshotTime = .distantPast; snapshotWindow = nil }
func perform(_ input: [String: Any]) throws -> [String: Any] {
    let command = try required(input, "command")
    if command == "status" {
        return ["accessibility": AXIsProcessTrusted(), "screen_recording": CGPreflightScreenCaptureAccess(),
                "helper": Bundle.main.bundlePath, "extension_required": false, "apple_events_required": false,
                "browsers": bundles.map { name, bundle in ["name": name, "running": !NSRunningApplication.runningApplications(withBundleIdentifier: bundle).isEmpty] as [String: Any] }]
    }
    let browser = try required(input, "browser")
    guard let bundle = bundles[browser] else { try fail("Browser must be safari or chrome") }
    if command == "open" {
        let raw = try required(input, "url")
        guard let url = URL(string: raw), ["https", "http"].contains(url.scheme?.lowercased() ?? ""), url.user == nil, url.password == nil else {
            try fail("Expected an http(s) URL without embedded credentials")
        }
        guard let appURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) else { try fail("Browser is not installed") }
        let conf = NSWorkspace.OpenConfiguration(); conf.activates = true
        var completed = false, openError: Error?
        NSWorkspace.shared.open([url], withApplicationAt: appURL, configuration: conf) { _, error in openError = error; completed = true }
        let until = Date().addingTimeInterval(10)
        while !completed && Date() < until { RunLoop.current.run(until: Date().addingTimeInterval(0.03)) }
        guard completed, openError == nil else { try fail("Browser open did not complete") }
        invalidate()
        return ["opened": true, "browser": browser, "next": "browser_snapshot; open alone does not verify page load or sign-in"]
    }
    if command == "snapshot" { return try snapshot(browser) }
    _ = try root(browser)
    if command == "focus_window" {
        let el = try element(input,browser)
        guard text(el,kAXRoleAttribute)=="AXWindow" else { try fail("Expected an observed window ID") }
        try focus(browser)
        guard AXUIElementPerformAction(el,kAXRaiseAction as CFString) == .success else { try fail("Could not raise selected window") }
    } else if command == "screenshot" {
        guard CGPreflightScreenCaptureAccess() else { try fail("SCREEN_RECORDING_REQUIRED: grant Screen Recording to Black Label Browser Bridge") }
        let destination = try required(input,"path")
        try focus(browser)
        let pid = try app(browser).processIdentifier
        let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
        guard let window = list.first(where: { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) && ($0[kCGWindowLayer as String] as? Int) == 0 }),
              let number = window[kCGWindowNumber as String] as? Int else { try fail("No visible browser window") }
        let proc = Process(); proc.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture")
        proc.arguments = ["-x","-o","-l",String(number),destination]
        proc.standardOutput = FileHandle.nullDevice; proc.standardError = FileHandle.nullDevice
        try proc.run(); proc.waitUntilExit()
        guard proc.terminationStatus == 0, FileManager.default.fileExists(atPath:destination) else { try fail("Screenshot capture failed") }
        return ["path":destination,"window_id":number]
    } else if command == "click" {
        let el = try element(input, browser)
        try focus(browser)
        guard AXUIElementPerformAction(el, kAXPressAction as CFString) == .success else {
            try fail("AX_PRESS_UNAVAILABLE: use a screenshot and browser_click_at for this element")
        }
    } else if command == "fill" {
        let el = try element(input, browser)
        let value = input["text"] as? String ?? ""
        try focus(browser)
        guard ["AXTextField","AXTextArea","AXComboBox","AXSecureTextField"].contains(text(el,kAXRoleAttribute)) else {
            try fail("Element is not an editable text field")
        }
        guard AXUIElementSetAttributeValue(el,kAXFocusedAttribute as CFString,true as CFBoolean) == .success else {
            try fail("AX_FOCUS_UNAVAILABLE: focus the observed field, then use browser_type")
        }
        var matched=false
        let focusDeadline=Date().addingTimeInterval(1)
        while Date() < focusDeadline {
            if let active=attr(try root(browser),kAXFocusedUIElementAttribute), CFEqual(active,el) { matched=true;break }
            RunLoop.current.run(until:Date().addingTimeInterval(0.05))
        }
        guard matched else { try fail("FOCUS_CHANGED: the expected field is not focused") }
        // Real keystrokes update browser input/change handlers; AXValue alone can
        // change Safari's accessibility text without changing the page's value.
        key(0,.maskCommand)
        RunLoop.current.run(until:Date().addingTimeInterval(0.08))
        if value.isEmpty { key(51) } else { typeUnicode(value) }
    } else if command == "type" {
        let expected = try element(input,browser)
        try focus(browser)
        guard let active=attr(try root(browser),kAXFocusedUIElementAttribute), CFEqual(active,expected) else { try fail("FOCUS_CHANGED: snapshot the visibly focused field before typing") }
        typeUnicode(input["text"] as? String ?? "")
    } else if command == "key" {
        let name = try required(input, "key")
        let codes: [String: CGKeyCode] = ["return":36,"tab":48,"escape":53,"backspace":51,"left":123,"right":124,"down":125,"up":126,"space":49,"a":0,"l":37,"t":17,"w":13,"r":15,"g":5,"v":9,"c":8,"f":3]
        let parts = name.lowercased().split(separator:"+").map(String.init)
        guard let last = parts.last, let code = codes[last], parts.dropLast().allSatisfy({ ["cmd","shift","alt","ctrl"].contains($0) }) else { try fail("Unsupported key") }
        var flags: CGEventFlags = []
        if parts.contains("cmd") { flags.insert(.maskCommand) }; if parts.contains("shift") { flags.insert(.maskShift) }
        if parts.contains("alt") { flags.insert(.maskAlternate) }; if parts.contains("ctrl") { flags.insert(.maskControl) }
        try focus(browser); key(code, flags)
    } else if command == "click_at" {
        guard let x = input["x"] as? Double, let y = input["y"] as? Double, x.isFinite, y.isFinite else { try fail("Invalid coordinates") }
        let windows = attr(try root(browser), kAXWindowsAttribute) as? [AXUIElement] ?? []
        let point = CGPoint(x:x,y:y)
        guard windows.contains(where: { frame($0)?.contains(point) == true }) else { try fail("Coordinates are outside this browser's windows") }
        try focus(browser)
        CGEvent(mouseEventSource:nil,mouseType:.leftMouseDown,mouseCursorPosition:point,mouseButton:.left)?.post(tap:.cghidEventTap)
        CGEvent(mouseEventSource:nil,mouseType:.leftMouseUp,mouseCursorPosition:point,mouseButton:.left)?.post(tap:.cghidEventTap)
    } else if command == "scroll" {
        try focus(browser)
        let amount = max(-1000,min(1000,input["amount"] as? Int ?? -500))
        CGEvent(scrollWheelEvent2Source:nil,units:.pixel,wheelCount:1,wheel1:Int32(amount),wheel2:0,wheel3:0)?.post(tap:.cghidEventTap)
    } else if command == "choose_file" {
        let path = try required(input, "path")
        guard path.hasPrefix("/"), FileManager.default.fileExists(atPath:path) else { try fail("File does not exist") }
        let windows = attr(try root(browser), kAXWindowsAttribute) as? [AXUIElement] ?? []
        func hasDialog(_ el: AXUIElement, _ depth: Int) -> Bool {
            if depth > 8 { return false }
            if ["AXSheet","AXDialog"].contains(text(el,kAXRoleAttribute)) || text(el,kAXSubroleAttribute) == "AXDialog" { return true }
            return (attr(el,kAXChildrenAttribute) as? [AXUIElement] ?? []).contains { hasDialog($0,depth+1) }
        }
        guard windows.contains(where:{hasDialog($0,0)}) else { try fail("Open the native file chooser first") }
        try focus(browser); key(5,[.maskCommand,.maskShift])
        RunLoop.current.run(until:Date().addingTimeInterval(0.5))
        guard let focusedValue=attr(try root(browser),kAXFocusedUIElementAttribute), CFGetTypeID(focusedValue)==AXUIElementGetTypeID() else { try fail("File path entry did not become focused") }
        let pathField=focusedValue as! AXUIElement
        guard ["AXTextField","AXComboBox"].contains(text(pathField,kAXRoleAttribute)) else { try fail("File path entry is not a text field; inspect the chooser") }
        key(0,.maskCommand)
        RunLoop.current.run(until:Date().addingTimeInterval(0.1))
        typeUnicode(path)
        RunLoop.current.run(until:Date().addingTimeInterval(0.2))
        guard text(pathField,kAXValueAttribute)==path else { try fail("File chooser did not retain the complete path; inspect and fill its path field") }
        key(36)
        RunLoop.current.run(until:Date().addingTimeInterval(0.4))
        // Select only the path. Read back the chooser before clicking its Open button.
    } else { try fail("Unknown native command") }
    invalidate()
    RunLoop.current.run(until:Date().addingTimeInterval(0.15))
    return ["action_performed":true,"browser":browser,"next":"Take a fresh snapshot and verify the intended result before continuing."]
}

while let line = readLine() {
    do {
        guard let data = line.data(using:.utf8), let object = try JSONSerialization.jsonObject(with:data) as? [String:Any] else { try fail("Invalid request") }
        let result = try perform(object)
        let responseData = try JSONSerialization.data(withJSONObject:["ok":true,"result":result],options:[.sortedKeys])
        print(String(data:responseData,encoding:.utf8)!)
    } catch {
        invalidate() // Partial actions must never leave reusable stale references.
        let message = (error as? BridgeError)?.message ?? "Native operation failed"
        let data = try! JSONSerialization.data(withJSONObject:["ok":false,"error":message])
        print(String(data:data,encoding:.utf8)!)
    }
    fflush(stdout)
}
