"""Xsens MVN real-time network stream -> MocapBridge.

The lab's tracker is an Xsens IMU suit (NOT OptiTrack; supersedes the
transport half of docs/design/optitrack-bridge.md — the bridge, recorder,
calibration and staleness design all carry over unchanged).

MVN Analyze streams UDP datagrams ("network streamer"). We parse message
MXTP02 (segment position + quaternion, big-endian) and forward ONE segment's
(x, y, z) — default segment 1 = pelvis, the single-point operator model.

Datagram layout (MVN real-time network streaming protocol):
  header (24 B): 6s ID ("MXTP02") | u32 sample counter | u8 datagram counter
                 | u8 item count | u32 time code (ms) | u8 avatar ID
                 | u8 body segments | u8 props | u8 finger segments
                 | 2s reserved | u16 payload size
  per item (32 B): u32 segment ID | f32 x | f32 y | f32 z | f32 q0..q3

VERIFY-ON-LAB NOTE: parser is validated here against packets built to this
spec; the first REAL packet from the lab's MVN Analyze must be checked once
(scripts/record_mocap.py --dump prints raw header fields for that purpose).
"""
from __future__ import annotations

import socket
import struct
import threading
import time

_HDR = struct.Struct(">6sIBBIBBBB2sH")
_ITEM = struct.Struct(">Ifffffff")
PELVIS = 1


def parse_mxtp02(data: bytes, segment_id: int = PELVIS):
    """Return (time_code_s, (x, y, z)) for segment_id, or None.

    None => not an MXTP02 datagram, truncated packet, or segment absent.
    Never raises on malformed input: a bad packet must not kill the stream.
    """
    if len(data) < _HDR.size:
        return None
    try:
        msg_id, _sc, _dg, item_count, time_code, *_rest = _HDR.unpack_from(data)
    except struct.error:
        return None
    if msg_id != b"MXTP02":
        return None
    off = _HDR.size
    for _ in range(item_count):
        if off + _ITEM.size > len(data):
            return None
        seg, x, y, z, *_quat = _ITEM.unpack_from(data, off)
        if seg == segment_id:
            return time_code / 1000.0, (x, y, z)
        off += _ITEM.size
    return None


def build_mxtp02(segments: dict[int, tuple[float, float, float]],
                 time_code_ms: int = 0, sample_counter: int = 0) -> bytes:
    """Construct a spec-conformant MXTP02 datagram (tests + fake feeds)."""
    payload = b"".join(
        _ITEM.pack(seg, x, y, z, 1.0, 0.0, 0.0, 0.0)
        for seg, (x, y, z) in segments.items())
    hdr = _HDR.pack(b"MXTP02", sample_counter, 0, len(segments), time_code_ms,
                    0, len(segments), 0, 0, b"\x00\x00", len(payload))
    return hdr + payload


class XsensListener:
    """UDP listener: MVN Analyze datagrams -> bridge.on_sample(...).

    MVN Analyze: Options -> Network Streamer -> add target = this machine's
    IP, port (default 9763), protocol UDP, datagram "Position + Quaternion".
    """

    def __init__(self, bridge, host: str = "0.0.0.0", port: int = 9763,
                 segment_id: int = PELVIS) -> None:
        self._bridge = bridge
        self._segment_id = segment_id
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._rx, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._sock.close()

    def _rx(self) -> None:
        while not self._stop.is_set():
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_mxtp02(data, self._segment_id)
            if parsed is not None:
                ts, pos = parsed
                self._bridge.on_sample(ts, pos, tracked=True,
                                       wall_time=time.monotonic())
