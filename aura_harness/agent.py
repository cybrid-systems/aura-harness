"""The self-evolution loop: Solver runs tasks under the live harness and records trajectories; the Proposer reads
evidence trajectories and proposes one-component mutations; the gate trials every candidate in its own worldline and
replays the recent window, scoring ONLY held-out tasks; KEEP the best or roll back. Every step lands in the audit log.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from .env import Memory, make_stream, run_task
from .proposer import get_proposer

MODES = {
    # mode: (backend, learn, gate)
    "frozen": ("aura", False, False),
    "file-reload": ("file", True, True),
    "aura-gated": ("aura", True, True),
    "aura-nogate": ("aura", True, False),
}


def replay_score(args) -> tuple[int, int, int]:
    """replay window tasks from a memory checkpoint under `table`; score held-out tasks only -> (ok, n, cost)"""
    table, tasks, mem, seed, shift = args
    mem = mem.copy()
    ok = n = cost = 0
    for t in tasks:
        ep = run_task(t, table, mem, seed, shift)
        if t.heldout:
            n += 1
            ok += ep.success
            cost += ep.cost
    return ok, n, cost


def better(s, b, tol=0.97) -> bool:
    return s[0] > b[0] or (s[0] == b[0] and s[2] <= tol * b[2])


def run_stream(mode: str, seed: int, n: int = 400, shift: int = 200, window: int = 80, min_evidence: int = 3,
               noise: float = 0.0, worldlines: str = "ws", jobs: int = 1, backend=None, min_heldout: int = 20) -> dict:
    from .control import AuraHarness, FileHarness
    from .harness import seed_table
    kind, learn, gate = MODES[mode]
    t_start = time.perf_counter()
    h = backend or (FileHarness(seed_table()) if kind == "file" else AuraHarness(worldlines))
    pool = ProcessPoolExecutor(jobs) if jobs > 1 else None
    stream = make_stream(seed, n, shift)
    prop = get_proposer(min_evidence=min_evidence, noise=noise, seed=seed)
    tb = h.table()
    mem = Memory(seed)
    ckpts = {}
    eps, verdicts = [], []
    gate_s, change_s = [], []
    try:
        for t in stream:
            if t.id % 10 == 0:
                ckpts[t.id] = mem.copy()
            ep = run_task(t, tb, mem, seed, shift)
            eps.append(ep.summary())
            if not learn or t.heldout:
                continue
            cands = prop.observe(ep, tb)
            if not cands:
                continue
            start = max(0, (t.id + 1 - window) // 10 * 10)
            tasks = stream[start:t.id + 1]
            if gate and sum(x.heldout for x in tasks) < min_heldout:
                continue                     # too few held-out tasks to judge yet; evidence keeps accumulating
            if hasattr(prop, "source"):
                prop.source = h.source()
            sig = cands[0].sig
            if not gate:
                t0 = time.perf_counter()
                blocked, chosen = [], None
                for c in cands:
                    r = h.apply(t.id, c)
                    if r.get("ok"):
                        chosen, tb = c, r["table"]
                        break
                    blocked.append(c.desc)
                change_s.append(time.perf_counter() - t0)
                v = "KEEP" if chosen else "ROLLBACK"
                prop.feedback(sig, v, blocked)
                verdicts.append({"ts": t.id, "verdict": v, "chosen": chosen.desc if chosen else None,
                                 "candidates": [c.desc for c in cands], "blocked": blocked, "why": cands[0].why})
                continue
            g0 = time.perf_counter()
            mem0 = ckpts[start]
            trials = h.trial(t.id, cands)
            blocked = [cands[r["i"]].desc for r in trials if not r["ok"]]
            ok_trials = [r for r in trials if r["ok"]]
            jobs_args = [(tb, tasks, mem0, seed, shift)] + [(r["table"], tasks, mem0, seed, shift) for r in ok_trials]
            scores = list(pool.map(replay_score, jobs_args)) if pool else [replay_score(a) for a in jobs_args]
            base, cs = scores[0], scores[1:]
            best, bs = -1, base
            for r, s in zip(ok_trials, cs):
                if better(s, bs):
                    best, bs = r["i"], s
            sc = {"base": base, "candidates": {cands[r["i"]].desc: s for r, s in zip(ok_trials, cs)},
                  "window": [start, t.id], "heldout": base[1]}
            v0 = time.perf_counter()
            vr = h.verdict(t.id, best, sc, cands[0].why)
            change_s.append(time.perf_counter() - v0)
            if vr["verdict"] == "KEEP":
                tb = vr["table"]
            prop.feedback(sig, vr["verdict"], blocked)
            gate_s.append(time.perf_counter() - g0)
            verdicts.append({"ts": t.id, "verdict": vr["verdict"], "chosen": cands[best].desc if best >= 0 else None,
                             "candidates": [c.desc for c in cands], "blocked": blocked, "scores": sc,
                             "why": cands[0].why, "gate_ms": round(1000 * gate_s[-1], 1)})
        audit = h.log()
        source = h.source()
        lat = {k: v for k, v in h.lat.items()}
    finally:
        h.close()
        if pool:
            pool.shutdown()
    return summarize(mode, seed, n, shift, eps, verdicts, audit, source, lat, gate_s, change_s,
                     time.perf_counter() - t_start, prop)


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def summarize(mode, seed, n, shift, eps, verdicts, audit, source, lat, gate_s, change_s, wall, prop) -> dict:
    w = n // 4
    wins = [eps[i * w:(i + 1) * w] for i in range(4)]
    modes = Counter(e["mode"] for e in eps if not e["success"])
    ms = lambda xs: {"p50_ms": round(1000 * pct(xs, .5), 2), "p99_ms": round(1000 * pct(xs, .99), 2),
                     "n": len(xs)} if xs else None
    return {
        "mode": mode, "seed": seed, "n": n, "shift": shift,
        "success": sum(e["success"] for e in eps) / n,
        "windows": [sum(e["success"] for e in ws) / len(ws) for ws in wins],
        "heldout_success": sum(e["success"] for e in eps if e["heldout"]) / max(1, sum(e["heldout"] for e in eps)),
        "cost_per_task": sum(e["cost"] for e in eps) / n,
        "cost_windows": [sum(e["cost"] for e in ws) / len(ws) for ws in wins],
        "failure_modes": dict(modes),
        "proposals": len(verdicts),
        "keep": sum(v["verdict"] == "KEEP" for v in verdicts),
        "rollback": sum(v["verdict"] == "ROLLBACK" for v in verdicts),
        "blocked": sum(1 for a in audit if a["op"] == "blocked"),
        "blocked_reasons": Counter(a["reason"] for a in audit if a["op"] == "blocked"),
        "kept": [v["chosen"] for v in verdicts if v["verdict"] == "KEEP"],
        "latency": {k: ms(v) for k, v in lat.items()},
        "gate": ms(gate_s), "change": ms(change_s),
        "wall_s": round(wall, 2),
        "verdicts": verdicts, "audit": audit, "final_source": source,
    }


if __name__ == "__main__":
    import sys
    r = run_stream(sys.argv[1], int(sys.argv[2]))
    print(json.dumps({k: v for k, v in r.items() if k not in ("verdicts", "audit", "final_source")}, indent=1))
