"""The canonical login flow from the README.

Assumes an agent is already running::

    sandstorm ios start --udid <UDID>
    export SANDSTORM_AGENT_PORT=<port> SANDSTORM_TOKEN=<token>
    python3 examples/login_flow.py
"""

from __future__ import annotations

import logging

from sandstorm_ios import IOSDevice, IOSElementNotFound

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

BUNDLE_ID = "com.sandstorm.demo"


def main() -> int:
    # Host/port/token default to SANDSTORM_AGENT_HOST / _PORT / SANDSTORM_TOKEN.
    device = IOSDevice()
    device.connect()

    app = device.app(BUNDLE_ID)
    app.launch(relaunch=True)
    page = app.page
    page.set_alert_policy("dismiss", buttons=["Not Now", "Don't Allow", "Cancel"])

    page.get_by_id("username").fill("khalil")
    page.get_by_id("password").fill("password")
    page.get_by_text("Login").tap()

    page.get_by_text("Welcome khalil").wait_for(state="visible", timeout=10)
    page.screenshot("screen.png")

    try:
        page.get_by_id("does_not_exist").with_timeout(1).tap()
    except IOSElementNotFound as exc:
        print(f"expected failure: {exc}")

    app.terminate()
    device.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
