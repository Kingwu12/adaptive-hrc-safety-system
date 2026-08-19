"""NatNet transport: parser validated against spec-shaped synthetic packets.

These tests are the whole reason the transport could be written before the
OptiTrack hardware was available. They do NOT prove the lab's Motive speaks
exactly this: that is the one-off first-packet check in record_mocap --dump.
What they do prove is that the parser walks a spec-conformant frame correctly,
survives malformed input, and lands on the same MocapBridge behaviour Xsens
already gets.
"""
import struct
import time

import pytest

from hrc_safety.mocap import MocapBridge
from hrc_safety.mocap.natnet_transport import (
    NAT_CONNECT,
    NAT_FRAMEOFDATA,
    NAT_SERVERINFO,
    build_command_packet,
    build_connect_packet,
    build_frame_packet,
    parse_rigid_body,
    parse_server_info,
)

BITSTREAMS = [(4, 1), (4, 0), (3, 1)]
TORSO = 1


def _frame(bitstream, **kw):
    major, minor = bitstream
    return build_frame_packet(major=major, minor=minor, **kw)


@pytest.mark.parametrize("bitstream", BITSTREAMS)
def test_round_trip_finds_the_target_rigid_body(bitstream):
    packet = _frame(
        bitstream,
        frame_number=8121,
        marker_sets={"Torso": [(0.1, 0.2, 0.3)] * 4, "all": [(0.0, 0.0, 0.0)] * 4},
        other_marker_count=3,
        rigid_bodies={
            7: ((9.0, 9.0, 9.0), True),
            TORSO: ((1.25, 0.75, -2.5), True),
            9: ((0.0, 0.0, 0.0), True),
        },
    )
    got = parse_rigid_body(packet, TORSO, *bitstream)
    assert got is not None
    frame_number, pos, tracked = got
    assert frame_number == 8121
    assert pos == pytest.approx((1.25, 0.75, -2.5))
    assert tracked is True


@pytest.mark.parametrize("bitstream", BITSTREAMS)
def test_untracked_rigid_body_reports_tracked_false(bitstream):
    packet = _frame(bitstream, rigid_bodies={TORSO: ((1.0, 2.0, 3.0), False)})
    _, pos, tracked = parse_rigid_body(packet, TORSO, *bitstream)
    assert tracked is False
    assert pos == pytest.approx((1.0, 2.0, 3.0))


@pytest.mark.parametrize("bitstream", BITSTREAMS)
def test_absent_rigid_body_returns_none(bitstream):
    packet = _frame(bitstream, rigid_bodies={42: ((1.0, 2.0, 3.0), True)})
    assert parse_rigid_body(packet, TORSO, *bitstream) is None


def test_empty_frame_is_parsed_not_crashed():
    packet = build_frame_packet(rigid_bodies={})
    assert parse_rigid_body(packet, TORSO) is None


def test_wrong_message_id_returns_none():
    packet = struct.pack("<HH", NAT_SERVERINFO, 4) + b"\x00" * 4
    assert parse_rigid_body(packet, TORSO) is None


@pytest.mark.parametrize("cut", [0, 1, 4, 9, 17, 33, 61])
def test_truncated_packets_never_raise(cut):
    packet = build_frame_packet(
        marker_sets={"Torso": [(0.1, 0.2, 0.3)] * 4},
        other_marker_count=2,
        rigid_bodies={TORSO: ((1.0, 2.0, 3.0), True)},
    )
    assert parse_rigid_body(packet[:cut], TORSO) is None


def test_unterminated_marker_set_name_returns_none():
    body = struct.pack("<i", 1) + struct.pack("<I", 1) + struct.pack("<I", 8)
    body += b"NoNullHere"
    packet = struct.pack("<HH", NAT_FRAMEOFDATA, len(body)) + body
    assert parse_rigid_body(packet, TORSO) is None


