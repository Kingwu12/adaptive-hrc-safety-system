from pathlib import Path

from scripts.research_readiness import audit


def test_repository_fails_closed_until_physical_and_final_evidence_exists():
    root = Path(__file__).resolve().parents[1]
    failures = dict(audit(root))

    assert "end_to_end_stop_time" in failures
    assert "safety_rated_output" in failures
    assert "protected_geometry" in failures
    assert "reported_results_are_real" in failures
    assert "model_has_final_test" in failures
