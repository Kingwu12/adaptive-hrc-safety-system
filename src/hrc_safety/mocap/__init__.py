"""Mocap integration: two transports, one bridge.

See docs/design/optitrack-bridge.md. Whichever tracker is feeding us, ONE
tracked point (Xsens pelvis segment, or a Motive rigid body = torso cluster)
reaches the same FeatureExtractor.push(t, position) entry point the simulator
feeds. Import the listener you want from .xsens_transport or .natnet_transport;
everything downstream is transport-blind on purpose.
"""
from .natnet_bridge import MocapBridge, TickSample, load_extrinsics
from .optitrack_transport import (NatNetV4Listener, OptiTrackListener,
                                  RigidBodyMonitor, RigidBodySample,
                                  parse_natnet4_frame)

__all__ = ["MocapBridge", "TickSample", "load_extrinsics",
           "OptiTrackListener", "RigidBodyMonitor", "RigidBodySample"]
__all__ += ["NatNetV4Listener", "parse_natnet4_frame"]
