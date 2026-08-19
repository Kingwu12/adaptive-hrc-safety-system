"""OptiTrack Motive NatNet stream -> MocapBridge.

Second transport behind the SAME boundary as `xsens_transport.py`: both end at
`MocapBridge.on_sample(motive_ts, pos_xyz, tracked, wall_time)`, so nothing
downstream (FeatureExtractor, envelope, controllers) knows or cares which
tracker fed it. That is the whole point of the seam.

WHY A HAND-ROLLED PARSER
Motive's NatNet SDK ships Windows and Linux binaries only; there is no macOS
build and no maintained PyPI client. OptiTrack's own documented fallback for
unsupported platforms is direct depacketization of the raw bitstream, using
their PacketClient / PythonClient samples as the authoritative syntax. This
module is that, cut down to the one asset this study needs.

SCOPE - we parse ONLY as far as the rigid-body block:
    frame prefix -> marker sets -> legacy other markers -> rigid bodies
Everything after it (skeletons, assets, labelled markers, force plates,
devices, frame suffix) is skipped entirely. Every extra block is another place
the bitstream can shift under us on a Motive upgrade, and the study tracks ONE
rigid body (torso cluster), position only.

BITSTREAM VERSION IS PINNED, NOT DISCOVERED
OptiTrack lets a unicast client request a bitstream version, and guarantees
future Motive versions still emit it. We request it and refuse to guess: a
version we have not been told about is a parse we do not trust. Pinning only
works on UNICAST - multicast always emits the installed Motive's own version.
That is a second reason this transport is unicast.

FRAME CONVENTION
Motive streams metres. Do NOT hand-convert Y-up to Z-up here. The mocap ->
robot-base transform in `calibrate_mocap.py` (Kabsch on touched floor points)
is solved from real correspondences, so it absorbs any axis convention for
free. A hand-conversion on top of it would double-apply the rotation.

TIME
We stop parsing before the frame suffix, so Motive's own timestamp is out of
reach by design. `frame_number` is the exact Motive-side identity and is what
offline logs join on; `motive_ts` is reported as frame_number / stream_rate_hz
so the field keeps its seconds meaning. Staleness never depends on this - the
bridge uses the local wall clock for that.

VERIFY-ON-LAB NOTE
Same standing rule as the Xsens parser: this is validated here against packets
built to the documented spec. The FIRST real packet out of the lab's Motive
must be checked once with `scripts/record_mocap.py --dump` before any trial
data is collected on it.
"""
from __future__ import annotations

import socket
import struct
import threading
import time

# Message IDs (NatNet command protocol).
NAT_CONNECT = 0
NAT_SERVERINFO = 1
NAT_REQUEST = 2
NAT_RESPONSE = 3
NAT_FRAMEOFDATA = 7
NAT_KEEPALIVE = 10

DEFAULT_COMMAND_PORT = 1510
DEFAULT_DATA_PORT = 1511

# The version we ask Motive to speak. 4.1 is the first with per-block byte
# counts; see _has_block_sizes.
PINNED_BITSTREAM = (4, 1)

_HEADER = struct.Struct("<HH")      # message id, payload size
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")
_VEC3 = struct.Struct("<fff")
_QUAT = struct.Struct("<ffff")
_F32 = struct.Struct("<f")
_I16 = struct.Struct("<h")
# id + position + quaternion + mean marker error + tracking param
_RIGID_BODY = struct.Struct("<i fff ffff f h".replace(" ", ""))


def _has_block_sizes(major: int, minor: int) -> bool:
    """NatNet 4.1+ prefixes each asset block with a byte count."""
    return (major == 4 and minor > 0) or major > 4


class NatNetParseError(ValueError):
    """Raised only by the strict helpers; the listener path never raises."""


def build_connect_packet(version: tuple[int, int, int, int] = (4, 1, 0, 0)) -> bytes:
    """The NAT_CONNECT ('Ping') packet, with the requested bitstream version.

    Layout is fixed by the SDK samples: a 270-byte body whose first four bytes
    spell 'Ping' and whose bytes 265..268 carry the requested version.
    """
    body = bytearray(270)
    body[0:4] = b"Ping"
    body[265] = version[0]
    body[266] = version[1]
    body[267] = version[2]
    body[268] = version[3]
    return _HEADER.pack(NAT_CONNECT, len(body) + 1) + bytes(body) + b"\0"


