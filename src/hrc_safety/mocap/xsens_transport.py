"""Xsens MVN real-time network stream -> MocapBridge.

The lab's tracker is an Xsens IMU suit (NOT OptiTrack; supersedes the
transport half of docs/design/optitrack-bridge.md — the bridge, recorder,
calibration and staleness design all carry over unchanged).

MVN Analyze streams UDP datagrams ("network streamer"). We parse message
MXTP02 (segment position + quaternion, big-endian), retain every item and its
packet metadata, and also forward one selected segment's (x, y, z) to the
legacy single-point bridge (default segment 1 = pelvis).

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
from copy import deepcopy
from typing import Callable

_HDR = struct.Struct(">6sIBBIBBBB2sH")
_ITEM = struct.Struct(">Ifffffff")
PELVIS = 1
MVN_FULL_BODY_SEGMENTS = 23


def parse_mxtp02_frame(data: bytes) -> dict | None:
    """Return one complete, JSON-safe MXTP02 datagram, or ``None``.

    Every position and quaternion item is retained, along with the counters
    required to align/deduplicate the stream later. The ``segments`` mapping
    uses string keys so the returned object can be written directly to JSON.

    None => not an MXTP02 datagram or a truncated/inconsistent packet.
    Never raises on malformed input: a bad packet must not kill the stream.
    """
    if len(data) < _HDR.size:
        return None
    try:
        (msg_id, sample_counter, datagram_counter, item_count, time_code,
         avatar_id, body_segment_count, prop_count, finger_segment_count,
         _reserved, payload_size) = _HDR.unpack_from(data)
    except struct.error:
        return None
    if msg_id != b"MXTP02":
        return None
    required_payload = item_count * _ITEM.size
    if payload_size < required_payload or len(data) < _HDR.size + payload_size:
        return None

    off = _HDR.size
    segments: dict[str, dict[str, list[float]]] = {}
    for _ in range(item_count):
        if off + _ITEM.size > len(data):
            return None
        seg, x, y, z, q0, q1, q2, q3 = _ITEM.unpack_from(data, off)
        segments[str(seg)] = {
            "position_m": [float(x), float(y), float(z)],
            "quaternion_wxyz": [float(q0), float(q1), float(q2), float(q3)],
        }
        off += _ITEM.size

    return {
        "message_id": "MXTP02",
        "sample_counter": int(sample_counter),
        "datagram_counter": int(datagram_counter),
        "time_code_s": time_code / 1000.0,
        "avatar_id": int(avatar_id),
        "item_count": int(item_count),
        "body_segment_count": int(body_segment_count),
        "prop_count": int(prop_count),
        "finger_segment_count": int(finger_segment_count),
        "payload_size": int(payload_size),
        "segments": segments,
    }


def parse_mxtp02(data: bytes, segment_id: int = PELVIS):
    """Return ``(time_code_s, (x, y, z))`` for one segment, or ``None``.

    This compatibility view is intentionally built from the full parser so a
    caller cannot accidentally introduce a second, lossy packet path.
    """
    frame = parse_mxtp02_frame(data)
    if frame is None:
        return None
    segment = frame["segments"].get(str(segment_id))
    if segment is None:
        return None
    return frame["time_code_s"], tuple(segment["position_m"])


def build_mxtp02(segments: dict[int, tuple[float, float, float]],
                 time_code_ms: int = 0, sample_counter: int = 0,
                 quaternions: (
                     dict[int, tuple[float, float, float, float]] | None
                 ) = None,
                 datagram_counter: int = 0, avatar_id: int = 0) -> bytes:
    """Construct a spec-conformant MXTP02 datagram (tests + fake feeds)."""
    quaternions = quaternions or {}
    payload = b"".join(
        _ITEM.pack(seg, x, y, z,
                   *quaternions.get(seg, (1.0, 0.0, 0.0, 0.0)))
        for seg, (x, y, z) in segments.items())
    hdr = _HDR.pack(b"MXTP02", sample_counter, datagram_counter, len(segments),
                    time_code_ms, avatar_id, len(segments), 0, 0,
                    b"\x00\x00", len(payload))
    return hdr + payload


class XsensListener:
    """UDP listener: MVN Analyze datagrams -> bridge.on_sample(...).

    MVN Analyze: Options -> Network Streamer -> add target = this machine's
    IP, port (default 9763), protocol UDP, datagram "Position + Quaternion".
    """

    def __init__(self, bridge, host: str = "0.0.0.0", port: int = 9763,
                 segment_id: int = PELVIS,
                 on_frame: Callable[[dict], None] | None = None) -> None:
        self._bridge = bridge
        self._segment_id = segment_id
        self._on_frame = on_frame
        self._frame_lock = threading.Lock()
        self._latest_frame: dict | None = None
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

    def latest_frame(self) -> dict | None:
        """Return a defensive copy of the latest complete Xsens datagram."""
        with self._frame_lock:
            return deepcopy(self._latest_frame)

    def _rx(self) -> None:
        while not self._stop.is_set():
            try:
                data, _addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            frame = parse_mxtp02_frame(data)
            if frame is None:
                continue
            received = time.monotonic()
            frame["received_monotonic_s"] = received
            with self._frame_lock:
                self._latest_frame = deepcopy(frame)
            if self._on_frame is not None:
                self._on_frame(deepcopy(frame))
            segment = frame["segments"].get(str(self._segment_id))
            if segment is not None:
                self._bridge.on_sample(
                    frame["time_code_s"], segment["position_m"], tracked=True,
                    wall_time=received)
