# From simulator to a physical iPhone

Everything below the SDK is already device-aware; the differences are signing, Developer Mode and
the USB tunnel. Get the simulator flow green first.

## 1. Prerequisites

```bash
# USB forwarding (pick one)
python3 -m pip install -e '.[device]'     # pymobiledevice3
# or
brew install libimobiledevice             # provides iproxy
```

* An Apple Developer team ID (`DEVELOPMENT_TEAM`), e.g. `ABCDE12345`.
* The iPhone connected by USB, unlocked, and "Trust This Computer" accepted.
* **Developer Mode on**: Settings → Privacy & Security → Developer Mode → on → reboot → confirm.

## 2. Verify the device is visible

```bash
sandstorm ios devices --physical-only
#   Test iPhone (physical, iOS 18.5, connected) 00008130-001A2B3C4D5E6F00
```

If the row shows `[developer-mode-off]` or `[unpaired]`, fix that before continuing — no tool can
work around it (see [`APPLE_CONSTRAINTS.md`](APPLE_CONSTRAINTS.md)).

## 3. Build and sign the agent once

```bash
export SANDSTORM_DEVELOPMENT_TEAM=ABCDE12345
sandstorm ios setup --udid 00008130-001A2B3C4D5E6F00 --team ABCDE12345
```

This runs:

```bash
xcodebuild build-for-testing \
  -project ios-agent/SandstormAgent.xcodeproj \
  -scheme SandstormAgent \
  -destination 'platform=iOS,id=<UDID>' \
  -derivedDataPath build/derived \
  DEVELOPMENT_TEAM=ABCDE12345 \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates
```

If automatic signing fails, the usual causes are:

| Symptom | Fix |
|---------|-----|
| `No profiles for 'com.sandstorm.agent' were found` | Bundle ID already taken by another team — change `AGENT_BUNDLE_ID` in `tools/generate_xcodeproj.py` and regenerate |
| `Failed to register bundle identifier` | Same as above, or the team hit its App ID limit |
| `A build only device cannot be used to run this target` | Device locked, or Developer Mode off |
| `Unable to install ... certificate not trusted` | Settings → General → VPN & Device Management → trust the developer certificate |

The result is a signed `SandstormAgent-Runner.app` plus a `.xctestrun`, both cached under
`build/derived`. **They are not rebuilt per test run.**

## 4. Start the agent

```bash
sandstorm ios start --udid 00008130-001A2B3C4D5E6F00
```

What differs from a simulator:

| Step | Simulator | Physical device |
|------|-----------|-----------------|
| Boot | `simctl bootstatus` | Device must be unlocked |
| Agent port | Free host port, bound to loopback inside the simulator | Fixed `8433` on the device |
| Tunnel | None — the simulator shares the host loopback | `iproxy <local> 8433 -u <UDID>` (or `pymobiledevice3 usbmux forward`) |
| Local port | Same as the device port | Freshly allocated on the Mac |

The CLI prints the local port and the session token.

## 5. Run

Identical to the simulator — the SDK only ever sees `127.0.0.1:<local_port>`:

```python
from sandstorm_ios import IOSDevice

device = IOSDevice("00008130-001A2B3C4D5E6F00", port=<local_port>, token="<token>").connect()
app = device.app("com.company.app")
app.launch()
app.page.get_by_id("login_button").tap()
```

## 6. Operational notes

* **Screen lock.** A locked device pauses the agent. Disable auto-lock on your test phones.
* **Certificate expiry.** Free provisioning profiles last 7 days; re-run `sandstorm ios setup`.
* **Reboots** kill the XCTest process; `AgentRunner`'s supervisor restarts `xcodebuild`, but the
  device must be unlocked for it to succeed.
* **Multiple devices.** Every `AgentRunner` allocates its own local port, so several sessions can run
  in parallel; give each one its own token.
* **Wi-Fi.** The agent binds `127.0.0.1` on purpose. Do not expose it over Wi-Fi
  (`SANDSTORM_BIND_ALL=1`) outside an isolated lab network — see [`SECURITY.md`](SECURITY.md).