def build_command_packet(command: str) -> bytes:
    """A NAT_REQUEST text command, e.g. 'Bitstream,4.1'."""
    payload = command.encode("utf-8")
    return _HEADER.pack(NAT_REQUEST, len(payload) + 1) + payload + b"\0"


def parse_server_info(packet: bytes):
    """Return (application_name, server_version, natnet_version) or None."""
    if len(packet) < _HEADER.size:
        return None
    msg_id, _size = _HEADER.unpack_from(packet)
    if msg_id != NAT_SERVERINFO:
        return None
    body = packet[_HEADER.size:]
    if len(body) < 264:
        return None
    name = bytes(body[:256]).partition(b"\0")[0].decode("utf-8", "replace")
    server_version = struct.unpack_from("BBBB", body, 256)
    natnet_version = struct.unpack_from("BBBB", body, 260)
    return name, server_version, natnet_version


def _skip_named_marker_sets(data: memoryview, off: int, major: int, minor: int) -> int:
    count = _U32.unpack_from(data, off)[0]
    off += 4
    if _has_block_sizes(major, minor):
        off += 4
    for _ in range(count):
        end = bytes(data[off:]).find(b"\0")
        if end < 0:
            raise NatNetParseError("unterminated marker set name")
        off += end + 1
        n_markers = _U32.unpack_from(data, off)[0]
        off += 4 + 12 * n_markers
    return off


def _skip_legacy_other_markers(data: memoryview, off: int, major: int, minor: int) -> int:
    count = _U32.unpack_from(data, off)[0]
    off += 4
    if _has_block_sizes(major, minor):
        off += 4
    return off + 12 * count


def parse_rigid_body(
    packet: bytes,
    rigid_body_id: int,
    major: int = PINNED_BITSTREAM[0],
    minor: int = PINNED_BITSTREAM[1],
):
    """Return (frame_number, (x, y, z), tracking_valid) for one rigid body.

    Returns None when the packet is not a frame of data, is truncated or
    malformed, or does not carry `rigid_body_id`. It never raises: one bad
    datagram must not take the safety loop down with it.

    Only NatNet >= 3 is supported. Before 3.0 the per-rigid-body marker arrays
    were inline in the frame, and no lab running OptiTrack today streams that.
    """
    if major < 3:
        return None
    if len(packet) < _HEADER.size:
        return None
    try:
        msg_id, _size = _HEADER.unpack_from(packet)
        if msg_id != NAT_FRAMEOFDATA:
            return None
        data = memoryview(packet)
        off = _HEADER.size
        frame_number = _I32.unpack_from(data, off)[0]
        off += 4
        off = _skip_named_marker_sets(data, off, major, minor)
        off = _skip_legacy_other_markers(data, off, major, minor)

        count = _U32.unpack_from(data, off)[0]
        off += 4
        if _has_block_sizes(major, minor):
            off += 4
        for _ in range(count):
            rb_id, x, y, z, _q0, _q1, _q2, _q3, _err, param = \
                _RIGID_BODY.unpack_from(data, off)
            off += _RIGID_BODY.size
            if rb_id == rigid_body_id:
                return frame_number, (x, y, z), bool(param & 0x01)
        return None
    except (struct.error, IndexError, NatNetParseError):
        return None


def build_frame_packet(
    rigid_bodies,
    frame_number: int = 0,
    marker_sets=None,
    other_marker_count: int = 0,
    major: int = PINNED_BITSTREAM[0],
    minor: int = PINNED_BITSTREAM[1],
) -> bytes:
    """Build a spec-conformant NAT_FRAMEOFDATA packet (tests + fake feeds).

    `rigid_bodies` maps id -> ((x, y, z), tracking_valid). `marker_sets` maps
    name -> list of (x, y, z); these exist purely so the skip logic is exercised
    on packets shaped like Motive's, not on an empty best case.
    """
    marker_sets = marker_sets or {}
    body = bytearray()
    body += _I32.pack(frame_number)

    block = bytearray()
    for name, markers in marker_sets.items():
        block += name.encode("utf-8") + b"\0"
        block += _U32.pack(len(markers))
        for m in markers:
            block += _VEC3.pack(*m)
    body += _U32.pack(len(marker_sets))
    if _has_block_sizes(major, minor):
        body += _U32.pack(len(block))
    body += block

    block = bytearray()
    for i in range(other_marker_count):
        block += _VEC3.pack(float(i), float(i), float(i))
    body += _U32.pack(other_marker_count)
    if _has_block_sizes(major, minor):
        body += _U32.pack(len(block))
    body += block

    block = bytearray()
    for rb_id, (pos, tracked) in rigid_bodies.items():
        block += _RIGID_BODY.pack(
            rb_id, pos[0], pos[1], pos[2], 0.0, 0.0, 0.0, 1.0,
            0.001, 1 if tracked else 0)
    body += _U32.pack(len(rigid_bodies))
    if _has_block_sizes(major, minor):
        body += _U32.pack(len(block))
    body += block

    return _HEADER.pack(NAT_FRAMEOFDATA, len(body)) + bytes(body)


