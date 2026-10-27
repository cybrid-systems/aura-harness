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
from .m2 import (Critic, M2Config, agg, budget_k, fresh_of, pareto_insert, per_task, prune_candidates,
                 recomb_candidates)
from .plugins import Library
from .proposal import CandidateQueue, RuleSource
from .stat import StatAdmission, hard_veto, per_task3


def run_rsi(seed: int, n: int = 400, shift: int = 200, window: int = 80, min_evidence: int = 3, noise: float = 0.0,
            worldlines: str = "ws", jobs: int = 1, backend=None, min_heldout: int = 20,
            retention: RetentionGate | None = None, supervise: bool = True, label: str = "rsi",
            cfg: M2Config | None = None, world: str = "sim", ledger=None, proposer=None, measure: bool = False) -> dict:
    from .supervisor import SupervisedAura
    from ..control import AuraHarness
    t_start = time.perf_counter()
    h = backend or (SupervisedAura(worldlines) if supervise else AuraHarness(worldlines))
    pool = ProcessPoolExecutor(jobs) if jobs > 1 else None
    pmap = pool.map if pool else map
    if world in ("dev", "dev2"):
        from ..devenv import make_stream as dev_stream
        stream = dev_stream(seed, n, shift, v2=world == "dev2")
    else:
        stream = make_stream(seed, n, shift)
    # proposer: None = scripted; or a factory(min_evidence=, noise=, seed=) -> Proposer (e.g. the M5 LLM proposer)
    src = RuleSource(proposer(min_evidence=min_evidence, noise=noise, seed=seed) if proposer else None,
                     min_evidence=min_evidence, noise=noise, seed=seed)
    lib = Library()
    cfg = cfg or M2Config()
    m2 = cfg.any()
    stat = cfg.admission == "stat"
    sa = StatAdmission(alpha=cfg.alpha)  # K concurrent pending slots
    queue = CandidateQueue()             # stat mode: proposals made while a candidate is pending admission
    if stat and retention is None:
        retention = RetentionGate()          # the retention budget gate is always on in stat mode
    keep_tables = []
    critic = Critic()
    archive: list = []
    spent_fresh: set = set()
    stats = {"budget_cut": 0, "critic_veto": 0, "fresh_veto": 0, "pruned": [], "recombined": 0,
             "recomb_kept": 0, "fresh_checks": 0}
    tb = h.table()
    mem = Memory(seed)
    ckpts = {}
    eps, verdicts = [], []
    gate_s, change_s = [], []
    learn = {"replay_tasks": 0}          # measurement only (rsi/metrics.py cost split)
    try:
        for t in stream:
            if t.id % 10 == 0:
                ckpts[t.id] = mem.copy()
            ep = run_task(t, tb, mem, seed, shift)
            eps.append(ep.summary())
            if t.heldout:
                continue
            if stat:
                sa.assign(stream, t.id)
                for P in [P for P in sa.slots if sa.due(P)]:
                    if P in sa.slots:                      # an earlier KEEP this step may have displaced it
                        tb = _stat_decide(h, t, tb, stream, ckpts, seed, shift, pmap, sa, src, retention, ledger,
                                          lib, verdicts, keep_tables, learn, P, queue)
            if cfg.pruner and t.id and t.id % cfg.prune_every == 0 and t.id >= window:
                tb = _prune(h, t, tb, stream, ckpts, window, seed, shift, pmap, stats, lib, ledger, learn)
            d = src.p.diagnose(ep) if cfg.critic else None
            if d:
                critic.note(f"{d[0]}|{d[1]}", t.project)
            cands = src.observe(ep, tb)
            if stat:
                # the proposer keeps running while candidates wait for fresh evidence; its output is queued and
                # selected into one of K concurrent slots, each with its own disjoint one-use fresh tasks
                queue.push(cands, [d for P in sa.slots for d in P["descs"]], [P["sig"] for P in sa.slots])
                if sa.full() or not len(queue):
                    continue
                cands = queue.pop(tb, src.p._noop)
            if not cands:
                continue
            if cfg.critic and critic.veto(cands[0].sig):
                stats["critic_veto"] += 1
                src.feedback(cands[0].sig, "ROLLBACK", [])
                verdicts.append({"ts": t.id, "verdict": "ROLLBACK", "chosen": None, "candidates": [c.desc for c in cands],
                                 "blocked": [], "why": "critic: single-project evidence", "scores": {}, "sig": cands[0].sig})
                continue
            if cfg.recombine:
                rc = recomb_candidates(lib, tb, cands[0].name, cands[0].sig, cands[0].why) \
                    if cands[0].name in COMPONENT else []
                stats["recombined"] += len(rc)
                cands = cands + rc
            if cfg.budget:
                k = budget_k(cfg, t.id, n)
                if len(cands) > k:
                    stats["budget_cut"] += len(cands) - k
                    cands = cands[:k]
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
            learn["replay_tasks"] += sum(len(j[1]) for j in jobs_args)
            if m2:
                pts = list(pmap(per_task, jobs_args))
                gk = (lambda tid: not fresh_of(tid)) if (cfg.fresh or stat) else (lambda tid: True)
                scores = [agg(x, gk) for x in pts]
            else:
                scores = list(pmap(replay_score, jobs_args))
            base, cs = scores[0], scores[1:]
            ranked = sorted(((s, r) for r, s in zip(ok_trials, cs)), key=lambda x: (-x[0][0], x[0][2], x[1]["i"]))
            sc = {"base": base, "candidates": {cands[r["i"]].desc: s for r, s in zip(ok_trials, cs)},
                  "window": [start, t.id], "heldout": base[1]}
            best, bs = -1, base
            for r, s in zip(ok_trials, cs):
                if better(s, bs):
                    best, bs = r["i"], s
            if stat and best >= 0 and not hard_veto(cands[best]):
                # M5b: selection done on the selection split; admission waits for fresh tasks after t.id
                h.verdict(t.id, -1, dict(sc, stat="selected; admission pending"), cands[0].why)
                sa.open({"ts": t.id, "start": start, "cand": cands[best], "sig": sig, "blocked": blocked,
                              "table": next(r["table"] for r in ok_trials if r["i"] == best), "look": 0,
                              "descs": [c.desc for c in cands], "tasks": tasks, "mem0": mem0, "sel": sc,
                              "n_llm": sum(c.meta.get("proposer") == "llm" for c in cands), "cands": cands})
                gate_s.append(time.perf_counter() - g0)
                continue
            best = -1 if stat else best
            # stage 3b: fresh one-use validation (held-out tasks the gate never scored, each used for one admission)
            if cfg.fresh and best >= 0:
                fk = lambda tid: fresh_of(tid) and tid not in spent_fresh
                bi = next(j for j, r in enumerate(ok_trials) if r["i"] == best)
                fb, fc = agg(pts[0], fk), agg(pts[bi + 1], fk)
                stats["fresh_checks"] += 1
                sc["fresh"] = {"base": fb, "cand": fc}
                if fc[0] < fb[0]:
                    stats["fresh_veto"] += 1
                    best = -1
                else:
                    spent_fresh.update(tid for tid in pts[0] if fk(tid))
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
            if ledger is not None:
                for d in blocked:
                    ledger.event("blocked", t.id, desc=d, why=cands[0].why)
            if vr["verdict"] == "KEEP":
                c = cands[best]
                if ledger is not None:
                    bi = next(j for j, r in enumerate(ok_trials) if r["i"] == best)
                    ledger.admit("keep", t.id, c, tb, vr["table"], "gate", {
                        "evidence": sig, "reason": c.why, "candidates": [x.desc for x in cands], "blocked": blocked,
                        "gate": {"window": [start, t.id], "base": list(base), "chosen": list(cs[bi])},
                        "retention": sc.get("retention"), "fresh": sc.get("fresh")})
                keep_tables.append({"ts": t.id, "desc": c.desc, "before": tb, "after": vr["table"]})
                tb = vr["table"]
                lib.add(c.name, tb[COMPONENT[c.name]], c.desc, sig, t.id, t.phase)
                if c.meta.get("target") == "composition":
                    stats["recomb_kept"] += 1
                if cfg.archive:
                    s_ = scores[1 + next(j for j, r in enumerate(ok_trials) if r["i"] == best)]
                    archive = pareto_insert(archive, {"ts": t.id, "success": s_[0] / max(1, s_[1]),
                                                      "tokens": s_[2] / max(1, s_[1]),
                                                      "regress": (ret_info or {}).get("regressions", 0),
                                                      "kept": c.desc})
                if retention is not None:
                    retention.admitted(t.id, start, t.id, tasks, mem0, ret_info or {})
            src.feedback(sig, vr["verdict"], blocked)
            gate_s.append(time.perf_counter() - g0)
            verdicts.append({"ts": t.id, "verdict": vr["verdict"], "chosen": cands[best].desc if best >= 0 else None,
                             "candidates": [c.desc for c in cands], "blocked": blocked, "scores": sc,
                             "why": cands[0].why, "gate_ms": round(1000 * gate_s[-1], 1),
                             "chosen_by": cands[best].meta.get("proposer", "rule") if best >= 0 else None,
                             "n_llm": sum(c.meta.get("proposer") == "llm" for c in cands), "sig": sig})
        if ledger is not None:
            for e in getattr(h, "events", []):
                if e["op"] == "restart":
                    ledger.event("restart", e["ts"], why=e["why"], replayed=e["replayed"], ms=e["ms"])
            if hasattr(src.p, "llm_usage"):          # M5: LLM usage / cost tally (no request data, no key)
                ledger.event("llm-usage", n, **src.p.llm_usage())
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
    out["final_table"] = tb
    out["m2"] = dict(stats, archive=len(archive), archive_members=archive)
    out["restarts"] = getattr(h, "restarts", 0)
    out["keep_tables"] = keep_tables
    if stat:
        out["stat"] = {"log": sa.log, "pending_at_end": len(sa.slots), "k": sa.k, "alpha_look": sa.alpha_look,
                       "unused_fresh": sa.unused_fresh, "owner": sa.owner, "conflicts": sa_conf(sa), "queue": dict(queue.n, left=len(queue))}
    if hasattr(src.p, "llm_usage"):
        v = [x for x in verdicts if x.get("n_llm")]
        out["llm"] = dict(src.p.llm_usage(), gated_with_llm=len(v),
                          llm_kept=sum(x["verdict"] == "KEEP" and x.get("chosen_by") == "llm" for x in verdicts),
                          rule_kept=sum(x["verdict"] == "KEEP" and x.get("chosen_by") == "rule" for x in verdicts))
    if retention is not None:
        learn["replay_tasks"] += retention.replayed
    if measure:
        from .metrics import measure as _measure
        out["metrics"] = _measure(stream, eps, verdicts, seed, shift, learn, out.get("llm"))
        if ledger is not None:
            ledger.event("metrics", n, **out["metrics"])
    if retention is not None:
        out["retention"] = {"checks": retention.checks, "vetoes": retention.vetoes, "spent": round(retention.spent, 2)}
    return out


