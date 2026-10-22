"""Admission (2610.18813): staged, each stage can veto with a reason. Stages here:
  target policy -> (guard + trial in server.aura) -> window gate -> retention gate.
The retention gate replays earlier KEEP windows (disjoint from the current one) and charges net held-out regressions
against a cumulative, decaying regression budget."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..env import run_task
from .targets import ADMISSIBLE, Target, target_of


def target_veto(c) -> str | None:
    t = target_of(c)
    return None if t in ADMISSIBLE else f"target {t.value} is not admissible"


def outcomes(args) -> dict[int, bool]:
    """replay a window under `table` from its checkpoint -> {held-out task id: success}"""
    table, tasks, mem, seed, shift = args
    mem = mem.copy()
    out = {}
    for t in tasks:
        ep = run_task(t, table, mem, seed, shift)
        if t.heldout:
            out[t.id] = bool(ep.success)
    return out


@dataclass
class RetentionGate:
    rho: float = 0.05            # budget per retained held-out task
    decay_every: int = 50        # one unit of spent budget is forgiven every this many tasks
    keep_windows: int = 4
    windows: list = field(default_factory=list)   # (start, end, tasks, mem checkpoint)
    spent: float = 0.0
    last_ts: int = 0
    vetoes: int = 0
    checks: int = 0
    log: list = field(default_factory=list)

    def _decay(self, ts):
        if self.decay_every:
            k = (ts - self.last_ts) / self.decay_every
            self.spent = max(0.0, self.spent - k)
        self.last_ts = ts

    def suite(self, cur_start: int):
        return [w for w in self.windows if w[1] < cur_start]

    def check(self, ts, cur_start, base_tb, cand_tb, seed, shift, pmap=map) -> tuple[bool, dict]:
        self._decay(ts)
        suite = self.suite(cur_start)
        if not suite:
            return True, {"suite": 0}
        self.checks += 1
        jobs = []
        for (_s, _e, tasks, mem) in suite:
            jobs += [(base_tb, tasks, mem, seed, shift), (cand_tb, tasks, mem, seed, shift)]
        res = list(pmap(outcomes, jobs))
        reg = rec = n = 0
        for b, c in zip(res[0::2], res[1::2]):
            for tid, ok in b.items():
                n += 1
                if ok and not c[tid]:
                    reg += 1
                elif c[tid] and not ok:
                    rec += 1
        net = reg - rec
        left = int(self.rho * n) - self.spent
        ok = net <= max(0.0, left)
        info = {"suite": len(suite), "n": n, "regressions": reg, "recoveries": rec, "budget_left": round(left, 2),
                "admit": ok}
        if not ok:
            self.vetoes += 1
        self.log.append(dict(info, ts=ts))
        return ok, info

    def admitted(self, ts, start, end, tasks, mem, info):
        if info.get("n"):
            self.spent += max(0, info["regressions"] - info["recoveries"])
        self.windows.append((start, end, tasks, mem))
        self.windows = self.windows[-self.keep_windows:]


__all__ = ["RetentionGate", "target_veto", "outcomes", "Target"]