class NatNetListener:
    """Unicast NatNet client: Motive frames -> bridge.on_sample(...).

    Motive setup (Data Streaming pane): Broadcast Frame Data on, Rigid Bodies
    on, Transmission Type UNICAST, and the local interface set to the private
    subnet the robot and the safety host share.

    Drop-out is NOT handled here. Untracked rigid bodies are forwarded with
    tracked=False and the bridge's hold-last-position plus staleness flag does
    the rest, exactly as with Xsens. One policy, one place.
    """

    def __init__(
        self,
        bridge,
        server_ip: str,
        rigid_body_id: int = 1,
        local_ip: str = "0.0.0.0",
        command_port: int = DEFAULT_COMMAND_PORT,
        data_port: int = DEFAULT_DATA_PORT,
        stream_rate_hz: float = 120.0,
        bitstream: tuple[int, int] = PINNED_BITSTREAM,
    ) -> None:
        self._bridge = bridge
        self._server = (server_ip, command_port)
        self._rigid_body_id = int(rigid_body_id)
        self._rate = float(stream_rate_hz)
        self._major, self._minor = bitstream
        self.last_frame_number: int | None = None
        self.server_info = None

        self._data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._data_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._data_sock.bind((local_ip, data_port))
        self._data_sock.settimeout(0.5)

        self._cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._cmd_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._cmd_sock.bind((local_ip, 0))
        self._cmd_sock.settimeout(0.5)

        self._stop = threading.Event()
        self._rx = threading.Thread(target=self._rx_loop, daemon=True)
        self._ka = threading.Thread(target=self._keepalive_loop, daemon=True)

    def connect(self, timeout_s: float = 2.0) -> bool:
        """Send NAT_CONNECT, pin the bitstream, and read back server info.

        Returns True if Motive answered. False means no reply in `timeout_s`;
        the caller should treat that as "no tracker" and refuse to start a
        trial rather than run blind.
        """
        self._cmd_sock.sendto(
            build_connect_packet((self._major, self._minor, 0, 0)), self._server)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                packet, _addr = self._cmd_sock.recvfrom(4096)
            except socket.timeout:
                continue
            info = parse_server_info(packet)
            if info is not None:
                self.server_info = info
                self._cmd_sock.sendto(
                    build_command_packet(
                        "Bitstream,%d.%d" % (self._major, self._minor)),
                    self._server)
                return True
        return False

    def start(self) -> None:
        self._rx.start()
        self._ka.start()

    def stop(self) -> None:
        self._stop.set()
        self._rx.join(timeout=2.0)
        self._ka.join(timeout=2.0)
        self._data_sock.close()
        self._cmd_sock.close()

    def handle_packet(self, packet: bytes, wall_time: float) -> bool:
        """Parse one datagram and push it. Returns True if a sample was pushed."""
        parsed = parse_rigid_body(
            packet, self._rigid_body_id, self._major, self._minor)
        if parsed is None:
            return False
        frame_number, pos, tracked = parsed
        self.last_frame_number = frame_number
        self._bridge.on_sample(
            frame_number / self._rate, pos, tracked=tracked, wall_time=wall_time)
        return True

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                packet, _addr = self._data_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_packet(packet, time.monotonic())

    def _keepalive_loop(self) -> None:
        """Unicast streams stop if the client goes quiet."""
        while not self._stop.wait(1.0):
            try:
                self._cmd_sock.sendto(
                    _HEADER.pack(NAT_KEEPALIVE, 0) + b"\0", self._server)
            except OSError:
                break
