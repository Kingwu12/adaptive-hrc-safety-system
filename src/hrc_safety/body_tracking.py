"""Head-anchored Xsens body pose and features in OptiTrack/robot coordinates.

MXTP02 IDs are one-based: head 7, hands 11/15. Xsens quaternions are
wxyz; NatNet quaternions are xyzw. The configured helmet/head axis relationship
must describe the actual mounting. This is a tracked-pose proxy, not a body mesh.
"""
from __future__ import annotations

import copy
import math
import numpy as np
from scipy.spatial.transform import Rotation

BODY_FEATURES = (
    "mean_segment_speed_m_s", "max_segment_speed_m_s", "trunk_tilt_rad",
    "right_reach_m", "left_reach_m", "right_hand_height_m",
    "left_hand_height_m", "foot_separation_m",
)
SEGMENT_NAMES = ("pelvis", "L5", "L3", "T12", "T8", "neck", "head",
                 "right_shoulder", "right_upper_arm", "right_forearm", "right_hand",
                 "left_shoulder", "left_upper_arm", "left_forearm", "left_hand",
                 "right_upper_leg", "right_lower_leg", "right_foot", "right_toe",
                 "left_upper_leg", "left_lower_leg", "left_foot", "left_toe")


def rotation(q, *, wxyz=False):
    q = np.asarray(q, dtype=float)
    if q.shape != (4,) or not np.isfinite(q).all() or not .9 <= np.linalg.norm(q) <= 1.1:
        raise ValueError("Invalid tracking quaternion")
    return Rotation.from_quat(np.roll(q, -1) if wxyz else q).as_matrix()


def rigid_rotation(value):
    r = np.asarray(value, dtype=float)
    if (r.shape != (3, 3) or not np.isfinite(r).all()
            or not np.allclose(r.T @ r, np.eye(3), atol=1e-5)
            or not np.isclose(np.linalg.det(r), 1)):
        raise ValueError("Invalid helmet/head axis relationship")
    return r


class HelmetBodyTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.last_features = None
        self.last_velocity = None

    def update(self, frame, helmet, *, xsens_age_s, config, robot_transform, tcp):
        try:
            if not config or config.get("enabled") is not True:
                raise ValueError("Helmet-anchored body tracking is not enabled")
            if config.get("head_axes_confirmed") is not True:
                raise ValueError("Helmet/head axes are not confirmed")
            age = float(xsens_age_s)
            helmet_age = float(helmet["age_s"])
            if (not all(math.isfinite(v) and 0 <= v <= .15 for v in (age, helmet_age))
                    or abs(age - helmet_age) > .05):
                raise ValueError("Body sources are stale or more than 50 ms apart")
            segments = frame["segments"]
            p = np.asarray([segments[str(i)]["position_m"] for i in range(1, 24)], dtype=float)
            if p.shape != (23, 3) or not np.isfinite(p).all():
                raise ValueError("All 23 finite Xsens segments are required")
            qs = [rotation(segments[str(i)]["quaternion_wxyz"], wxyz=True) for i in range(1, 24)]
            helmet_r = rotation(helmet["rotation_xyzw"])
            # Mount maps anatomical head-local axes into helmet-local axes.
            mount = rigid_rotation(config["head_to_helmet_rotation"])
            offset = np.asarray(config["head_origin_in_helmet_m"], dtype=float)
            helmet_p = np.asarray(helmet["position"], dtype=float)
            if any(v.shape != (3,) or not np.isfinite(v).all() for v in (offset, helmet_p)):
                raise ValueError("Invalid helmet anchor position/offset")
            world_from_xsens = helmet_r @ mount @ qs[6].T
            anchor = helmet_p + helmet_r @ offset
            world = (p - p[6]) @ world_from_xsens.T + anchor
            r_robot, t_robot = robot_transform
            robot = world @ r_robot.T + t_robot
            source = (int(frame["sample_counter"]), float(helmet["source_time_s"]))
            source_t = float(frame["time_code_s"])
            if not math.isfinite(source_t) or not math.isfinite(source[1]):
                raise ValueError("Invalid body source clock")
            velocity = None
            if self.previous is not None:
                old_source, old_t, old_p = self.previous
                if any(a < b for a, b in zip(source, old_source)) or source_t < old_t:
                    raise ValueError("Body source clock reset; restart body observation")
                if all(a > b for a, b in zip(source, old_source)):
                    dt = source_t - old_t
                    if 0 < dt <= .15:
                        velocity = (robot - old_p) / dt
                    self.previous = (source, source_t, robot.copy())
                    self.last_features = None
                    self.last_velocity = velocity
            else:
                self.previous = (source, source_t, robot.copy())
            trunk = robot[6] - robot[0]
            length = float(np.linalg.norm(trunk))
            if length < .1 or length > 1.5:
                raise ValueError("Implausible head-to-pelvis geometry")
            features = {
                "trunk_tilt_rad": float(np.arccos(np.clip(trunk[2] / length, -1, 1))),
                "right_reach_m": float(np.linalg.norm(robot[10] - robot[7])),
                "left_reach_m": float(np.linalg.norm(robot[14] - robot[11])),
                "right_hand_height_m": float(robot[10, 2] - robot[0, 2]),
                "left_hand_height_m": float(robot[14, 2] - robot[0, 2]),
                "foot_separation_m": float(np.linalg.norm(robot[17] - robot[21])),
            }
            if velocity is not None:
                speeds = np.linalg.norm(velocity, axis=1)
                features.update(mean_segment_speed_m_s=float(speeds.mean()),
                                max_segment_speed_m_s=float(speeds.max()))
                self.last_features = features
            elif self.last_features is not None:
                features = self.last_features
            distances = None
            geometry = None
            if tcp is not None:
                nearest = np.tile(np.asarray(tcp, dtype=float), (23, 1))
                nearest[:, 2] = np.clip(robot[:, 2], 0, tcp[2])
                distances = np.linalg.norm(robot - nearest, axis=1)
                if self.last_velocity is not None:
                    toward = (nearest - robot) / np.maximum(distances[:, None], 1e-9)
                    closing = np.sum(toward * self.last_velocity, axis=1)
                    # Conservative aggregate: closest origin and fastest closing
                    # origin may be different. This is not a body/robot surface mesh.
                    geometry = {"d": float(distances.min()),
                                "v_proj": float(max(0, closing.max())),
                                "speed": float(np.linalg.norm(self.last_velocity, axis=1).max()),
                                "a_proj": 0.0, "source": "anchored_segment_origins"}
            return {
                "available": True, "source": "helmet_anchored_xsens_v1", "units": "m",
                "source_ids": list(source), "source_time_s": source_t,
                "source_skew_s": abs(age - helmet_age), "segment_count": 23,
                "anchor_position_optitrack_m": anchor.tolist(),
                "mount": copy.deepcopy(config), "features": features,
                "features_ready": all(k in features for k in BODY_FEATURES),
                "body_geometry": geometry,
                "minimum_segment_distance_m": None if distances is None else float(distances.min()),
                "nearest_segment": None if distances is None else SEGMENT_NAMES[int(distances.argmin())],
                "segments": {str(i + 1): {
                    "name": SEGMENT_NAMES[i], "position_optitrack_m": world[i].tolist(),
                    "position_robot_m": robot[i].tolist(),
                    "rotation_optitrack_xyzw": Rotation.from_matrix(world_from_xsens @ qs[i]).as_quat().tolist(),
                    "rotation_robot_xyzw": Rotation.from_matrix(r_robot @ world_from_xsens @ qs[i]).as_quat().tolist(),
                } for i in range(23)},
                "reason": "23 body segments anchored to the tracked helmet",
            }
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            self.reset()
            return {"available": False, "features_ready": False,
                    "reason": str(exc), "segments": {}, "features": {}}
