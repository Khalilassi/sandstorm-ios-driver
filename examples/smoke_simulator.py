"""End-to-end smoke test for phases 1-3 against the bundled demo app.

Run it with a booted simulator::

    PYTHONPATH=ios-sdk:ios-controller python3 examples/smoke_simulator.py
"""

from __future__ import annotations

import json
import logging
import sys

from sandstorm_controller.agent import start_agent
from sandstorm_controller.build import AgentBuilder
from sandstorm_controller.devices import resolve_device

BUNDLE_ID = "com.sandstorm.demo"

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")


def count_nodes(node: dict) -> int:
    return 1 + sum(count_nodes(child) for child in node.get("children", []))


def main(udid: str | None = None) -> int:
    device_record = resolve_device(udid)
    print(f"Device: {device_record.describe()}")

    builder = AgentBuilder()
    build = builder.locate_build(device_record)
    builder.install_demo_app(device_record, build)

    handle = start_agent(device_record)
    try:
        device = handle.client_device()

        # Phase 1 -----------------------------------------------------------
        print(f"ping: {device.ping() * 1000:.1f} ms")

        # Phase 2 -----------------------------------------------------------
        app = device.app(BUNDLE_ID)
        app.launch(relaunch=True)
        page = app.page
        # Let the agent clear iOS interruptions ("Save Password?", permissions)
        # whenever they appear, not just where we happen to look.
        page.set_alert_policy("dismiss", buttons=["Not Now", "Don't Allow", "Cancel", "Later"])

        page.get_by_id("username").fill("khalil")
        page.get_by_id("password").fill("password")
        page.get_by_text("Login").tap()

        page.get_by_id("welcome_message").wait_for(state="visible", timeout=10)
        print("welcome text:", page.get_by_id("welcome_message").text_content())

        image = page.screenshot("build/screen.png")
        print(f"screenshot: {len(image)} bytes -> build/screen.png")

        # Phase 3 -----------------------------------------------------------
        snapshot = page.snapshot(max_depth=30)
        tree = snapshot["tree"]
        print(f"hierarchy: {count_nodes(tree)} nodes, root={tree['type']}")
        with open("build/snapshot.json", "w", encoding="utf-8") as handle_out:
            json.dump(snapshot, handle_out, indent=2)

        # Phase 6 preview ---------------------------------------------------
        page.get_by_id("logout_button").tap()
        page.get_by_id("login_button").wait_for(state="visible", timeout=10)
        page.swipe((0.5, 0.8), (0.5, 0.3), duration=0.3)
        print("orientation:", page.orientation())

        app.terminate()
        device.stop_agent()
        print("\nAll phases passed.")
        return 0
    finally:
        handle.stop()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
