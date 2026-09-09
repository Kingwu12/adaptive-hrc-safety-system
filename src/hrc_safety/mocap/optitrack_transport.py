"""OptiTrack Motive/NatNet transport with multi-rigid-body monitoring.

This adapter uses OptiTrack's official ``NatNetClient.py`` sample (distributed
with the NatNet SDK).  The head rigid body feeds ``MocapBridge`` and therefore
the safety controller.  Additional rigid bodies on the robot are retained for
logging/geometry validation; they never substitute for a missing head sample.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
import socket
import struct
import threading
import time
from typing import Any

import numpy as np

NAT_FRAMEOFDATA = 7
NATNET_DATA_PORT = 1511
NATNET_MULTICAST = "239.255.42.99"


def parse_natnet4_marker_sets(data: bytes):
    """Retain named marker positions from the existing NatNet 4.0 stream.

    Positions remain in raw OptiTrack metres. This is independent of the
    rigid-body parser, so malformed marker geometry cannot change head input.
    Marker indices are the order in the named set, not the global 'all' set.
    """
    try:
        message_id, size = struct.unpack_from("<HH", data)
        if message_id != NAT_FRAMEOFDATA or size + 4 > len(data):
            return None
        data = data[:size + 4]
        frame, count = struct.unpack_from("<ii", data, 4)
        if not 0 <= count <= 10000:
            return None
        offset, sets = 12, {}
        for _ in range(count):
            end = data.index(0, offset)
            name = data[offset:end].decode("utf-8")
            offset = end + 1
            n, = struct.unpack_from("<i", data, offset)
            offset += 4
            if not 0 <= n <= 10000 or offset + 12 * n > len(data) or name in sets:
                return None
            points = tuple(struct.unpack_from("<3f", data, offset + 12 * i) for i in range(n))
            offset += 12 * n
            if not all(np.isfinite(point).all() for point in points):
                return None
            sets[name] = points
        return frame, sets
    except (ValueError, IndexError, struct.error):
        return None


def parse_natnet4_frame(data: bytes):
    """Parse frame number and rigid bodies from a NatNet 4 FrameOfData.

    Returns ``(frame_number, [(id, position, quaternion, mean_error,
    tracked), ...])`` or ``None`` for malformed/non-frame packets. Only the
    prefix through rigid bodies is needed, keeping this safety input isolated
    from unrelated skeleton/force-plate payload changes.
    """
    try:
        message_id, payload_size = struct.unpack_from("<HH", data, 0)
        if message_id != NAT_FRAMEOFDATA or len(data) < payload_size + 4:
            return None
        off = 4
        frame_number, = struct.unpack_from("<i", data, off); off += 4
        marker_sets, = struct.unpack_from("<i", data, off); off += 4
        if marker_sets < 0 or marker_sets > 10000:
            return None
        for _ in range(marker_sets):
            end = data.index(0, off)
            off = end + 1
            count, = struct.unpack_from("<i", data, off); off += 4
            if count < 0:
                return None
            off += 12 * count
        unlabeled, = struct.unpack_from("<i", data, off); off += 4
        if unlabeled < 0:
            return None
        off += 12 * unlabeled
        body_count, = struct.unpack_from("<i", data, off); off += 4
        if body_count < 0 or body_count > 10000:
            return None
        bodies = []
        for _ in range(body_count):
            rb_id, = struct.unpack_from("<i", data, off); off += 4
            position = struct.unpack_from("<3f", data, off); off += 12
            rotation = struct.unpack_from("<4f", data, off); off += 16
            mean_error, = struct.unpack_from("<f", data, off); off += 4
            params, = struct.unpack_from("<h", data, off); off += 2
            bodies.append((rb_id, position, rotation, mean_error,
                           bool(params & 0x01)))
        return frame_number, bodies
    except (IndexError, ValueError, struct.error):
        return None


@dataclass(frozen=True)
class RigidBodySample:
    rigid_body_id: int
    position: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    source_time_s: float
    age_s: float
    mean_error_m: float | None


class RigidBodyMonitor:
    """Thread-safe latest-pose store for robot/head diagnostics and logs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._marker_frame = None
        self._poses: dict[
            int, tuple[np.ndarray, tuple[float, ...], float, float, float | None]
        ] = {}

    def update(self, rigid_body_id: int, position, rotation, source_time_s: float,
               wall_time: float, mean_error_m: float | None = None) -> None:
        p = np.asarray(position, dtype=float).reshape(3)
        q = tuple(float(v) for v in rotation)
        if (np.all(np.isfinite(p)) and len(q) == 4 and np.all(np.isfinite(q))
                and np.isfinite(source_time_s) and np.isfinite(wall_time)
                and (mean_error_m is None or np.isfinite(mean_error_m))):
            with self._lock:
                self._poses[int(rigid_body_id)] = (p.copy(), q, float(source_time_s),
                                                    float(wall_time),
                                                    (None if mean_error_m is None else
                                                     float(mean_error_m)))

    def update_marker_sets(self, sets, source_time_s, wall_time):
        with self._lock:
            self._marker_frame = (sets, source_time_s, wall_time)

    def marker_snapshot(self, now_s: float | None = None) -> dict:
        now = time.monotonic() if now_s is None else float(now_s)
        with self._lock:
            frame = self._marker_frame
        if frame is None:
            return {}
        sets, source_time, received = frame
        return {"frame": "optitrack", "units": "m", "source_time_s": source_time,
                "age_s": max(0.0, now - received),
                "sets": {name: [list(p) for p in points] for name, points in sets.items()}}

    def snapshot(self, now_s: float | None = None) -> dict[int, RigidBodySample]:
        now = time.monotonic() if now_s is None else float(now_s)
        with self._lock:
            values = list(self._poses.items())
        return {
            rb_id: RigidBodySample(rb_id, tuple(map(float, p)), q, source_t,
                                   max(0.0, now - wall_t), mean_error)
            for rb_id, (p, q, source_t, wall_t, mean_error) in values
        }


