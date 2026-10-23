"""M5b: fully automatic, human-free statistical admission (alternative to agent.better()).

  selection  - candidates are ranked on the window's *selection* held-out tasks (fresh_of(tid) is False) with
               better(); the winner becomes the single pending candidate.
  admission  - decided only on *fresh* held-out tasks (fresh_of(tid) is True) that arrive AFTER the selection, so no
               task is used for both, and each fresh task is used for one admission only. The decision waits until
               enough fresh evidence has accrued (looks at 16/24/32/40 fresh tasks; it never shrinks a window).
  test       - paired per-task outcomes base vs candidate; discordant pairs b (cand-only wins) / c (base-only wins)
               -> one-sided exact sign test (McNemar) p = P(X >= b | b+c, 1/2). KEEP needs p < alpha / #looks
               (Bonferroni over the sequential looks, so peeking does not inflate the error rate).
  Pareto     - no regression on success (implied), mean tokens and steps (latency proxy) on tasks both solve, and
               the retention budget gate (on in this mode).
  hard veto  - free-form bodies, protected defines and non-admissible targets (guard / runtime boundary) never get
               here: target_veto + the server guard reject them before selection, and admit() re-checks.
Signals come only from automatic trajectory data (task success, tokens, steps)."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import comb

from ..env import run_task
from ..harness import COMPONENT
from .admission import target_veto
from .m2 import fresh_of


def sign_p(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return sum(comb(n, k) for k in range(b, n + 1)) / 2 ** n


def per_task3(args) -> dict[int, tuple[bool, int, int]]:
    table, tasks, mem, seed, shift = args
    mem = mem.copy()
    out = {}
    for t in tasks:
        ep = run_task(t, table, mem, seed, shift)
        if t.heldout:
            out[t.id] = (bool(ep.success), ep.cost, ep.steps)
    return out


def hard_veto(c) -> str | None:
    if c.raw_aura is not None or c.name not in COMPONENT:
        return "free-form / protected define"
    return target_veto(c)


@dataclass
class StatAdmission:
    alpha: float = 0.05
    looks: tuple = (16, 24, 32, 40)
    cost_tol: float = 1.05
    steps_tol: float = 1.05
    pending: dict | None = None
    log: list = field(default_factory=list)

    def fresh_ids(self, stream, upto):
        p = self.pending
        return [t.id for t in stream[p["ts"] + 1:upto + 1] if t.heldout and fresh_of(t.id)]

    def due(self, stream, upto) -> bool:
        n = len(self.fresh_ids(stream, upto))
        return n >= self.looks[min(self.pending["look"], len(self.looks) - 1)]

    def decide(self, base: dict, cand: dict, ids: list) -> tuple[str, dict]:
        """-> ("keep" | "reject" | "wait", info). base/cand: {tid: (ok, tokens, steps)}"""
        b = sum(cand[i][0] and not base[i][0] for i in ids)
        c = sum(base[i][0] and not cand[i][0] for i in ids)
        n = len(ids)
        both = [i for i in ids if base[i][0] and cand[i][0]]      # cost/latency compared where both succeed
        mean = lambda r, k: sum(r[i][k] for i in both) / max(1, len(both))
        p = sign_p(b, c)
        a = self.alpha / len(self.looks)
        info = {"n": n, "b": b, "c": c, "p": round(p, 5), "alpha_look": round(a, 4), "look": self.pending["look"], "both_ok": len(both),
                "tokens": [round(mean(base, 1)), round(mean(cand, 1))],
                "steps": [round(mean(base, 2), 2), round(mean(cand, 2), 2)]}
        if p < a:
            if both and mean(cand, 1) > self.cost_tol * mean(base, 1) or mean(cand, 2) > self.steps_tol * mean(base, 2):
                info["pareto"] = "regression"
                v = "reject"
            else:
                v = "keep"
        elif self.pending["look"] + 1 >= len(self.looks):
            v = "reject"
        else:
            self.pending["look"] += 1
            v = "wait"
        self.log.append(dict(info, verdict=v, desc=self.pending["cand"].desc))
        return v, info