## 7. Troubleshooting

```bash
SANDSTORM_VERBOSE=1 sandstorm ios start --udid <UDID> -v   # full xcodebuild output
sandstorm ios ping --port <local_port> --token <token>     # is the agent alive?
```

| Symptom | Cause |
|---------|-------|
| `Agent did not report READY` | Signing failure, locked device, or Developer Mode off — read the verbose log |
| `USB tunnel exited immediately` | `iproxy`/`pymobiledevice3` missing, or the device is unpaired |
| `Agent port never accepted a connection` | The runner started but crashed; check the `.xcresult` path printed by `xcodebuild` |
| `UNAUTHORIZED` | Token mismatch — copy the one printed by `sandstorm ios start` |
| `Failed writing xctestrun file: The folder "SandstormAgent_iphoneos18.1-arm64.xctestrun" doesn't exist` | Xcode is older than the device's iOS version — see below |
| `Invalid credentials in keychain for <email>, missing Xcode-Token` | A stale Apple ID in Xcode → Settings → Accounts; remove it and sign in again |
| `No Accounts: Add a new account in Accounts settings` | No Apple ID is signed into Xcode, so no provisioning profile can be created |
| `No profiles for 'com.sandstorm.agent.xctrunner' were found` | Same as above, or the signed-in account does not belong to the signing team |

### Signing needs an account, not just a certificate

`sandstorm ios setup` can report `Signing: 2 identity(ies) available` and still
fail to build. Certificates in the keychain only prove a team once signed;
*creating* a provisioning profile requires an Apple ID signed into Xcode, and
`xcodebuild -allowProvisioningUpdates` cannot do that on its own.

Adding an account is GUI-only — Apple provides no scriptable path:

1. Open Xcode → Settings → Accounts.
2. Remove any account listed as invalid (a stale entry produces
   `missing Xcode-Token` and suppresses the others).
3. Click **+** → Apple ID and sign in. A free Apple ID is enough; it yields a
   Personal Team with a valid Team ID.
4. Re-run `sandstorm ios setup --udid <UDID>`.

### Locked-down machines: manual signing

On a managed build machine you often cannot sign in at all, and only have
certificates and provisioning profiles installed by IT. Automatic signing is
impossible there, so Sandstorm supports manual signing against a profile that
already exists.

List what the machine has:

```bash
sandstorm ios profiles --udid <UDID>
```

```
Corp iOS Development (com.company.*, team ABCDE12345) [wildcard]
  uuid     4f1c...  team ABCDE12345 Company Ltd
  app id   com.company.*
  expires  2027-03-01
  devices  84
  covers Test iPhone: yes
```

Then build with it:

```bash
sandstorm ios setup --udid <UDID> \
    --profile "Corp iOS Development" \
    --bundle-prefix com.company
```

`--profile` switches the project to `CODE_SIGN_STYLE = Manual`, sets
`CODE_SIGN_IDENTITY = "Apple Development"` and pins
`PROVISIONING_PROFILE_SPECIFIER`, so `-allowProvisioningUpdates` — which needs
an Apple ID — is never used.

`--bundle-prefix` rewrites the two bundle identifiers so they fall inside the
profile's app ID:

| Target | Default | With `--bundle-prefix com.company` |
|--------|---------|------------------------------------|
| Demo app | `com.sandstorm.demo` | `com.company.sandstormdemo` |
| Agent | `com.sandstorm.agent` | `com.company.sandstormagent` |
| **XCTest runner** | `com.sandstorm.agent.xctrunner` | `com.company.sandstormagent.xctrunner` |

The runner is what actually gets installed, and XCTest always appends
`.xctrunner` to the agent's identifier. The profile must therefore cover that
identifier too — `setup` warns when it does not.

Requirements for this path, none of which Sandstorm can work around:

* the profile must be an **iOS App Development** profile (a distribution
  profile provisions no devices and cannot run an XCTest runner);
