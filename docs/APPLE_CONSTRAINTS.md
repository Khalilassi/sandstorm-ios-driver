# Apple constraints

This project stays entirely inside what Apple supports. That has hard consequences, and pretending
otherwise is how automation stacks become unmaintainable. Here is exactly where the walls are.

## 1. You cannot synthesize touch events without XCTest

**What Apple allows.** Only a process running under Apple's testing infrastructure can inject
synthetic touch and keyboard events into another app. On device, that process is an XCTest *runner*
app (`SandstormAgent-Runner.app`), signed with a development certificate and launched by
`XCTestBootstrap` on behalf of `xcodebuild`.

**What XCTest provides.** `XCUIApplication`, `XCUIElement`, `XCUICoordinate`, `XCUIDevice`,
`XCUIScreen` — enough to launch apps, query the accessibility tree, tap, type, swipe, rotate and
screenshot.

**What cannot be avoided.**

* There is no daemon we could install once and talk to forever. A test *run* must be in progress.
  This is why the controller owns an `xcodebuild test-without-building` child process for the entire
  session, and why the agent is a test method with an infinite loop.
* If the test process dies, automation stops. Hence `AgentRunner`'s supervisor and auto-restart.
* This is the same constraint WebDriverAgent lives under. Sandstorm does not avoid the runner; it
  avoids the WebDriver protocol, the Appium server, the Node.js runtime and the driver stack on top
  of it.

## 2. Code signing and provisioning (real devices only)

**What Apple allows.** Installing a development-signed runner app onto a device you own, with a
provisioning profile that includes that device's UDID.

**What cannot be avoided.**

* A real Apple Developer account and a `DEVELOPMENT_TEAM` for the build.
* A unique bundle identifier per team; `com.sandstorm.agent` may collide — override
  `PRODUCT_BUNDLE_IDENTIFIER`.
* Free (7-day) certificates expire; the agent must be reinstalled weekly.
* Simulators need none of this, which is why the MVP targets them first.

## 3. Developer Mode (iOS 16+)

**What Apple allows.** Running development-signed code only when the user has explicitly enabled
*Settings → Privacy & Security → Developer Mode* and re-authenticated after the reboot it forces.

**What cannot be avoided.** No API can enable it remotely — it is a deliberate anti-abuse control.
The controller can only *detect* it (`sandstorm ios setup` reports it via `devicectl`/
`pymobiledevice3`) and tell the user to flip the switch.

## 4. The device must be trusted and paired

`usbmuxd` refuses to forward to an unpaired device. Pairing requires physically unlocking the phone
and tapping "Trust". Again: detectable, not automatable.

## 5. Networking on the device

**What Apple allows.** An app (including a test runner) may bind a TCP listener. Traffic can reach
it over Wi-Fi, or through `usbmuxd`, Apple's public USB multiplexer, which is what Xcode itself uses.

**What cannot be avoided.** There is no supported "USB pipe" API for third-party code, so the host
side must go through a usbmux client (`iproxy` or `pymobiledevice3 usbmux forward`). Both are
userspace clients of the documented socket — no private frameworks, no jailbreak.

On simulators none of this applies: the simulator shares the host's loopback interface, so a socket
bound to `127.0.0.1:P` inside the simulator *is* `127.0.0.1:P` on the Mac. The tunnel is a no-op.

## 6. Accessibility tree fidelity

**What XCTest provides.** `XCUIElement.snapshot()` (public since Xcode 11) returning
`XCUIElementSnapshot` with `elementType`, `identifier`, `label`, `title`, `value`,
`placeholderValue`, `isEnabled`, `isSelected`, `frame` and `children`.

**What cannot be avoided.**

* `XCUIElementSnapshot` has **no** `isHittable` and no occlusion information. True visibility is only
  available on `XCUIElement`, one IPC round trip per element. Sandstorm therefore reports a
  heuristic `visible` in snapshots and an authoritative `hittable` in `element.getAttributes`.
* Elements that the app does not expose to accessibility are invisible to *any* XCUITest-based tool,
  including Appium. The fix belongs in the app: set `accessibilityIdentifier`.
* Hierarchies are large. `maxDepth` and subtree snapshots exist for this reason.

## 7. Keyboard and text entry

`typeText` requires the element to have keyboard focus and the software keyboard to be present. On
simulators, "Connect Hardware Keyboard" silently changes behaviour — disable it with
`xcrun simctl status_bar`/Simulator settings if typing misbehaves.

## 8. What we explicitly do *not* do

* **No private iOS APIs.** No `XCAXClient_iOS`, no `UIAutomation`, no direct `accessibilityserver`
  access, no `IOHIDEvent` injection.
* **No jailbreak paths.**
* **No shell execution on the device.** The agent's command surface is a fixed switch statement.

> **Experimental / unsupported (not implemented here, listed for completeness).** Some tools reach
> for private accessibility APIs to get faster hierarchy dumps or true hit-testing. Those break on
> every iOS release, can get App Store builds rejected, and are out of scope for this project. If you
> ever add such a path, gate it behind an explicit `--experimental-unsupported` flag and never make
> it the default.

## 9. Summary table

| Want | Supported way | Cost |
|------|---------------|------|
| Tap a button on a real device | XCTest runner app | Signing, Developer Mode, a live `xcodebuild` process |
| Talk to the device over USB | `usbmuxd` via `iproxy`/`pymobiledevice3` | An extra host process per session |
| Dump the UI tree | `XCUIElement.snapshot()` | ~100–400 ms on large hierarchies |
| Know if an element is truly visible | `XCUIElement.isHittable` | One IPC round trip per element |
| Enable Developer Mode | Manual, on the device | Cannot be automated |
| Run without any test process | — | **Impossible** on stock iOS |
