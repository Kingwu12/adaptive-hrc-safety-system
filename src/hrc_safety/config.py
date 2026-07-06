"""Configuration loading. The YAML file is the single source of every tunable."""

from __future__ import annotations

import os

import yaml

_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "configs",
    "default.yaml",
)


def load_config(path: str | None = None) -> dict:
    """Load the experiment config (defaults to configs/default.yaml)."""
    with open(path or _DEFAULT, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_zone_model(config: dict):
    """Construct a ZoneModel from the config's zones block."""
    from .zones import ZoneModel

    z = config["zones"]
    return ZoneModel(
        K=z["K"],
        T=z["T"],
        C=z["C"],
        Sa=z["Sa"],
        yellow_margin=z["yellow_margin"],
        hysteresis=z["hysteresis"],
    )
