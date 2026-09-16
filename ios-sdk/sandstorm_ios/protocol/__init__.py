"""Wire protocol for the Sandstorm iOS Driver.

The protocol is deliberately tiny: length prefixed frames carrying JSON, plus
optional raw binary frames for screenshots.
"""

from .framing import BINARY_FRAME, JSON_FRAME, FrameReader, encode_frame
from .messages import (
    PROTOCOL_VERSION,
    Command,
    DeviceInfo,
    Handshake,
    Response,
)
from .selector import Selector

__all__ = [
    "PROTOCOL_VERSION",
    "JSON_FRAME",
    "BINARY_FRAME",
    "FrameReader",
    "encode_frame",
    "Command",
    "Response",
    "Handshake",
    "DeviceInfo",
    "Selector",
]
