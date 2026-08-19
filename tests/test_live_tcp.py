"""Regression tests for the P0 live-TCP bug (found 2026-08-17, fixed 2026-08-19).

THE BUG: FeatureExtractor was built once from configs' static scenario.tcp_position
and never updated, while scripts/live_run.py drove a real arm through a full panel
cycle. Separation was therefore measured to a stationary phantom robot. Every
safety number the study reports -- minimum separation, protective stop timing,
predictor lead time -- was wrong on real hardware, and no test caught it because
every test held the TCP still.

These tests exist to make a stationary-TCP regression fail loudly.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hrc_safety.features import FeatureExtractor, nearest_column_point  # noqa: E402
from hrc_safety.logging_schema import Command  # noqa: E402
from hrc_safety.robot import MockRobot  # noqa: E402


def _extractor(tcp):
    return FeatureExtractor(tcp, sample_rate_hz=60.0, velocity_window=5, accel_window=3)


def test_moving_tcp_changes_separation():
    """The headline test. Operator stands still; only the robot moves."""
    operator = [2.0, 0.0, 1.0]
    fx = _extractor([0.0, 0.0, 2.2])

    fx.push(0.0, operator)
    near_frame = fx.push(1 / 60.0, operator)
    assert near_frame is not None
    d_before = near_frame.d

    # Arm travels 1.5 m away in x. Nothing about the human changed.
    fx.set_tcp([1.5, 0.0, 2.2])
    after = fx.push(2 / 60.0, operator)
    assert after is not None

    assert after.d != pytest.approx(d_before), (
        "separation did not respond to the robot moving -- the extractor is "
        "still measuring to a phantom TCP"
    )
    assert after.d < d_before, "robot moved toward the operator; d should shrink"


def test_column_model_uses_live_tcp_xy():
    """Separation is to the occupied COLUMN, so the TCP's x,y is what matters."""
    p = np.array([1.0, 0.0, 1.2])
    near_a = nearest_column_point(p, np.array([0.0, 0.0, 2.2]))
    near_b = nearest_column_point(p, np.array([0.8, 0.0, 2.2]))
    assert np.linalg.norm(near_a - p) > np.linalg.norm(near_b - p)


def test_stationary_tcp_is_the_regression_signature():
    """If someone reverts set_tcp, this is what the wrong answer looks like."""
    operator = [2.0, 0.0, 1.0]
    fx = _extractor([0.0, 0.0, 2.2])
    fx.push(0.0, operator)
    first = fx.push(1 / 60.0, operator)
    second = fx.push(2 / 60.0, operator)  # no set_tcp call
    assert first is not None and second is not None
    assert second.d == pytest.approx(first.d), (
        "sanity: with a genuinely static robot and static operator, d is flat"
    )


def test_mock_robot_reports_scripted_tcp():
    """MockRobot must satisfy the same actual_tcp() contract as URRobot."""
    r = MockRobot()
    assert r.actual_tcp() is None, "no pose scripted -> None, never a default"

    r = MockRobot(tcp=[0.1, 0.2, 2.2])
    assert r.actual_tcp() == [0.1, 0.2, 2.2]
    r.tcp = [0.3, 0.2, 1.4]
    assert r.actual_tcp() == [0.3, 0.2, 1.4]


def test_none_pose_is_not_silently_defaulted():
    """actual_tcp() returning None must stay None, so callers can stop the cell."""
    r = MockRobot(tcp=[0.0, 0.0, 2.2])
    r.tcp = None
    assert r.actual_tcp() is None


def test_full_cycle_sweep_moves_separation_monotonically():
    """Panel cycle sweep: TCP rises and travels; operator fixed under the path."""
    operator = [1.2, 0.0, 1.0]
    fx = _extractor([0.0, 0.0, 0.5])
    fx.push(0.0, operator)

    distances = []
    for k in range(1, 40):
        x = 0.0 + (1.2 - 0.0) * (k / 39.0)   # arm travels toward the operator
        z = 0.5 + (2.2 - 0.5) * (k / 39.0)   # and rises to ceiling height
        fx.set_tcp([x, 0.0, z])
        frame = fx.push(k / 60.0, operator)
        if frame is not None:
            distances.append(frame.d)

    assert len(distances) > 10
    assert distances[-1] < distances[0], "arm closed on the operator; d must fall"
    assert min(distances) < 0.2, "arm ends effectively on top of the operator"
