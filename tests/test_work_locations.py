import pytest

from hrc_safety.work_locations import WorkLocationVisits


# Synthetic coordinates, not the lab geometry.
POINTS = [(0, 0, 1.6), (1, 0, 1.6), (1, 1, 1.6), (0, 1, 1.6)]


def dwell(detector, point, start):
    return [detector.observe(start + i * 0.125, point) for i in range(17)]


def test_four_distinct_dwells_in_either_order_are_visits_not_fastening():
    detector = WorkLocationVisits(POINTS)
    for j, i in enumerate([2, 1, 0, 3]):
        events = dwell(detector, POINTS[i], j * 3)
        assert [e for e in events if e is not None] == [i]
    assert detector.status()["all_locations_visited"]
    assert detector.status()["fastening_verified"] is False
    assert all(e is None for e in dwell(detector, POINTS[0], 15))
    detector.reset()
    assert detector.status()["visited_count"] == 0


def test_walking_past_or_revisiting_one_corner_does_not_complete_route():
    detector = WorkLocationVisits(POINTS)
    for i in range(4):
        detector.observe(i * 0.125, POINTS[i])
    assert detector.status()["visited_count"] == 0
    dwell(detector, POINTS[0], 1)
    dwell(detector, POINTS[0], 4)
    assert detector.status()["visited_count"] == 1


@pytest.mark.parametrize("break_kind", ["gap", "tracking", "nan", "missing", "outside", "inactive", "duplicate", "backward"])
def test_interrupted_dwell_cannot_count(break_kind):
    detector = WorkLocationVisits(POINTS)
    for i in range(9):
        detector.observe(i * 0.125, POINTS[0])
    if break_kind == "gap":
        detector.observe(1.5, POINTS[0])
    else:
        detector.observe(1 if break_kind == "duplicate" else 0.5 if break_kind == "backward" else 1.125,
                         None if break_kind == "missing" else
                         [float("nan"), 0, 0] if break_kind == "nan" else
                         [5, 5, 5] if break_kind == "outside" else POINTS[0],
                         tracked=break_kind != "tracking", task_active=break_kind != "inactive")
    for i in range(9):
        detector.observe(1.625 + i * 0.125, POINTS[0])
    assert detector.status()["visited_count"] == 0


@pytest.mark.parametrize("locations,kwargs", [
    (POINTS[:3], {}), (POINTS[:3] + [POINTS[0]], {}),
    (POINTS, {"radius_m": 0.6}), (POINTS, {"dwell_s": -1}),
    (POINTS, {"max_gap_s": float("nan")}),
])
def test_invalid_or_ambiguous_geometry_is_rejected(locations, kwargs):
    with pytest.raises(ValueError):
        WorkLocationVisits(locations, **kwargs)
