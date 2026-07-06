"""Layered HMM for interpretable human-state recognition.

Deliberately hand-rolled (NO hmmlearn): interpretability of the transition matrix,
emissions, and per-step posteriors is a paper requirement, and the reported model
must be fitted from labelled pilot data with an auditable procedure.
"""

from .upper import STATES, UpperHMM, default_emissions
from .lower import LowerHMM

__all__ = ["STATES", "UpperHMM", "default_emissions", "LowerHMM"]