def _prune(h, t, tb, stream, ckpts, window, seed, shift, pmap, stats, lib, ledger=None, learn=None):
    """RRSI pruner: ablate each kept plugin (revert to seed); adopt the ablation if the recent window is not worse in
    held-out successes and not more expensive. Goes through the guard (trial + verdict, actor pruner)."""
    cands = prune_candidates(tb)
    if not cands:
        return tb
    start = max(0, (t.id - window) // 10 * 10)
    tasks = stream[start:t.id]
    trials = h.trial(t.id, cands, actor="pruner")
    ok = [r for r in trials if r["ok"]]
    if not ok:
        return tb
    if learn is not None:
        learn["replay_tasks"] += len(tasks) * (1 + len(ok))
    sc = list(pmap(replay_score, [(tb, tasks, ckpts[start], seed, shift)] +
                   [(r["table"], tasks, ckpts[start], seed, shift) for r in ok]))
    base = sc[0]
    best, bs = -1, None
    for r, s in zip(ok, sc[1:]):
        if s[0] >= base[0] and s[2] <= base[2] and (bs is None or (s[0], -s[2]) > (bs[0], -bs[2])):
            best, bs = r["i"], s
    vr = h.verdict(t.id, best, {"base": base, "prune": True}, "pruner: ablate kept plugins", actor="pruner")
    if vr["verdict"] == "KEEP":
        stats["pruned"].append((t.id, cands[best].desc))
        if ledger is not None:
            ledger.admit("prune", t.id, cands[best], tb, vr["table"], "pruner",
                         {"reason": "pruner: plugin no longer useful", "gate": {"base": list(base), "chosen": list(bs)}})
        return vr["table"]
    return tb


def _stat_decide(h, t, tb, stream, ckpts, seed, shift, pmap, sa, src, retention, ledger, lib, verdicts, keep_tables,
                 learn=None, P=None, queue=None):
    learn = learn if learn is not None else {"replay_tasks": 0}
    """M5b admission of the pending candidate on fresh, one-use held-out tasks that arrived after its selection"""
    a0 = (P["ts"] + 1) // 10 * 10
    ids = list(P["fresh"])
    seg = stream[a0:t.id + 1]
    learn["replay_tasks"] += 2 * len(seg)
    rb, rc = list(pmap(per_task3, [(tb, seg, ckpts[a0], seed, shift), (P["table"], seg, ckpts[a0], seed, shift)]))
    v, info = sa.decide(rb, rc, ids, P)
    if v == "wait":
        return tb
    c, verdict, ret_info = P["cand"], "ROLLBACK", None
    if v == "keep" and retention is not None:
        ok, ret_info = retention.check(t.id, P["start"], tb, P["table"], seed, shift, pmap)
        info["retention"] = ret_info
        v = "keep" if ok else "reject"
    if v == "keep":
        res = h.apply(t.id, c, actor="stat-gate")
        if res.get("ok"):
            verdict = "KEEP"
            if ledger is not None:
                ledger.admit("keep", t.id, c, tb, res["table"], "stat-gate", {
                    "evidence": P["sig"], "reason": c.why, "candidates": P["descs"], "blocked": P["blocked"],
                    "selection": {"window": P["sel"]["window"], "base": list(P["sel"]["base"])},
                    "admission": info})
            keep_tables.append({"ts": t.id, "desc": c.desc, "before": tb, "after": res["table"]})
            tb = res["table"]
            _resolve_conflicts(sa, P, c, tb, queue, t.id)
            lib.add(c.name, tb[COMPONENT[c.name]], c.desc, P["sig"], t.id, t.phase)
            if retention is not None:
                retention.admitted(t.id, P["start"], P["ts"], P["tasks"], P["mem0"], ret_info or {})
        else:
            info["apply"] = res.get("reason")
    src.feedback(P["sig"], verdict, P["blocked"])
    verdicts.append({"ts": t.id, "verdict": verdict, "chosen": c.desc if verdict == "KEEP" else None,
                     "candidates": P["descs"], "blocked": P["blocked"], "scores": {"stat": info}, "why": c.why,
                     "chosen_by": c.meta.get("proposer", "rule") if verdict == "KEEP" else None, "n_llm": P["n_llm"],
                     "sig": P["sig"], "proposed_ts": P["ts"]})
    sa.close(P)
    return tb


def sa_conf(sa):
    return [x for x in sa.log if x.get("verdict") == "conflict"]


def _resolve_conflicts(sa, P, c, tb, queue, ts):
    """after P's KEEP on component X: other pending candidates on X are displaced (re-queued for re-selection on
    the new table; their fresh tasks stay spent), the rest are re-based so their table carries the new KEEP"""
    key = COMPONENT[c.name]
    for Q in [Q for Q in sa.slots if Q is not P]:
        qk = COMPONENT.get(Q["cand"].name)
        if qk == key:
            sa.close(Q)
            sa.log.append({"verdict": "conflict", "ts": ts, "slot": Q["uid"], "desc": Q["cand"].desc,
                           "with": c.desc, "component": key, "fresh_spent": len(Q["fresh"])})
            if queue is not None:
                queue.requeue(Q["cands"])
        else:
            Q["table"] = dict(tb, **{qk: Q["table"][qk]})
