from pathlib import Path

from scripts.research_readiness import audit


def test_repository_collection_gate_excludes_post_study_evidence():
    root = Path(__file__).resolve().parents[1]
    failures = dict(audit(root, stage="collection"))

    assert "end_to_end_stop_time" in failures
    assert "safety_rated_output" in failures
    assert "protected_geometry" in failures
    assert "untouched_final_evaluation" not in failures
    assert "reported_results_are_real" not in failures
    assert "model_has_final_test" not in failures


def test_repository_report_gate_requires_final_real_evidence():
    root = Path(__file__).resolve().parents[1]
    failures = dict(audit(root, stage="report"))

    assert "untouched_final_evaluation" in failures
    assert "reported_results_are_real" in failures
    assert "model_has_final_test" in failures
