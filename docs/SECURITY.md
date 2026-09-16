# Security model

The agent runs inside a signed test process with the ability to drive the whole UI. Treat its port
as a remote control for the device.

## 1. Binding

The listener is created with `requiredLocalEndpoint = 127.0.0.1:<port>`, so it accepts connections
only from:

* the host Mac's loopback, when running in a simulator (the simulator shares the host loopback);
* the `usbmuxd` tunnel, when running on a physical device (usbmux connects to the device's own
  loopback).

There is **no open Wi-Fi automation port by default**. `SANDSTORM_BIND_ALL=1` exists for isolated lab
networks only; it is never set by the controller and should be considered unsafe.

## 2. Session token

* The controller generates a 128-bit token (`secrets.token_hex(16)`) per session.
* It reaches the device through the patched `.xctestrun` (`SANDSTORM_TOKEN`), never through a file on
  disk that other users could read and never over the network.
* Clients must present it in the handshake. Comparison is constant time (length check plus an XOR
  fold) to avoid timing oracles.
* A wrong or missing token closes the connection immediately with `UNAUTHORIZED`; no command is ever
  executed before the handshake completes.
* If no token is configured, the agent accepts unauthenticated handshakes. This only happens when you
  start the agent manually from Xcode — the CLI always sets one.

## 3. Command surface

The agent's dispatcher is a fixed `switch` over a closed set of method names.

* **No arbitrary shell execution.** There is no `exec`, `system`, `Process` or `NSTask` anywhere in
  the agent.
* **No file read/write primitives.**
* **No `eval`-style dynamic dispatch.** Unknown methods return `UNKNOWN_METHOD`.
* `predicate` selectors do pass a string to `NSPredicate(format:)`. This is a query language, not a
  code execution vector, but it is still attacker-controlled input if you forward untrusted
  selectors — do not expose the agent to untrusted clients.

## 4. Frame limits

Payloads are capped at 64 MiB on both sides and the length is validated before allocation, so a
malicious peer cannot force an unbounded allocation with a forged header.

## 5. Threat model

| Threat | Mitigation |
|--------|------------|
| Another local user connects to the agent | Session token; ports are ephemeral and per session |
| A device on the LAN connects to the agent | Loopback-only binding |
| Token leakage through process listings | Token is passed via the `.xctestrun` plist, not on the command line |
| Replay of a captured session | Tokens are per session and die with the agent |
| Memory exhaustion via huge frames | 64 MiB cap, length validated before reading |
| Malicious commands after connection | Fixed method table; no shell, no filesystem access |

## 6. What is *not* protected

* **The channel is not encrypted.** It is loopback or USB; adding TLS would cost latency for no
  practical gain in that trust boundary. Do not route it over an untrusted network.
* **Screenshots may contain secrets.** They are written wherever the caller asks; treat CI artifacts
  accordingly.
* **The agent has the app's full UI privileges.** Never point it at a device holding real user data.

## 7. Checklist for CI

- [ ] Agent started by the controller (token always set)
- [ ] `SANDSTORM_BIND_ALL` unset
- [ ] Tokens not echoed into build logs
- [ ] Screenshot artifacts scrubbed or access-controlled
- [ ] Test devices hold no production accounts