def _load_natnet_client(path: str):
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"NatNet client not found: {path}. Copy NatNetClient.py from the "
            "OptiTrack NatNet SDK Python samples or pass --natnet-client.")
    spec = importlib.util.spec_from_file_location("optitrack_natnet_client", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load NatNet client from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NatNetClient


class OptiTrackListener:
    """Official NatNet sample client -> primary head bridge + RB monitor."""

    def __init__(self, bridge, head_rigid_body_id: int, server_address: str,
                 client_address: str = "0.0.0.0", use_multicast: bool = True,
                 natnet_client_path: str = "vendor/NatNetClient.py",
                 monitor: RigidBodyMonitor | None = None,
                 client_factory=None) -> None:
        self.bridge = bridge
        self.head_id = int(head_rigid_body_id)
        self.monitor = monitor or RigidBodyMonitor()
        factory = client_factory or _load_natnet_client(natnet_client_path)
        self.client = factory()
        self._source_time = float("nan")
        self._configure(server_address, client_address, use_multicast)
        self.client.new_frame_listener = self._on_frame
        self.client.rigid_body_listener = self._on_rigid_body

    def _configure(self, server: str, client: str, multicast: bool) -> None:
        setters = (("set_server_address", server),
                   ("set_client_address", client),
                   ("set_use_multicast", multicast))
        for name, value in setters:
            fn = getattr(self.client, name, None)
            if fn is not None:
                fn(value)

    def _on_frame(self, frame: Any) -> None:
        # SDK sample versions pass either a dict or a frame object.
        if isinstance(frame, dict):
            value = frame.get("timestamp", frame.get("frameNumber"))
        else:
            value = getattr(frame, "timestamp", getattr(frame, "frame_number", None))
        if value is not None:
            self._source_time = float(value)

    def _on_rigid_body(self, rigid_body_id, position, rotation, *args) -> None:
        now = time.monotonic()
        rb_id = int(rigid_body_id)
        source_t = self._source_time if np.isfinite(self._source_time) else now
        # Some SDK revisions append a tracking-valid boolean to the callback.
        tracked = bool(args[0]) if args and isinstance(args[0], (bool, np.bool_)) else True
        if not tracked:
            return
        self.monitor.update(rb_id, position, rotation, source_t, now)
        if rb_id == self.head_id:
            self.bridge.on_sample(source_t, position, tracked=True, wall_time=now)

    def start(self) -> None:
        result = self.client.run()
        if result is False:
            raise RuntimeError("NatNet client failed to start; check Motive streaming/network settings")

    def stop(self) -> None:
        shutdown = getattr(self.client, "shutdown", None)
        if shutdown is not None:
            shutdown()


class NatNetV4Listener:
    """Dependency-free NatNet 4 multicast receiver for Motive 3.x/4.x."""

    def __init__(self, bridge, head_rigid_body_id: int,
                 local_address: str = "127.0.0.1", data_port: int = 1511,
                 multicast_address: str = NATNET_MULTICAST,
                 monitor: RigidBodyMonitor | None = None,
                 nominal_rate_hz: float = 120.0) -> None:
        self.bridge = bridge
        self.head_id = int(head_rigid_body_id)
        self.monitor = monitor or RigidBodyMonitor()
        self.nominal_rate_hz = float(nominal_rate_hz)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                   socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", int(data_port)))
        membership = (socket.inet_aton(multicast_address) +
                      socket.inet_aton(local_address))
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                              membership)
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._receive, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._sock.close()

    def _receive(self) -> None:
        while not self._stop.is_set():
            try:
                data, _address = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            parsed = parse_natnet4_frame(data)
            if parsed is None:
                continue
            frame_number, bodies = parsed
            now = time.monotonic()
            source_t = frame_number / self.nominal_rate_hz
            markers = parse_natnet4_marker_sets(data)
            # Replacing the whole frame also removes sets absent from this packet.
            self.monitor.update_marker_sets({} if markers is None else markers[1], source_t, now)
            for rb_id, position, rotation, mean_error, tracked in bodies:
                if not tracked:
                    continue
                self.monitor.update(
                    rb_id, position, rotation, source_t, now,
                    mean_error_m=mean_error)
                if rb_id == self.head_id:
                    self.bridge.on_sample(source_t, position, True, now)
