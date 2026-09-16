# Sandstorm Protocol v1

A versioned, framed, JSON-RPC-like protocol over a plain TCP stream.
It is **not** WebDriver and it is **not** HTTP.

## 1. Framing

```
+--------+------------------+--------------------+
| type   | length (uint32)  | payload            |
| uint8  | 4 bytes, big-end | `length` bytes     |
+--------+------------------+--------------------+
```

| Type | Value | Meaning |
|------|-------|---------|
| JSON | `0x01` | UTF-8 encoded JSON object |
| Binary | `0x02` | Raw bytes (screenshot data) |

A JSON response that carries a `binary` descriptor is **always immediately followed** by exactly one
binary frame on the same connection. Maximum payload: 64 MiB.

This is why screenshots are never base64: base64 inflates payloads by ~33 % and adds an encode and a
decode pass on a link where bytes are already the bottleneck.

## 2. Handshake

The first JSON frame a client sends must be the handshake.

**Client → Agent**

```json
{
  "protocolVersion": 1,
  "client": "sandstorm-python",
  "clientVersion": "0.1.0",
  "token": "0f1e2d..."
}
```

**Agent → Client**

```json
{
  "protocolVersion": 1,
  "agentVersion": "0.1.0",
  "sessionId": "0B2A9E6C-...",
  "device": {
    "name": "iPhone 17 Pro",
    "iosVersion": "26.5",
    "model": "iPhone",
    "udid": "62AFE684-...",
    "isSimulator": true,
    "screen": { "width": 402, "height": 874, "scale": 3 }
  }
}
```

Rules:

* a version mismatch closes the connection with `PROTOCOL_ERROR`;
* a wrong or missing token closes the connection with `UNAUTHORIZED` (constant-time comparison);
* commands sent before the handshake are rejected.

## 3. Requests and responses

**Request**

```json
{ "id": 1, "method": "element.tap", "params": { "selector": { "identifier": "login_button" } } }
```

**Success**

```json
{ "id": 1, "success": true, "result": {} }
```

**Failure**

```json
{
  "id": 1,
  "success": false,
  "error": { "code": "ELEMENT_NOT_FOUND", "message": "Element was not found", "details": {} }
}
```

**Success with a binary attachment** (followed by one `0x02` frame of `length` bytes)

```json
{
  "id": 7,
  "success": true,
  "result": { "width": 402, "height": 874, "mimeType": "image/png", "length": 67314 },
  "binary": { "length": 67314, "encoding": "raw", "mimeType": "image/png" }
}
```

`id` is a monotonic integer chosen by the client. Responses are correlated by `id`; late or orphaned
replies are discarded rather than mis-attributed.

## 4. Error codes

| Code | Python exception |
|------|------------------|
| `UNKNOWN_METHOD`, `INVALID_PARAMS`, `PROTOCOL_ERROR` | `IOSProtocolError` |
| `UNAUTHORIZED` | `IOSUnauthorized` |
| `ELEMENT_NOT_FOUND`, `ALERT_NOT_FOUND` | `IOSElementNotFound` |
| `ELEMENT_NOT_INTERACTABLE` | `IOSElementNotInteractable` |
| `STALE_ELEMENT` | `IOSStaleElement` |
| `APP_LAUNCH_FAILED`, `NO_ACTIVE_APP` | `IOSAppLaunchError` |
| `TIMEOUT` | `IOSCommandTimeout` |
| `SNAPSHOT_FAILED`, `INTERNAL_ERROR` | `IOSError` |

Transport level failures raise `IOSAgentConnectionError`, `IOSAgentNotRunning` or `IOSSessionLost`.

## 5. Selector object

Every criterion present is ANDed into a single `NSPredicate` evaluated inside the app process.

```json
{
  "type": "XCUIElementTypeButton",
  "identifier": "login_button",
  "label": "Login",
  "text": "Login",
  "value_": "on",
  "predicate": "label BEGINSWITH 'Log'",
  "index": 0,
  "exact": true,
  "parent": { "identifier": "list" }
}
```

The compact form `{"strategy": "accessibilityId", "value": "login_button"}` is also accepted and is
normalized into the object above.

* `text` matches `label`, `value`, `title` or `placeholderValue`.
* `exact: false` switches `==` to `CONTAINS`.
* `parent` enables locator chaining (descendants of the parent match).
* `index` selects `element(boundBy:)`; without it, `firstMatch` is used.
* **No XPath.**

## 6. Methods

### session

| Method | Params | Result |
|--------|--------|--------|
| `session.ping` | — | `{pong, agentVersion, timestamp}` |
| `session.info` | — | `{agentVersion, protocolVersion, uptime, activeBundleId, device}` |
| `session.stop` | — | `{stopping: true}` — ends the XCTest run |
| `session.setAlertPolicy` | `policy`, `buttons[]?` | `{policy, buttons[]}` |

### app

