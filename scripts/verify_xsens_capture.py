#!/usr/bin/env python3
"""Fail closed unless Xsens captures contain complete, usable body-pose data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 3
VALID_PHASES = {"unlabelled", "approaching", "working", "retreating"}
VALID_EVENTS = {"none", "hazard", "distractor"}
REQUIRED_PHASES = {"approaching", "working", "retreating"}
EXPECTED_PHASE_SEQUENCE = [
    "approaching", "working", "retreating",
    "approaching", "working", "retreating",
]


def audit_capture(path: Path, min_rows: int = 120, min_segments: int = 23,
                  require_trial: bool = False) -> tuple[list[str], dict]:
    """Audit one dashboard JSONL capture.

    A short disposable preflight proves packet completeness. ``require_trial``
    additionally proves that the file is a labelled guided run tied to a native
    MVN recording and one identifiable model artifact.
    """
    failures: list[str] = []
    rows = 0
    counters: list[int] = []
    time_codes: list[float] = []
    stale_rows = 0
    phase_counts: dict[str, int] = {}
    event_counts: dict[str, int] = {}
    phase_sequence: list[str] = []
    session_ids: set[str] = set()
    native_references: set[str] = set()
    model_hashes: set[str] = set()
    pelvis_positions: set[tuple[float, float, float]] = set()
    expected_ids = {str(i) for i in range(1, min_segments + 1)}

    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        return [f"cannot read capture ({exc})"], {"path": str(path), "rows": 0}

    for line_number, raw in enumerate(raw_lines, 1):
        if not raw.strip():
            continue
        rows += 1
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            failures.append(f"line {line_number}: invalid JSON ({exc})")
            continue
        if record.get("schema_version") != SCHEMA_VERSION:
            failures.append(
                f"line {line_number}: schema_version is not {SCHEMA_VERSION}")
            continue
        frame = record.get("xsens_frame")
        if not isinstance(frame, dict):
            failures.append(f"line {line_number}: missing xsens_frame")
            continue
        segments = frame.get("segments")
        if not isinstance(segments, dict):
            failures.append(f"line {line_number}: missing segments mapping")
            continue
        missing = expected_ids - set(segments)
        if missing:
            failures.append(
                f"line {line_number}: missing body segments "
                + ",".join(sorted(missing, key=int)))
            continue
        if int(frame.get("body_segment_count", 0)) < min_segments:
            failures.append(
                f"line {line_number}: declared body segment count below "
                f"{min_segments}")
        counter = frame.get("sample_counter")
        time_code = frame.get("time_code_s")
        if isinstance(counter, int):
            counters.append(counter)
        else:
            failures.append(f"line {line_number}: invalid sample_counter")
        if isinstance(time_code, (int, float)) and math.isfinite(time_code):
            time_codes.append(float(time_code))
        else:
            failures.append(f"line {line_number}: invalid time_code_s")

        for segment_id in expected_ids:
            item = segments[segment_id]
            position = item.get("position_m") if isinstance(item, dict) else None
            quaternion = (item.get("quaternion_wxyz")
                          if isinstance(item, dict) else None)
            if not _finite_vector(position, 3):
                failures.append(
                    f"line {line_number}: segment {segment_id} has invalid position")
                break
            if not _finite_vector(quaternion, 4):
                failures.append(
                    f"line {line_number}: segment {segment_id} has invalid quaternion")
                break
            norm = math.sqrt(sum(float(value) ** 2 for value in quaternion))
            if not 0.8 <= norm <= 1.2:
                failures.append(
                    f"line {line_number}: segment {segment_id} quaternion "
                    f"norm {norm:.3f} is implausible")
                break
        pelvis = segments.get("1", {}).get("position_m")
        if _finite_vector(pelvis, 3):
            pelvis_positions.add(tuple(round(float(value), 4) for value in pelvis))

        if not require_trial:
            continue
        session_id = str(record.get("session_id") or "").strip()
        native_reference = str(
            record.get("mvn_native_recording_reference") or "").strip()
        model_hash = str(record.get("model_sha256") or "").strip().lower()
        if session_id:
            session_ids.add(session_id)
        else:
            failures.append(f"line {line_number}: missing session_id")
        if record.get("mvn_native_recording_confirmed") is not True:
            failures.append(f"line {line_number}: native MVN recording not confirmed")
        if native_reference:
            native_references.add(native_reference)
        else:
            failures.append(f"line {line_number}: missing native MVN file reference")
        if re.fullmatch(r"[0-9a-f]{64}", model_hash):
            model_hashes.add(model_hash)
        else:
            failures.append(f"line {line_number}: invalid or synthetic model_sha256")

        phase = str(record.get("ground_truth_phase") or "")
        event = str(record.get("ground_truth_event") or "")
        if phase not in VALID_PHASES:
            failures.append(f"line {line_number}: invalid ground_truth_phase")
        else:
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            if phase != "unlabelled" and (not phase_sequence or phase != phase_sequence[-1]):
                phase_sequence.append(phase)
        if event not in VALID_EVENTS:
            failures.append(f"line {line_number}: invalid ground_truth_event")
        else:
            event_counts[event] = event_counts.get(event, 0) + 1
        if record.get("stale") is True:
            stale_rows += 1

    if rows < min_rows:
        failures.append(f"only {rows} rows; require at least {min_rows}")
    unique_counters = len(set(counters))
    if unique_counters < 2:
        failures.append("sample_counter did not advance")
    if len(time_codes) < 2 or max(time_codes) <= min(time_codes):
        failures.append("time_code_s did not advance")

    if require_trial:
        missing_phases = REQUIRED_PHASES - set(phase_counts)
        if missing_phases:
            failures.append(
                "missing labelled phases: " + ",".join(sorted(missing_phases)))
        if phase_sequence != EXPECTED_PHASE_SEQUENCE:
            failures.append(
                "phase sequence is not approach-work-retreat repeated twice")
        if event_counts.get("hazard", 0) == 0:
            failures.append("no labelled hazard event window")
        if len(session_ids) != 1:
            failures.append("capture does not contain exactly one session_id")
        if len(native_references) != 1:
            failures.append("capture does not contain exactly one native MVN file reference")
        if len(model_hashes) != 1:
            failures.append("capture does not contain exactly one real model digest")
        if rows and stale_rows / rows > 0.05:
            failures.append(
                f"OptiTrack stale rate {100 * stale_rows / rows:.2f}% exceeds 5%")
        if len(pelvis_positions) < 2:
            failures.append("Xsens pelvis pose did not change during the run")
        if unique_counters < max(2, int(rows * 0.50)):
            failures.append(
                f"only {unique_counters}/{rows} unique Xsens sample counters")

    failures = list(dict.fromkeys(failures))
    return failures, {
        "path": str(path),
        "rows": rows,
        "unique_sample_counters": unique_counters,
        "time_span_s": (0.0 if len(time_codes) < 2 else
                        max(time_codes) - min(time_codes)),
        "required_segments": min_segments,
        "stale_percent": 0.0 if not rows else 100 * stale_rows / rows,
        "phase_counts": phase_counts,
        "event_counts": event_counts,
        "phase_sequence": phase_sequence,
        "session_id": next(iter(session_ids), None) if len(session_ids) == 1 else None,
        "native_mvn_reference": (
            next(iter(native_references), None) if len(native_references) == 1 else None),
        "model_sha256": next(iter(model_hashes), None) if len(model_hashes) == 1 else None,
        "capture_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def audit_batch(paths: list[Path], min_captures: int = 10,
                min_rows: int = 120, min_segments: int = 23) -> tuple[list[str], list[dict]]:
    failures: list[str] = []
    summaries: list[dict] = []
    if len(paths) < min_captures:
        failures.append(f"only {len(paths)} captures; require at least {min_captures}")
    for path in paths:
        capture_failures, summary = audit_capture(
            path, min_rows=min_rows, min_segments=min_segments,
            require_trial=True)
        summaries.append(summary)
        failures.extend(f"{path.name}: {failure}" for failure in capture_failures)

    sessions = [item.get("session_id") for item in summaries if item.get("session_id")]
    native_refs = [item.get("native_mvn_reference") for item in summaries
                   if item.get("native_mvn_reference")]
    model_hashes = {item.get("model_sha256") for item in summaries
                    if item.get("model_sha256")}
    if len(sessions) != len(set(sessions)):
        failures.append("session_id is reused across capture files")
    if len(native_refs) != len(set(native_refs)):
        failures.append("native MVN file reference is reused across capture files")
    if len(model_hashes) > 1:
        failures.append("model digest changed inside the qualification batch")
    return list(dict.fromkeys(failures)), summaries


def _finite_vector(value: object, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(isinstance(item, (int, float)) and math.isfinite(item)
                for item in value)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path, nargs="+")
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--min-segments", type=int, default=23)
    parser.add_argument(
        "--trial-batch", action="store_true",
        help="require labelled trial metadata and batch-level consistency")
    parser.add_argument("--min-captures", type=int, default=10)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if args.trial_batch:
        failures, summaries = audit_batch(
            args.captures, min_captures=args.min_captures,
            min_rows=args.min_rows, min_segments=args.min_segments)
    else:
        summaries = []
        failures = []
        for path in args.captures:
            capture_failures, summary = audit_capture(
                path, min_rows=args.min_rows, min_segments=args.min_segments)
            summaries.append(summary)
            failures.extend(f"{path.name}: {failure}" for failure in capture_failures)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "result": "fail" if failures else "pass",
        "trial_batch": args.trial_batch,
        "minimum_captures": args.min_captures if args.trial_batch else None,
        "captures": summaries,
        "failures": failures,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if failures:
        print("XSENS CAPTURE FAIL")
        for failure in failures[:30]:
            print(f"  BLOCKED: {failure}")
        if len(failures) > 30:
            print(f"  ... {len(failures) - 30} additional failures")
        return 2
    total_rows = sum(int(item["rows"]) for item in summaries)
    print(
        "XSENS CAPTURE PASS: "
        f"{len(summaries)} file(s), {total_rows} rows, "
        f"{args.min_segments} complete body segments"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
