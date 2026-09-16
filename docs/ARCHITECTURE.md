# Architecture

## 1. Components

| Component | Language | Runs on | Responsibility |
|-----------|----------|---------|----------------|
| `ios-agent` | Swift / XCTest | iPhone or simulator | Executes UI actions, serves the command protocol |
| `ios-controller` | Python | macOS | Discovery, build, agent lifecycle, tunnel, health |
| `ios-sdk` | Python | anywhere with a route to the tunnel | User-facing automation API |
| `ios-inspector` | Python + PySide6 | macOS | Visual element explorer and locator generator |

```
┌──────────────────────┐      ┌────────────────────────┐
│  Inspector (PySide6) │      │  pytest / user script  │
└──────────┬───────────┘      └───────────┬────────────┘
           └──────────────┬───────────────┘
                          ▼
              ┌───────────────────────┐
              │  ios-sdk              │  IOSDevice → IOSApplication → IOSPage → Locator
              │  IOSControllerClient  │  framing, handshake, retries, timeouts
              └───────────┬───────────┘
                          │ TCP (length-prefixed frames)
                          ▼
              ┌───────────────────────┐
              │  ios-controller       │  xcodebuild test-without-building
              │  AgentRunner + Tunnel │  usbmux forwarding, supervision
              └───────────┬───────────┘
                          │ loopback (sim) / usbmuxd (device)
                          ▼
              ┌───────────────────────┐
              │  ios-agent (XCTest)   │  NWListener → CommandRouter → XCUITest
              └───────────┬───────────┘
                          │ XCTest IPC (Apple private, but Apple-operated)
                          ▼
                 Application Under Test
```

## 2. The on-device agent

The agent is one XCTest method that never returns:

```swift
func testAutomationServer() throws {
    try server.start()
    while !server.shouldStop && !router.stopRequested {
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.02))
        while let pending = server.dequeue() {
            let (response, binary) = router.handle(pending.request)
            pending.connection.send(response: response, binary: binary)
        }
    }
}
```

### Threading model

* **Network.framework queue** (`com.sandstorm.agent.net`) accepts connections, parses frames and
  pushes `RequestMessage`s onto a mutex-protected queue. It never touches XCUITest.
* **XCTest thread** owns the loop above. Every XCUITest call therefore happens on the thread XCTest
  itself created, which is the only supported way to drive `XCUIApplication`.
* The run loop is pumped explicitly (`RunLoop.run(mode:before:)`) so Network.framework callbacks and
  `XCTWaiter` expectations both make progress while we stay synchronous and single-session.

Consequences, by design:

* commands are executed strictly in order — no interleaving of taps;
* a long agent-side wait blocks other commands, which is the correct semantic for a single session;
* no `async`/actor complexity inside a test process where XCTest owns the main queue.

### Why not WebDriver

WebDriver forces HTTP verbs, session URLs, JSON error payloads, W3C actions and capability
negotiation onto a link where a request costs a USB round trip. Sandstorm sends a 5-byte header and
one JSON object instead, and it puts *waiting* on the device side, which removes the polling storm
that dominates Appium's latency profile.

## 3. Performance model

The expensive operation in XCUITest is not the network, it is the **IPC between the test runner and
the application under test**. Every `XCUIElement` property access is one synchronous round trip.

| Concern | Naive approach | What Sandstorm does |
|---------|----------------|---------------------|
| Hierarchy dump | Walk `XCUIElement` children, read ~10 properties each → `O(10·N)` IPC calls | `try app.snapshot()` once → `O(1)` IPC call, then a purely local walk over `XCUIElementSnapshot` value objects |
| Element matching | Fetch candidates, filter in Python | Build one `NSPredicate`, let XCTest evaluate it **inside the app process** |
| Waiting | Poll `exists` from the host every 200 ms | `XCTNSPredicateExpectation` + `XCTWaiter` inside the agent: one request per wait |
| Screenshots | base64 in JSON (+33% size, two extra encodes) | Dedicated binary frame following the JSON response |
| Coordinates | Device pixels | Normalized 0..1 via `XCUICoordinate`, resolution independent |
| Screen size | One screenshot per query | Cached after the first capture |

`XCUIElementSnapshot` has been public API since Xcode 11 — this is not a private-API trick.

Known limits (documented rather than hidden):

* `XCUIElementSnapshot` has no `isHittable`, so `visible` is a heuristic: a non-empty frame that
  intersects the screen. Occlusion by an overlapping sibling is not detected. `element.getAttributes`
  returns the authoritative `hittable` flag because it can afford the extra round trip.
* `snapshot()` on a huge, deeply nested hierarchy still costs 100–400 ms; use `maxDepth` or pass a
  `selector` to snapshot a subtree.

## 4. Controller lifecycle

```
sandstorm ios setup
  ├── detect Xcode (xcodebuild -version, xcode-select -p)
  ├── detect signing identities (security find-identity)
  ├── xcodebuild build-for-testing        ← once, cached in build/derived
  ├── sign (automatic, DEVELOPMENT_TEAM for devices)
  └── install demo app (simctl / devicectl)

sandstorm ios start --udid <UDID>
  ├── verify the .xctestrun exists         ← never rebuilds
  ├── patch the .xctestrun with SANDSTORM_PORT / SANDSTORM_TOKEN / SANDSTORM_LOG_LEVEL
  ├── xcodebuild test-without-building -only-testing:…/testAutomationServer
  ├── wait for the SANDSTORM_AGENT_READY marker on stdout
  ├── open the tunnel (no-op on simulators, iproxy/pymobiledevice3 on devices)
  └── wait for the port to accept a connection
```

After that, test execution only sends commands — no build, no reinstall.

### Why the `.xctestrun` is patched

`xcodebuild` forwards `TEST_RUNNER_*` environment variables only when it is driven by a *scheme*.
Because we deliberately run `test-without-building -xctestrun` (so we never rebuild), the controller
writes the variables into a copy of the plist instead, and also disables the per-test timeout so a
long-lived agent is never killed mid-session.

## 5. Reliability

| Mechanism | Where |
|-----------|-------|
| Heartbeat | `session.ping` / `IOSDevice.ping()` / `client.is_healthy()` |
| Command timeout | per-request socket timeout in `IOSControllerClient` |
| XCTest timeout | `TestTimeoutsEnabled = False` in the patched `.xctestrun` |
| Reconnect | `invoke()` reconnects and retries on connection loss (`max_retries`) |
| Agent restart | `AgentRunner` supervisor thread respawns `xcodebuild` if it exits |
| Graceful shutdown | `session.stop` flips the loop flag, the test method returns normally |
| Structured logging | `[sandstorm][timestamp][LEVEL]` on the device, `logging` on the host |
| Stale responses | responses are correlated by `id`; late replies are discarded |
| Device disconnect | tunnel process death is detected via `Tunnel.is_active` |

## 6. Deliberate non-goals for the MVP

* XPath (slow, brittle, no native XCUITest equivalent).
* Parallel command execution on one session.
* Element handle caching across commands — selectors are re-resolved agent-side, which is cheap
  because matching is a single predicate query. Handle caching is the next optimization and would
  require stale-handle invalidation.
* Diff-based Inspector updates (full refresh is fast enough at this size).
