"""OptiTrack (NatNet) mocap integration.

See docs/design/optitrack-bridge.md. One rigid body (torso cluster) -> the
same FeatureExtractor.push(t, position) entry point the simulator feeds.
"""
from .natnet_bridge import MocapBridge, TickSample, load_extrinsics

__all__ = ["MocapBridge", "TickSample", "load_extrinsics"]