* the target device's UDID must already be in the profile;
* the matching private key and `Apple Development` certificate must be in the
  keychain;
* the profile must not be expired.

### The runner needs its own App ID

This is the single most common blocker, and it is an Apple rule Sandstorm
cannot work around.

XCTest installs its runner as `<agent id>.xctrunner`, and Xcode matches the
provisioning profile against that **full** identifier:

```
Provisioning profile "QA Automation Development" has app ID
"com.company.qa.automationTest", which does not match the bundle ID
"com.company.qa.automationTest.xctrunner".
```

So an explicit profile must itself end in `.xctrunner`. A profile for the bare
identifier signs an ordinary app only -- which is exactly why WebDriverAgent's
IntegrationApp builds against such a profile while `WebDriverAgentRunner` does
not. If WDA runs on your device, an `.xctrunner` App ID already exists
somewhere; the same kind is needed here.

Ask for either:

* a **wildcard** profile, e.g. `com.company.*` -- covers everything, or
* an explicit App ID and iOS App Development profile for
  `<agent id>.xctrunner`.

Given a profile for `com.company.automation.xctrunner`, Sandstorm derives the
agent identifier automatically -- no flags needed. `setup` detects an
unusable profile before running xcodebuild and prints the exact App ID to
request; `--force` builds anyway.

To pin identifiers by hand:

```bash
sandstorm ios setup --udid <UDID> --profile "<name>" \
    --agent-bundle-id com.company.automation
```

### The demo app is optional

The bundled demo app is only used by the built-in example. An explicit profile
covers one identifier, so it cannot sign both the runner and the demo; `setup`
drops the demo automatically in that case (`--no-demo` forces it). The agent
never needs it: it has no host application and launches apps by bundle ID,
exactly like WebDriverAgent. Verified on a simulator -- an agent-only build
answers `session.ping` normally.

## Xcode must be newer than the device

Xcode can only build, sign and install onto devices whose major iOS version is
at most the version of its bundled SDK. Xcode 16.1 ships the iOS 18.1 SDK, so
it cannot drive an iPhone on iOS 26 — the build fails late with a misleading
"xctestrun doesn't exist" message.

`sandstorm ios setup` prints both versions and refuses to continue:

```
Xcode:    Xcode 26.6
iOS SDK:  26.5
Target:   Test iPhone (physical, iOS 26.5.2, connected) 00008130-...
```

If the SDK is too old, install a matching Xcode and select it:

```bash
sudo xcode-select -s /Applications/Xcode-26.app/Contents/Developer
xcrun --sdk iphoneos --show-sdk-version    # must be >= the device's major version
```

Simulators are unaffected: a simulator runtime never exceeds the SDK that
Xcode ships, so simulator setup keeps working on an older Xcode.

### If you cannot upgrade Xcode

Ranked by reliability:

1. **Use simulators on that machine.** Fully supported, no workarounds.
2. **Use a device running iOS ≤ the SDK version.** Also fully supported.
3. **Build on a newer Mac, run anywhere.** `sandstorm ios setup` only has to
   run on a Mac with a current Xcode. Copy the resulting `build/DerivedData`
   directory to the older machine, which then only needs `sandstorm ios start`
   (`xcodebuild test-without-building` plus the tunnel).
4. **DeviceSupport transplant — experimental and unsupported by Apple.** Copy
   the matching `<iOS version>` folder from a newer Xcode into
   `/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport/`,
   restart Xcode, then re-run with the check bypassed:

   ```bash
   SANDSTORM_SKIP_SDK_CHECK=1 sandstorm ios setup --udid <UDID>
   ```

   This often works for a one- or two-version gap and frequently fails across
   larger ones. It uses no private APIs, but Apple does not support it and it
   can break on any Xcode update. Treat it as a stopgap, never as CI
   infrastructure.

Note the distinction: compiling *against* an older SDK is normal and produces a
binary that runs on newer iOS. What actually breaks is Xcode's ability to
**install and debug** on an OS it has no DeviceSupport bundle for — which is
exactly what an XCTest runner requires.
