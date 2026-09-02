#!/usr/bin/env python3
"""Fail closed unless a JSONL preflight contains complete Xsens body poses."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def audit_capture(path: Path, min_rows: int = 120,
                  min_segments: int = 23) -> tuple[list[str], dict]:
    failures: list[str] = []
    rows = 0
    counters: set[int] = set()
    time_codes: list[float] = []
    expected_ids = {str(i) for i in range(1, min_segments + 1)}

    for line_number, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        rows += 1
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            failures.append(f"line {line_number}: invalid JSON ({exc})")
            continue
        if record.get("schema_version") != 2:
            failures.append(f"line {line_number}: schema_version is not 2")
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
            counters.add(counter)
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

    if rows < min_rows:
        failures.append(f"only {rows} rows; require at least {min_rows}")
    if len(counters) < 2:
        failures.append("sample_counter did not advance")
    if len(time_codes) < 2 or max(time_codes) <= min(time_codes):
        failures.append("time_code_s did not advance")

    # Keep console output useful instead of repeating a cascade from every row.
    failures = list(dict.fromkeys(failures))
    return failures, {
        "rows": rows,
        "unique_sample_counters": len(counters),
        "time_span_s": (0.0 if len(time_codes) < 2 else
                        max(time_codes) - min(time_codes)),
        "required_segments": min_segments,
    }


def _finite_vector(value: object, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(isinstance(item, (int, float)) and math.isfinite(item)
                for item in value)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--min-rows", type=int, default=120)
    parser.add_argument("--min-segments", type=int, default=23)
    args = parser.parse_args()

    failures, summary = audit_capture(
        args.capture, min_rows=args.min_rows,
        min_segments=args.min_segments)
    if failures:
        print("XSENS CAPTURE FAIL")
        for failure in failures[:20]:
            print(f"  BLOCKED: {failure}")
        if len(failures) > 20:
            print(f"  ... {len(failures) - 20} additional failures")
        return 2
    print(
        "XSENS CAPTURE PASS: "
        f"{summary['rows']} rows, {summary['required_segments']} segments, "
        f"{summary['unique_sample_counters']} unique samples, "
        f"{summary['time_span_s']:.3f}s source-time span"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

