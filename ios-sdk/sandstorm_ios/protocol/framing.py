"""Frame level encoding/decoding.

Wire format (all integers big endian)::

    +--------+-----------------+-------------------+
    | type   | length (uint32) | payload           |
    | uint8  | 4 bytes         | ``length`` bytes  |
    +--------+-----------------+-------------------+

``type`` is :data:`JSON_FRAME` or :data:`BINARY_FRAME`. A JSON response that
carries a ``binary`` descriptor is always immediately followed by exactly one
binary frame, which is how screenshots avoid base64 inflation (~33% larger and
an extra encode/decode pass on both sides).
"""

from __future__ import annotations

import socket
import struct
from typing import Final

from ..errors import IOSAgentConnectionError, IOSProtocolError

JSON_FRAME: Final[int] = 0x01
BINARY_FRAME: Final[int] = 0x02

HEADER_SIZE: Final[int] = 5
MAX_PAYLOAD_SIZE: Final[int] = 64 * 1024 * 1024

_HEADER = struct.Struct(">BI")


def encode_frame(frame_type: int, payload: bytes) -> bytes:
    """Serializes a single frame."""
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise IOSProtocolError(f"Payload of {len(payload)} bytes exceeds the frame limit")
    return _HEADER.pack(frame_type, len(payload)) + payload


class FrameReader:
    """Blocking frame reader over a socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock

    def read_frame(self) -> tuple[int, bytes]:
        """Reads exactly one frame, blocking until it is complete."""
        header = self._read_exactly(HEADER_SIZE)
        frame_type, length = _HEADER.unpack(header)
        if frame_type not in (JSON_FRAME, BINARY_FRAME):
            raise IOSProtocolError(f"Unknown frame type 0x{frame_type:02x}")
        if length > MAX_PAYLOAD_SIZE:
            raise IOSProtocolError(f"Agent announced an oversized frame of {length} bytes")
        return frame_type, self._read_exactly(length)

    def _read_exactly(self, count: int) -> bytes:
        chunks: list[bytes] = []
        remaining = count
        while remaining:
            try:
                chunk = self._socket.recv(min(remaining, 1 << 16))
            except socket.timeout as exc:
                raise IOSAgentConnectionError("Timed out reading from the agent") from exc
            except OSError as exc:
                raise IOSAgentConnectionError(f"Agent socket error: {exc}") from exc
            if not chunk:
                raise IOSAgentConnectionError("Agent closed the connection")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
