"""Update targets (2610.18813): what a proposal may change. Control-logic targets are never admissible."""
from __future__ import annotations

from enum import Enum

from ..harness import MUTABLE, PROTECTED, Candidate


class Target(str, Enum):
    STATE = "state"              # a table edit inside one plugin
    CODE = "code"                # a free-form body for a mutable plugin (LLM)
    CONTROL = "control"          # runtime boundary / guard / loop: never admitted
    COMPOSITION = "composition"  # recombination of library variants (M2)


ADMISSIBLE = {Target.STATE, Target.CODE, Target.COMPOSITION}


def target_of(c: Candidate) -> Target:
    if c.meta.get("target"):
        return Target(c.meta["target"])
    if c.name not in MUTABLE:
        return Target.CONTROL
    return Target.CODE if c.raw_aura is not None else Target.STATE


__all__ = ["Target", "ADMISSIBLE", "target_of", "PROTECTED"]
