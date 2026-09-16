"""Unit tests for the frame codec, selector model and error mapping."""

from __future__ import annotations

import json
import socket
import threading

import pytest

from sandstorm_ios.errors import IOSElementNotFound, IOSProtocolError, error_from_payload
from sandstorm_ios.protocol.framing import BINARY_FRAME, JSON_FRAME, FrameReader, encode_frame
from sandstorm_ios.protocol.selector import Selector


def test_encode_frame_header_is_big_endian() -> None:
    frame = encode_frame(JSON_FRAME, b"hi")
    assert frame == bytes([JSON_FRAME, 0, 0, 0, 2]) + b"hi"


def test_frame_reader_handles_split_and_coalesced_frames() -> None:
    server, client = socket.socketpair()
    reader = FrameReader(client)

    payload = json.dumps({"id": 1, "success": True}).encode()
    stream = encode_frame(JSON_FRAME, payload) + encode_frame(BINARY_FRAME, b"\x89PNG")

    def feed() -> None:
        # Deliberately dribble the bytes to exercise partial reads.
        for index in range(0, len(stream), 3):
            server.sendall(stream[index : index + 3])

    thread = threading.Thread(target=feed)
    thread.start()

    frame_type, data = reader.read_frame()
    assert frame_type == JSON_FRAME
    assert json.loads(data)["id"] == 1

    frame_type, data = reader.read_frame()
    assert frame_type == BINARY_FRAME
    assert data == b"\x89PNG"

    thread.join()
    server.close()
    client.close()


def test_frame_reader_rejects_unknown_frame_type() -> None:
    server, client = socket.socketpair()
    server.sendall(bytes([0x09, 0, 0, 0, 0]))
    with pytest.raises(IOSProtocolError):
        FrameReader(client).read_frame()
    server.close()
    client.close()


def test_selector_strategies_map_to_the_compound_model() -> None:
    assert Selector.by_strategy("accessibilityId", "login_button").identifier == "login_button"
    assert Selector.by_strategy("label", "Email").label == "Email"
    assert Selector.by_strategy("index", 3).index == 3
    with pytest.raises(ValueError):
        Selector.by_strategy("xpath", "//button")  # type: ignore[arg-type]


def test_selector_serialises_only_the_criteria_it_has() -> None:
    wire = Selector(type="XCUIElementTypeButton", label="Login").to_wire()
    assert wire == {"exact": True, "type": "XCUIElementTypeButton", "label": "Login"}


def test_selector_chaining_nests_the_parent() -> None:
    parent = Selector(identifier="list")
    wire = parent.child(label="Row 1").to_wire()
    assert wire["parent"]["identifier"] == "list"
    assert wire["label"] == "Row 1"


def test_agent_errors_map_to_typed_exceptions() -> None:
    error = error_from_payload({"code": "ELEMENT_NOT_FOUND", "message": "nope"})
    assert isinstance(error, IOSElementNotFound)
    assert error.code == "ELEMENT_NOT_FOUND"
