"""Synthetic scenarios for the development-only distance worksheet."""
from pathlib import Path

import pytest
import yaml

from scripts.offline_distance_candidate import compare, load_candidate


SYNTHETIC = {
    "static_stop_m": 1.4,
    "static_warning_m": 1.8,
    "adaptive_min_m": 0.7,
    "end_to_end_stop_time_s": 0.4,
    "sensing_uncertainty_m": 0.1,
    "protected_geometry_margin_m": 0.2,
    "adaptive_speed_ramp_m": 0.4,
}


def test_unmeasured_worksheet_refuses_to_run():
    worksheet = Path(__file__).resolve().parents[1] / "configs" / "distance_candidate.yaml"
    with pytest.raises(ValueError, match="Measured candidate inputs missing"):
        load_candidate(worksheet)


def test_values_without_safeguard_measurement_evidence_are_refused(tmp_path):
    candidate = tmp_path / "candidate.yaml"
    candidate.write_text(yaml.safe_dump({"status": "development_only", **SYNTHETIC,
                                         "evidence": {"stop_time": "synthetic-only"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="safeguard evidence"):
        load_candidate(candidate)


def test_stationary_person_can_move_in_fixed_stop_band_in_offline_scenario():
    outcome = compare(SYNTHETIC, distance_m=1.2, closing_m_s=0)
    assert outcome["fixed"] == 0
    assert outcome["reactive"] == 1
    assert outcome["predictive"] == 1
    assert outcome["adaptive_stop_m"] == SYNTHETIC["adaptive_min_m"]


def test_fast_closing_person_stops_adaptive_controller_at_same_distance():
    outcome = compare(SYNTHETIC, distance_m=1.2, closing_m_s=3)
    assert outcome["fixed"] == 0
    assert outcome["reactive"] == 0
    assert outcome["predictive"] == 0
    assert outcome["adaptive_stop_m"] == pytest.approx(1.5)


def test_predictive_phase_cap_cannot_override_reactive_stop():
    moving = compare(SYNTHETIC, distance_m=1.2, closing_m_s=1, phase_cap=.3)
    assert moving["predictive"] <= moving["reactive"]
    stopped = compare(SYNTHETIC, distance_m=.6, closing_m_s=0, phase_cap=1)
    assert stopped["predictive"] == stopped["reactive"] == 0
