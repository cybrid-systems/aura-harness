"""LLM proposes -> swarm fine-tunes: a local searcher around LLM candidates in the RSI loop.

The LLM proposer emits typed mutations (route / compress / retry / ttl / delegate). For each LLM candidate the
swarm hill-climbs over neighbouring *typed* mutations of the same entry (limit x0.5..x2 and other strategies for
compress, n+-1 for retry, ttl /2 x2, delegate threshold +-1 / inline, the other tools for a route). Every neighbour
is built with the same validator as an LLM mutation (rsi/llm.build), so it is range-checked and goes through the
same target policy, Aura guard (server.aura), gate and stat admission afterwards.

Coordinator path (no shared mutation; aura#4730): the refiner object is the single writer. Workers are pure
functions (`train_score`) that replay the window's EVIDENCE tasks on a private copy of the memory and return one
score tuple as their message; the coordinator assigns attempt ids, records every attempt, and decides. Workers run
through the loop's pmap (a process pool for jobs > 1), so nothing is shared between them.

Isolation: the swarm scores on evidence (training) tasks only, like the proposer itself. Held-out tasks stay for the
gate's selection split and the fresh one-use admission split, so the stat admission test is unchanged.
"""
from __future__ import annotations

import copy

from ..env import NEEDS_TOOLS, run_task
from ..harness import COMPONENT
from .llm import STRATS, build
from .targets import target_of


def train_score(args) -> tuple[int, int, int]:
    """worker: (table, tasks, mem, seed, shift) -> (successes, n, tokens) over the non-held-out tasks"""
    table, tasks, mem, seed, shift = args
    mem = mem.copy()
    ok = n = cost = 0
    for t in tasks:
        ep = run_task(t, table, mem, seed, shift)
        if not t.heldout:
            n += 1
            ok += bool(ep.success)
            cost += ep.cost
    return ok, n, cost


def better(a, b) -> bool:
    """more evidence successes; on a tie strictly fewer tokens"""
    return a[0] > b[0] or (a[0] == b[0] and a[2] < b[2])


def _r50(x):
    return int(round(x / 50.0) * 50)


def neighbours(m: dict) -> list[dict]:
    k = m.get("kind")
    out = []
    if k == "compress":
        lim = m["limit"]
        out += [dict(m, limit=v) for v in dict.fromkeys(_r50(lim * f) for f in (0.5, 0.75, 1.5, 2.0))
                if 100 <= v <= 2000 and v != lim]
        out += [dict(m, strategy=s) for s in STRATS if s != m["strategy"]]
    elif k == "retry":
        out += [dict(m, n=v) for v in (m["n"] - 1, m["n"] + 1, 0, m["n"] + 2) if 0 <= v <= 5 and v != m["n"]]
    elif k == "ttl":
        n = m["n"]
        out += [dict(m, n=v) for v in dict.fromkeys((n // 2, n * 2, n + 10, n - 10, 0)) if 0 <= v <= 1000 and v != n]
    elif k == "delegate":
        t = m.get("threshold")
        vals = (3, 5) if t is None else (t - 1, t + 1, None)
        out += [dict(m, threshold=v) for v in vals if v is None or 2 <= v <= 7]
    elif k == "route":
        out += [dict(m, tool=x) for x in NEEDS_TOOLS.get(m["need"], []) if x != m["tool"]]
    # dedupe, deterministic order
    seen, res = set(), []
    for x in out:
        key = tuple(sorted((a, str(b)) for a, b in x.items()))
        if key not in seen:
            seen.add(key)
            res.append(x)
    return res


def apply_to(tb: dict, c) -> dict:
    t2 = copy.deepcopy(tb)
    t2[COMPONENT[c.name]] = copy.deepcopy(c.value)
    return t2


class SwarmRefiner:
    """single-writer coordinator of the local search; `refine` returns (candidates, info for the trace)"""

    def __init__(self, rounds: int = 2, width: int = 6, max_parents: int = 3, noop=None):
        self.rounds, self.width, self.max_parents, self.noop = rounds, width, max_parents, noop
        self.next_id = 0
        self.attempts: list[dict] = []        # every attempt (coordinator-owned log)
        self.n = {"refine_calls": 0, "parents": 0, "attempts": 0, "improved": 0, "evals_replayed": 0}

    def _aid(self, ts):
        self.next_id += 1
        return f"sw{ts}.{self.next_id}"

    def refine(self, ts, cands, tb, tasks, mem0, seed, shift, pmap=map):
        parents = [c for c in cands if c.meta.get("proposer") == "llm" and c.meta.get("mutation")][:self.max_parents]
        if not parents:
            return cands, None
        self.n["refine_calls"] += 1
        info = {"ts": ts, "parents": [], "attempts": []}
        seen = {c.desc for c in cands}
        refined = []
        for p in parents:
            self.n["parents"] += 1
            pid = self._aid(ts)
            (ps,) = list(pmap(train_score, [(apply_to(tb, p), tasks, mem0, seed, shift)]))
            self._log(info, pid, None, p.desc, 0, ps, True)
            cur, cur_m, cur_s, cur_id, lineage = p, p.meta["mutation"], ps, pid, [pid]
            for r in range(1, self.rounds + 1):
                ns = []
                for m in neighbours(cur_m):
                    c = build(m, tb, p.why, p.sig)
                    if c is None or c.desc in seen or (self.noop and self.noop(c, tb)):
                        continue
                    seen.add(c.desc)
                    ns.append((m, c))
                    if len(ns) >= self.width:
                        break
                if not ns:
                    break
                ids = [self._aid(ts) for _ in ns]
                scores = list(pmap(train_score, [(apply_to(tb, c), tasks, mem0, seed, shift) for _, c in ns]))
                best = None
                for (m, c), aid, s in zip(ns, ids, scores):     # messages applied in attempt-id order
                    up = better(s, cur_s if best is None else best[2])
                    self._log(info, aid, cur_id, c.desc, r, s, False)
                    if up:
                        best = (m, c, s, aid)
                if best is None:
                    break
                cur_m, cur, cur_s, cur_id = best[0], best[1], best[2], best[3]
                lineage.append(cur_id)
                for a in info["attempts"]:
                    if a["id"] == cur_id:
                        a["accepted"] = True
            info["parents"].append({"parent": p.desc, "parent_id": pid, "result": cur.desc, "result_id": cur_id,
                                    "parent_score": list(ps), "result_score": list(cur_s), "lineage": lineage})
            if cur is not p:
                self.n["improved"] += 1
                cur.meta.update(proposer="llm+swarm", mutation=cur_m, target=target_of(cur).value,
                                swarm={"parent": p.desc, "parent_id": pid, "attempt_id": cur_id, "lineage": lineage})
                p.meta["swarm"] = {"parent_id": pid, "refined_to": cur_id}
                refined.append(cur)
            else:
                p.meta["swarm"] = {"parent_id": pid, "refined_to": None}
        self.n["evals_replayed"] += len(info["attempts"]) * len(tasks)
        # refined candidates first (the gate ranks all of them anyway); parents are kept, so LLM+swarm >= LLM
        return refined + cands, info

    def _log(self, info, aid, parent, desc, rnd, s, accepted):
        a = {"id": aid, "parent": parent, "desc": desc, "round": rnd, "ok": s[0], "n": s[1], "tokens": s[2],
             "accepted": accepted, "ts": info["ts"]}
        info["attempts"].append(a)
        self.attempts.append(a)              # same record: the coordinator's log is the only copy
        self.n["attempts"] += 1

    def summary(self):
        return dict(self.n, attempt_ids=len({a["id"] for a in self.attempts}))
