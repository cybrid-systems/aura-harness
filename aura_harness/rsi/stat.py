"""M5b: fully automatic, human-free statistical admission (alternative to agent.better()).

  selection  - candidates are ranked on the window's *selection* held-out tasks (fresh_of(tid) is False) with
               better(); the winner takes one of K concurrent pending slots.
  admission  - decided only on *fresh* held-out tasks (fresh_of(tid) is True) that arrive AFTER the selection, so no
               task is used for both. Each arriving fresh task is dealt round-robin to exactly one open slot (none open
               -> it is spent unused), so the slots' fresh sets are disjoint and each task serves one admission only. The decision waits until
               enough fresh evidence has accrued (looks at 16/24/32/40 fresh tasks; it never shrinks a window).
  test       - paired per-task outcomes base vs candidate; discordant pairs b (cand-only wins) / c (base-only wins)
               -> one-sided exact sign test (McNemar) p = P(X >= b | b+c, 1/2). KEEP needs p < alpha / (K * #looks):
               Bonferroni over the K concurrent slots and the sequential looks, so the family-wise type-I error over
               everything pending at once stays <= alpha and peeking does not inflate it. (Online FDR rules - LORD++,
               Ramdas et al. 2017, NeurIPS "Online control of the false discovery rate with decaying memory"; alpha-
               investing, Foster & Stine 2008 - were not used: they bound FDR, not FWER, and with ~1-3 discoveries per
               run they buy no power over a fixed split. The serial predecessor (66855b4) used alpha / #looks.)
  conflicts  - a KEEP that changes component X sends every other pending candidate on X back to the caller (re-queue;
               its fresh tasks stay spent); candidates on other components are re-based onto the new table and are
               always replayed against the live table at decision time.
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
    k: int = 3                          # concurrent slots; see docs/rsi-design.md (3a-parallel) for the choice
    cost_tol: float = 1.05
    steps_tol: float = 1.05
    slots: list = field(default_factory=list)
    log: list = field(default_factory=list)
    owner: dict = field(default_factory=dict)       # fresh tid -> slot uid (audit: each fresh task serves one slot)
    cursor: int = -1
    rr: int = 0
    uid: int = 0
    unused_fresh: int = 0

    @property
    def alpha_look(self) -> float:
        return self.alpha / (self.k * len(self.looks))

    def full(self) -> bool:
        return len(self.slots) >= self.k

    def open(self, P: dict) -> dict:
        assert not self.full()
        P.setdefault("look", 0)
        P["fresh"], P["uid"] = [], self.uid
        self.uid += 1
        if not self.slots:
            self.cursor = max(self.cursor, P["ts"])
        self.slots.append(P)
        return P

    def close(self, P: dict) -> None:
        self.slots.remove(P)

    def assign(self, stream, upto: int) -> None:
        for t in stream[self.cursor + 1:upto + 1]:
            if not (t.heldout and fresh_of(t.id)):
                continue
            live = [P for P in self.slots if P["ts"] < t.id]      # only tasks arriving after a slot's selection
            if not live:
                self.unused_fresh += 1
                continue
            P = live[self.rr % len(live)]
            self.rr += 1
            P["fresh"].append(t.id)
            self.owner[t.id] = P["uid"]
        self.cursor = max(self.cursor, upto)

    def due(self, P) -> bool:
        return len(P["fresh"]) >= self.looks[min(P["look"], len(self.looks) - 1)]

    def decide(self, base: dict, cand: dict, ids: list, P: dict) -> tuple[str, dict]:
        """-> ("keep" | "reject" | "wait", info). base/cand: {tid: (ok, tokens, steps)}"""
        b = sum(cand[i][0] and not base[i][0] for i in ids)
        c = sum(base[i][0] and not cand[i][0] for i in ids)
        n = len(ids)
        both = [i for i in ids if base[i][0] and cand[i][0]]      # cost/latency compared where both succeed
        mean = lambda r, k: sum(r[i][k] for i in both) / max(1, len(both))
        p = sign_p(b, c)
        a = self.alpha_look
        info = {"n": n, "fresh": [min(ids), max(ids)] if ids else None, "fresh_ids": list(ids), "sel_ts": P.get("ts"),
                "slot": P.get("uid"), "concurrent": len(self.slots), "b": b, "c": c, "p": round(p, 5),
                "alpha_look": round(a, 5), "look": P["look"], "both_ok": len(both),
                "tokens": [round(mean(base, 1)), round(mean(cand, 1))],
                "steps": [round(mean(base, 2), 2), round(mean(cand, 2), 2)]}
        if p < a:
            if both and mean(cand, 1) > self.cost_tol * mean(base, 1) or mean(cand, 2) > self.steps_tol * mean(base, 2):
                info["pareto"] = "regression"
                v = "reject"
            else:
                v = "keep"
        elif P["look"] + 1 >= len(self.looks):
            v = "reject"
        else:
            P["look"] += 1
            v = "wait"
        self.log.append(dict(info, verdict=v, desc=P["cand"].desc))
        return v, info
