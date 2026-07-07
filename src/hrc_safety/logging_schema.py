"""Decision-record schema and JSONL logger.

Both controllers emit the IDENTICAL DecisionRecord every tick. Full traceability of
every command back to the observation, zone, posterior, prediction and rule that
produced it is a core paper requirement, and using one schema for both conditions
is what makes the static-vs-adaptive comparison auditable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Command(str, Enum):
    """Physical command issued to the robot."""

    FULL_SPEED = "full_speed"
    REDUCED_SPEED = "reduced_speed"
    PROTECTIVE_STOP = "protective_stop"


@dataclass
class DecisionRecord:
    """One tick of controller decision, fully traceable.

    The sem-2 fields (envelope_max_speed, risk, time_to_breach_s) default so the
    fixed-zone baseline -- which carries no envelope or horizon -- still emits the
    identical schema. They make the runtime-assurance floor and the anticipation
    signal auditable per tick, which is the whole point of the redesign.
    """

    t: float
    condition: str  # "static"/"fixed_zone" | "dynamic_ssm" | "adaptive"
    d: float
    zone: str
    state_posterior: list[float]
    predicted_posterior: list[float]
    p_hazard_next: float
    inferred_state: str
    rule: str
    command: str
    speed_fraction: float
    # --- sem-2 traceability (optional; baseline leaves them at defaults) --------
    envelope_max_speed: float = 1.0  # certified speed floor permitted this tick
    risk: float = 0.0                # fused hazard risk (posterior + breach imminence)
    time_to_breach_s: float | None = None  # predicted s until red-radius breach (None = n/a)

    def to_json(self) -> str:
        return json.dumps(self._serialisable())

    def _serialisable(self) -> dict[str, Any]:
        d = asdict(self)
        # Enum instances (if a Command slipped in) -> value.
        if isinstance(d.get("command"), Enum):
            d["command"] = d["command"].value
        return d


@dataclass
class JsonlLogger:
    """Append DecisionRecords to a JSON Lines file (one record per line)."""

    path: str
    _records: list[DecisionRecord] = field(default_factory=list)

    def log(self, record: DecisionRecord) -> None:
        self._records.append(record)

    @property
    def records(self) -> list[DecisionRecord]:
        return self._records

    def flush(self) -> None:
        import os

        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            for rec in self._records:
                fh.write(rec.to_json() + "\n")
