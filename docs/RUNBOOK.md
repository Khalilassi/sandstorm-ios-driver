# E2E runbook

## One-time

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -e .                  # SDK + controller + `sandstorm` CLI
python3 -m pip install pymobiledevice3       # device only: app listing
brew install libimobiledevice                # device only: iproxy USB tunnel
```

If `sandstorm` is not found afterwards, the console script is not on `PATH`;
use `python3 -m sandstorm_controller ...` instead (see README → Installation).

On the iPhone: Developer Mode on, Auto-Lock = Never, and trust the certificate in
Settings -> General -> VPN & Device Management.

## Per machine / after code changes

```bash
sandstorm ios devices                        # pick a UDID
sandstorm ios setup --udid <UDID>            # build + sign + install the agent (Team ID auto-detected)
```

## Per session

```bash
sandstorm ios start --udid <UDID> --token dev1     # leave running; prints the local port
```

## Per test run (any number of times, agent stays up)

```bash
export SANDSTORM_AGENT_PORT=<port> SANDSTORM_TOKEN=dev1

sandstorm ios ping                                 # health check
python3 examples/login_flow.py                     # demo app login
python3 examples/smoke_simulator.py <UDID>         # full phases 1-3 (starts its own agent)
python3 -m pytest -q                               # host-side unit tests
```

## Concrete: a physical device

```bash
sandstorm ios setup --udid <DEVICE_UDID>
sandstorm ios start --udid <DEVICE_UDID> --token dev1
SANDSTORM_AGENT_PORT=<port> SANDSTORM_TOKEN=dev1 python3 examples/login_flow.py
```

## Simulator

```bash
sandstorm ios setup --udid <SIM_UDID>
python3 examples/smoke_simulator.py <SIM_UDID>     # opens Simulator.app; SANDSTORM_HEADLESS=1 to hide
```

## Troubleshooting

| Message | Fix |
|---------|-----|
| `The device is locked` | Unlock; set Auto-Lock to Never |
| `Developer certificate is not trusted` | Settings -> General -> VPN & Device Management -> Trust |
| `Terminating stale agent supervisor` | Normal: a previous session was cleaned up |
| `Lost the agent session` | Device locked or two runners on one device; rerun |
