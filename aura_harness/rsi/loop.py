"""The RSI loop: the legacy gated loop (agent.run_stream) restructured into ProposalSource -> Admission stages, with
a plugin library, an optional retention gate and the crash-restart supervisor. retention=None reproduces the legacy
loop exactly (tests/test_rsi.py)."""
from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor

from ..agent import better, replay_score, summarize
from ..env import Memory, make_stream, run_task
from ..harness import COMPONENT
from .admission import RetentionGate, target_veto
from .plugins import Library
from .proposal import RuleSource


def run_rsi(seed: int, n: int = 400, shift: int = 200, window: int = 80, min_evidence: int = 3, noise: float = 0.0,
            worldlines: str = "ws", jobs: int = 1, backend=None, min_heldout: int = 20,
            retention: RetentionGate | None = None, supervise: bool = True, label: str = "rsi") -> dict:
    from .supervisor import SupervisedAura
    from ..control import AuraHarness
    t_start = time.perf_counter()
    h = backend or (SupervisedAura(worldlines) if supervise else AuraHarness(worldlines))
    pool = ProcessPoolExecutor(jobs) if jobs > 1 else None
    pmap = pool.map if pool else map
    stream = make_stream(seed, n, shift)
    src = RuleSource(min_evidence=min_evidence, noise=noise, seed=seed)
    lib = Library()
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
            if t.heldout:
                continue
            cands = src.observe(ep, tb)
            if not cands:
                continue
            start = max(0, (t.id + 1 - window) // 10 * 10)
            tasks = stream[start:t.id + 1]
            if sum(x.heldout for x in tasks) < min_heldout:
                continue
            if hasattr(src.p, "source"):
                src.p.source = h.source()
            sig = cands[0].sig
            g0 = time.perf_counter()
            mem0 = ckpts[start]
            # stage 1: target policy (host). Vetoed candidates still go to the guard so the attempt is audited there.
            pre = {i: target_veto(c) for i, c in enumerate(cands)}
            # stage 2: guard + worldline trial (server.aura)
            trials = h.trial(t.id, cands)
            blocked = [cands[r["i"]].desc for r in trials if not r["ok"]]
            ok_trials = [r for r in trials if r["ok"] and not pre[r["i"]]]
            blocked += [cands[r["i"]].desc for r in trials if r["ok"] and pre[r["i"]]]
            # stage 3: window gate (held-out tasks of the recent window, paired replay)
            jobs_args = [(tb, tasks, mem0, seed, shift)] + [(r["table"], tasks, mem0, seed, shift) for r in ok_trials]
            scores = list(pmap(replay_score, jobs_args))
            base, cs = scores[0], scores[1:]
            ranked = sorted(((s, r) for r, s in zip(ok_trials, cs)), key=lambda x: (-x[0][0], x[0][2], x[1]["i"]))
            sc = {"base": base, "candidates": {cands[r["i"]].desc: s for r, s in zip(ok_trials, cs)},
                  "window": [start, t.id], "heldout": base[1]}
            best, bs = -1, base
            for r, s in zip(ok_trials, cs):
                if better(s, bs):
                    best, bs = r["i"], s
            # stage 4: retention gate on the gate's pick; on a veto fall back to the next-best passing candidate
            ret_info = None
            if retention is not None and best >= 0:
                order = [best] + [r["i"] for s, r in ranked if r["i"] != best and better(s, base)]
                tables = {r["i"]: r["table"] for r in ok_trials}
                best = -1
                for i in order:
                    ok, ret_info = retention.check(t.id, start, tb, tables[i], seed, shift, pmap)
                    ret_info["cand"] = cands[i].desc
                    if ok:
                        best = i
                        break
                sc["retention"] = ret_info
            v0 = time.perf_counter()
            vr = h.verdict(t.id, best, sc, cands[0].why)
            change_s.append(time.perf_counter() - v0)
            if vr["verdict"] == "KEEP":
                tb = vr["table"]
                c = cands[best]
                lib.add(c.name, tb[COMPONENT[c.name]], c.desc, sig, t.id, t.phase)
                if retention is not None:
                    retention.admitted(t.id, start, t.id, tasks, mem0, ret_info or {})
            src.feedback(sig, vr["verdict"], blocked)
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
    out = summarize(label, seed, n, shift, eps, verdicts, audit, source, lat, gate_s, change_s,
                    time.perf_counter() - t_start, src)
    out["library"] = lib.summary()
    out["restarts"] = getattr(h, "restarts", 0)
    if retention is not None:
        out["retention"] = {"checks": retention.checks, "vetoes": retention.vetoes, "spent": round(retention.spent, 2)}
    return out
