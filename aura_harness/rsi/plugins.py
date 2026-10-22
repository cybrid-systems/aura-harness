"""The five mutable harness defines as plugins (PluginRSI 2609.32423, ModularRSI 2609.14857): each has its own
restricted scope (one define, one table), compiler and validator; admitted variants accumulate in a library."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from ..harness import COMPONENT, MUTABLE, PROTECTED, post_check, to_lisp


@dataclass(frozen=True)
class Plugin:
    define: str          # workspace define it owns
    key: str             # decision-table component
    role: str            # ModularRSI-style module role

    def compile(self, value) -> str:
        return to_lisp(self.define, value)

    def validate(self, table: dict, boundary: dict) -> str | None:
        return post_check(table, boundary)


ROLES = {"route-tool": "tool use", "compress": "observation management", "retry-limit": "agent loop / error policy",
         "memory-ttl": "context management (memory)", "delegate": "agent loop (sub-agents)"}
PLUGINS = {d: Plugin(d, COMPONENT[d], ROLES[d]) for d in MUTABLE}


def variant_id(define: str, value) -> str:
    return hashlib.sha1((define + json.dumps(value, sort_keys=True)).encode()).hexdigest()[:10]


@dataclass
class Variant:
    id: str
    define: str
    value: object
    desc: str
    sig: str
    ts: int
    phase: int
    uses: int = 1


@dataclass
class Library:
    """every admitted plugin variant with provenance; recombination draws from here (M2)"""
    variants: dict[str, Variant] = field(default_factory=dict)

    def add(self, define, value, desc, sig, ts, phase) -> Variant:
        vid = variant_id(define, value)
        v = self.variants.get(vid)
        if v:
            v.uses += 1
            return v
        v = self.variants[vid] = Variant(vid, define, value, desc, sig, ts, phase)
        return v

    def of(self, define) -> list[Variant]:
        return [v for v in self.variants.values() if v.define == define]

    def summary(self) -> dict:
        return {d: len(self.of(d)) for d in PLUGINS}


__all__ = ["PLUGINS", "PROTECTED", "Plugin", "Library", "Variant", "variant_id"]