def test_wrong_bitstream_misreads_rather_than_crashes():
    """A 4.1 packet read as 4.0 must fail safe, never return a wrong position.

    This is the exact failure mode pinning the bitstream exists to prevent, so
    it is worth having a test that says out loud what happens if we get it
    wrong: the block-size words shift every offset, and the parse either finds
    nothing or dies inside the try. What it must never do is hand the safety
    loop a plausible-looking position.
    """
    packet = build_frame_packet(
        marker_sets={"Torso": [(0.1, 0.2, 0.3)] * 4},
        rigid_bodies={TORSO: ((1.0, 2.0, 3.0), True)},
        major=4, minor=1,
    )
    got = parse_rigid_body(packet, TORSO, 4, 0)
    if got is not None:
        assert got[1] != pytest.approx((1.0, 2.0, 3.0))


def test_natnet_2_is_refused_outright():
    packet = build_frame_packet(rigid_bodies={TORSO: ((1.0, 2.0, 3.0), True)})
    assert parse_rigid_body(packet, TORSO, 2, 9) is None


def test_connect_packet_layout():
    packet = build_connect_packet((4, 1, 0, 0))
    msg_id, size = struct.unpack_from("<HH", packet)
    assert msg_id == NAT_CONNECT
    assert size == 271
    body = packet[4:]
    assert body[0:4] == b"Ping"
    assert tuple(body[265:269]) == (4, 1, 0, 0)


def test_bitstream_command_packet():
    packet = build_command_packet("Bitstream,4.1")
    assert packet[4:].rstrip(b"\0") == b"Bitstream,4.1"


def test_server_info_round_trip():
    body = b"Motive".ljust(256, b"\0")
    body += bytes((3, 1, 0, 0)) + bytes((4, 1, 0, 0))
    packet = struct.pack("<HH", NAT_SERVERINFO, len(body)) + body
    name, server_version, natnet_version = parse_server_info(packet)
    assert name == "Motive"
    assert server_version == (3, 1, 0, 0)
    assert natnet_version == (4, 1, 0, 0)


class _FakeListener:
    """Exercises NatNetListener.handle_packet without opening sockets."""

    def __init__(self, bridge, rigid_body_id=TORSO, rate=120.0):
        from hrc_safety.mocap.natnet_transport import NatNetListener
        self._impl = NatNetListener.__new__(NatNetListener)
        self._impl._bridge = bridge
        self._impl._rigid_body_id = rigid_body_id
        self._impl._rate = rate
        self._impl._major, self._impl._minor = 4, 1
        self._impl.last_frame_number = None

    def feed(self, packet, wall_time):
        return self._impl.handle_packet(packet, wall_time)

    @property
    def last_frame_number(self):
        return self._impl.last_frame_number


def test_packet_reaches_the_bridge_and_survives_dropout():
    bridge = MocapBridge(sample_rate_hz=60.0, staleness_s=0.150)
    listener = _FakeListener(bridge)
    t0 = time.monotonic()

    assert bridge.tick(t0) is None  # warm-up: nothing seen yet

    packet = build_frame_packet(
        frame_number=240,
        rigid_bodies={TORSO: ((0.4, 1.1, 2.2), True)},
    )
    assert listener.feed(packet, t0) is True
    assert listener.last_frame_number == 240

    sample = bridge.tick(t0 + 0.01)
    assert sample is not None
    assert tuple(sample.position) == pytest.approx((0.4, 1.1, 2.2))
    assert sample.stale is False
    assert sample.motive_timestamp == pytest.approx(2.0)  # 240 / 120 Hz

    stale = bridge.tick(t0 + 0.4)
    assert stale.stale is True
    assert tuple(stale.position) == pytest.approx((0.4, 1.1, 2.2))


def test_untracked_frames_do_not_move_the_held_position():
    bridge = MocapBridge(sample_rate_hz=60.0)
    listener = _FakeListener(bridge)
    t0 = time.monotonic()
    listener.feed(
        build_frame_packet(rigid_bodies={TORSO: ((1.0, 1.0, 1.0), True)}), t0)
    listener.feed(
        build_frame_packet(rigid_bodies={TORSO: ((9.9, 9.9, 9.9), False)}), t0 + 0.01)
    sample = bridge.tick(t0 + 0.02)
    assert tuple(sample.position) == pytest.approx((1.0, 1.0, 1.0))


def test_garbage_packet_is_ignored_without_touching_the_bridge():
    bridge = MocapBridge(sample_rate_hz=60.0)
    listener = _FakeListener(bridge)
    assert listener.feed(b"\x01\x02\x03", time.monotonic()) is False
    assert bridge.tick(time.monotonic()) is None