| Method | Params | Result |
|--------|--------|--------|
| `app.launch` | `bundleId`, `arguments[]`, `environment{}`, `relaunch`, `timeout` | `{bundleId, state}` |
| `app.activate` | `bundleId` | `{state}` |
| `app.terminate` | `bundleId` | `{bundleId}` |
| `app.state` | `bundleId` | `{state, running}` |

### element

| Method | Params | Result |
|--------|--------|--------|
| `element.find` | `selector`, `timeout` | attributes |
| `element.findAll` | `selector`, `limit` | `{count, elements[]}` |
| `element.exists` | `selector`, `timeout` | `{exists}` |
| `element.getAttributes` | `selector`, `timeout` | attributes incl. `hittable` |
| `element.tap` | `selector`, `timeout` | `{}` |
| `element.longPress` | `selector`, `duration`, `timeout` | `{}` |
| `element.typeText` | `selector`, `text`, `clear`, `timeout` | `{}` |
| `element.clear` | `selector`, `timeout` | `{}` |
| `element.waitFor` | `selector`, `state`, `timeout` | `{state}` |

`state` ∈ `exists`, `not_exists`, `visible`, `not_visible`, `enabled`.

The wait runs **inside the agent**, so a 10-second wait costs one round trip, not fifty. The
condition is polled directly (`exists` / `isHittable` / `isEnabled`) rather than through
`XCTNSPredicateExpectation`: the expectation only re-evaluates on its own schedule and needs an
uninterrupted `XCTWaiter` run, which does not compose with the agent's run-loop pump — it reported
timeouts for elements that demonstrably existed. Each poll is a query inside the app process, so no
USB traffic is involved.

### gesture

All coordinates are normalized to `0..1` of the active application's frame and executed through
`XCUICoordinate`.

| Method | Params |
|--------|--------|
| `gesture.tap` | `at: {x, y}` |
| `gesture.longPress` | `at: {x, y}`, `duration` |
| `gesture.swipe` | `from: {x, y}`, `to: {x, y}`, `duration` |
| `gesture.drag` | `from`, `to`, `duration` |

### screen

| Method | Params | Result |
|--------|--------|--------|
| `screen.screenshot` | `scale`, `quality`, `appOnly` | metadata + binary frame |
| `screen.snapshot` | `maxDepth`, `includeInvisible`, `selector` | `{tree, screen}` |

### alert / device

| Method | Params | Result |
|--------|--------|--------|
| `alert.accept` | `button?` | `{}` |
| `alert.dismiss` | `button?` | `{}` |
| `alert.text` | — | `{text, buttons[]}` |
| `alert.info` | — | `{present, text?, buttons[]?}` — never throws |
| `device.orientation` | `orientation?` | `{orientation}` |

Alerts are looked up in the app under test first, then in SpringBoard (system permission dialogs are
not owned by the app). Both `alerts` and `sheets` are searched, because iOS renders some system
prompts — the keychain "Save Password?" being the common one — as a sheet.

#### Automatic interruption handling

`session.setAlertPolicy` makes the agent clear blocking dialogs by itself:

```json
{"method": "session.setAlertPolicy",
 "params": {"policy": "dismiss", "buttons": ["Not Now", "Don't Allow", "Cancel"]}}
```

`policy` ∈ `manual` (default), `dismiss` (first/left button), `accept` (last button). `buttons` is
tried first, in order. While a policy is active, every `element.*` interaction:

1. clears a dialog that is already on screen, since it would swallow the touch;
2. retries once if the interaction failed because of a dialog;
3. after a short settle delay, clears a dialog that appeared *during* the interaction and replays it
   — iOS delivered that touch to the dialog, not to the app. The replay is skipped when the target
   element no longer exists, which means the interaction had in fact landed and the dialog was a
   consequence of it.

`element.waitFor` clears dialogs between polls for the same reason. The default `manual` policy costs
nothing: no extra queries are issued.

## 7. Normalized snapshot format

```json
{
  "type": "XCUIElementTypeWindow",
  "identifier": "",
  "label": "",
  "value": null,
  "title": "",
  "placeholder": null,
  "enabled": true,
  "selected": false,
  "visible": true,
  "path": "0",
  "frame": { "x": 0, "y": 0, "width": 393, "height": 852 },
  "children": [
    {
      "type": "XCUIElementTypeButton",
      "identifier": "login_button",
      "label": "Login",
      "value": null,
      "enabled": true,
      "visible": true,
      "path": "0.0",
      "frame": { "x": 100, "y": 600, "width": 180, "height": 50 }
    }
  ]
}
```

* `debugDescription` is never returned — it is unstable, unparseable and version dependent.
* `path` is a stable positional address (`0.2.1`) used by the Inspector to map tree selections back
  to nodes without object identity.
* `truncated: true` appears instead of `children` when `maxDepth` is reached.
* `visible` is a heuristic (non-empty frame intersecting the screen); see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#3-performance-model).

## 8. Versioning

`protocolVersion` is bumped on any breaking change. The agent rejects mismatched clients at
handshake time rather than failing mysteriously later. Additive, optional parameters do not bump the
version.
