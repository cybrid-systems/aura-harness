"""M2 pieces (docs/rsi-design.md): proposal budget (RRSI 2609.24972), critic and pruner (RRSI), Pareto archive
(Harmony 2610.15150), fresh one-use validation (2610.18813 admission rule), library recombination (PluginRSI)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..env import run_task
from ..harness import COMPONENT, Candidate, seed_table


@dataclass
class M2Config:
    budget: bool = False        # annealed candidates-per-step budget
    k0: int = 4                 # candidates allowed at t=0
    kmin: int = 2               # ... at the end of the stream
    critic: bool = False        # veto proposals whose evidence all comes from one project
    pruner: bool = False        # periodic ablation of kept plugin edits
    prune_every: int = 100
    fresh: bool = False         # admission needs a non-loss on fresh, one-use held-out tasks
    recombine: bool = False     # add library variants of the same plugin as candidates
    archive: bool = True        # Pareto archive bookkeeping (always cheap)

    def any(self):
        return self.budget or self.critic or self.pruner or self.fresh or self.recombine


def fresh_of(tid: int) -> bool:
    """second, independent hash split of held-out tasks: fresh (admission only) vs gate"""
    return ((tid * 40503 + 7) >> 5) % 2 == 1


def per_task(args) -> dict[int, tuple[bool, int]]:
    table, tasks, mem, seed, shift = args
    mem = mem.copy()
    out = {}
    for t in tasks:
        ep = run_task(t, table, mem, seed, shift)
        if t.heldout:
            out[t.id] = (bool(ep.success), ep.cost)
    return out


def agg(res: dict, keep=lambda tid: True) -> tuple[int, int, int]:
    ok = n = cost = 0
    for tid, (s, c) in res.items():
        if keep(tid):
            n += 1
            ok += s
            cost += c
    return ok, n, cost


def budget_k(cfg: M2Config, ts: int, n: int) -> int:
    return max(cfg.kmin, round(cfg.k0 - (cfg.k0 - cfg.kmin) * ts / max(1, n)))


class Critic:
    """RRSI critic: screens benchmark-specific proposals. Evidence for a signature must span >= 2 projects."""

    def __init__(self):
        self.projects: dict[str, set] = {}
        self.vetoes = 0

    def note(self, sig, project):
        self.projects.setdefault(sig, set()).add(project)

    def veto(self, sig) -> bool:
        bad = len(self.projects.get(sig, ())) < 2
        self.vetoes += bad
        return bad


def pareto_insert(archive: list, entry: dict) -> list:
    """objectives: success (max), tokens (min), retention regressions (min)"""
    def dom(a, b):
        ge = a["success"] >= b["success"] and a["tokens"] <= b["tokens"] and a["regress"] <= b["regress"]
        gt = a["success"] > b["success"] or a["tokens"] < b["tokens"] or a["regress"] < b["regress"]
        return ge and gt
    if any(dom(a, entry) for a in archive):
        return archive
    return [a for a in archive if not dom(entry, a)] + [entry]


def seed_value(define):
    return seed_table()[COMPONENT[define]]


def recomb_candidates(lib, tb, define, sig, why, limit=2) -> list[Candidate]:
    cur = json.dumps(tb[COMPONENT[define]], sort_keys=True)
    out = []
    for v in sorted(lib.of(define), key=lambda v: -v.uses):
        if json.dumps(v.value, sort_keys=True) != cur:
            out.append(Candidate(define, v.value, why, sig, f"recombine {v.desc} [{v.id}]",
                                 meta={"target": "composition"}))
        if len(out) >= limit:
            break
    return out


def prune_candidates(tb) -> list[Candidate]:
    """one ablation per plugin that differs from the seed: revert that plugin to its seed value"""
    out = []
    for define, key in COMPONENT.items():
        sv = seed_value(define)
        if json.dumps(tb[key], sort_keys=True) != json.dumps(sv, sort_keys=True):
            out.append(Candidate(define, sv, "pruner: ablate", "prune|" + define, f"prune {define}",
                                 meta={"target": "state"}))
    return out
