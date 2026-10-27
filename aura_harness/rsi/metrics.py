"""ServeLearnBench-style measurements (arXiv 2610.07792, §3.1, §5.1-5.3, App. B.2) for one RSI run. Measurement only:
nothing here feeds back into proposal or admission.

  FS / HD        per-task outcome vs a no-learning baseline (frozen seed harness on the same stream, own memory):
                 regressions = baseline ok & run fails, recoveries = the reverse (paper §5.2, Fully Specified split)
  AULC_K         mean success on the k-th task (k < K) after a hidden fact changes version, pooled over onsets (§5.1)
  AUC_E          per failure signature: c_k = distinct candidates offered over its first k proposal events,
                 AUC_E = mean_{k=1..K} (c_k - 1) (§5.3, 'distinct answers'); plus the repeat rate of candidate sets
  AUC_KA         after the first KEEP for a signature, success on the next K tasks the baseline fails with that same
                 signature (the deficiency the KEEP targeted): does the fix get reused (§5.3, knowledge acquisition)
  acceptance     KEEP rate over proposal events; first-KEEP latency in tasks from a signature's first proposal
  cost split     serving tokens vs learning work: replayed task executions (+ token estimate) and LLM tokens / USD
                 (App. B.2 books learning-side calls as maintenance)"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from ..env import Memory, fact_key, fact_version_of, run_task, task_label
from ..harness import seed_table
from ..proposer import Proposer


def baseline(stream, seed, shift, table=None) -> tuple[list[bool], list[str | None]]:
    """frozen seed harness on the same stream -> (success per task, failure signature per task)"""
    tb, mem, diag = table or seed_table(), Memory(seed), Proposer()
    ok, sig = [], []
    for t in stream:
        ep = run_task(t, tb, mem, seed, shift)
        ok.append(bool(ep.success))
        d = diag.diagnose(ep) if not ep.success else None
        sig.append(f"{d[0]}|{d[1]}" if d else None)
    return ok, sig


def split(stream, run_ok, base_ok, seed, shift) -> dict:
    out = {}
    for lab in ("FS", "HD"):
        ix = [i for i, t in enumerate(stream) if task_label(t, seed, shift) == lab]
        n = len(ix)
        reg = sum(base_ok[i] and not run_ok[i] for i in ix)
        rec = sum(run_ok[i] and not base_ok[i] for i in ix)
        out[lab] = {"n": n, "run": round(sum(run_ok[i] for i in ix) / max(1, n), 4),
                    "baseline": round(sum(base_ok[i] for i in ix) / max(1, n), 4),
                    "regressions": reg, "recoveries": rec}
    return out


def aulc(stream, ok, seed, shift, K=10) -> dict:
    last, onset, pos = {}, {}, defaultdict(list)
    for i, t in enumerate(stream):
        p, f, _ = fact_key(t)
        v = fact_version_of(t, seed, shift)
        key = (p, f)
        if key in last and last[key] != v:
            onset[key] = 0
        elif key in onset:
            onset[key] += 1
        last[key] = v
        if key in onset and onset[key] < K:
            pos[onset[key]].append(ok[i])
    a = [st.mean(pos[k]) for k in range(K) if pos[k]]
    return {"K": K, "aulc": round(st.mean(a), 4) if a else None, "onsets": len(pos[0]),
            "curve": [round(x, 3) for x in a]}


def auc_e(verdicts, K=8) -> dict:
    by = defaultdict(list)
    for v in verdicts:
        if v.get("sig"):
            by[v["sig"]].append(v)
    per, rep, ev = {}, 0, 0
    for s, vs in by.items():
        seen, sets, c = set(), set(), []
        for v in vs[:K]:
            seen.update(v["candidates"])
            c.append(len(seen))
            key = tuple(sorted(v["candidates"]))
            rep += key in sets
            sets.add(key)
            ev += 1
        c += [c[-1]] * (K - len(c))
        per[s] = round(sum(x - 1 for x in c) / K, 3)
    return {"K": K, "auc_e": round(st.mean(per.values()), 3) if per else None, "signatures": len(per),
            "events": ev, "repeat_rate": round(rep / max(1, ev), 3),
            "distinct_per_sig": round(st.mean(len({d for v in by[s] for d in v["candidates"]}) for s in by), 2) if by else None}


def auc_ka(stream, verdicts, run_ok, base_sig, K=5) -> dict:
    idx = {t.id: i for i, t in enumerate(stream)}
    first = {}
    for v in verdicts:
        if v["verdict"] == "KEEP" and v.get("sig") and v["sig"] not in first:
            first[v["sig"]] = v["ts"]
    rs, per = [], {}
    for s, ts in first.items():
        nxt = [i for i in range(idx[ts] + 1, len(stream)) if base_sig[i] == s][:K]
        if nxt:
            per[s] = round(st.mean(run_ok[i] for i in nxt), 3)
            rs += [run_ok[i] for i in nxt]
    return {"K": K, "auc_ka": round(st.mean(rs), 4) if rs else None, "keeps_scored": len(per), "per_sig": per}


def acceptance(verdicts) -> dict:
    n = len(verdicts)
    keeps = [v for v in verdicts if v["verdict"] == "KEEP"]
    first_seen, lat = {}, []
    for v in verdicts:
        s = v.get("sig")
        first_seen.setdefault(s, v.get("proposed_ts", v["ts"]))
        if v["verdict"] == "KEEP" and s not in {x for x, _ in lat}:
            lat.append((s, v["ts"] - first_seen[s]))
    return {"proposals": n, "keep": len(keeps), "accept_rate": round(len(keeps) / max(1, n), 3),
            "first_keep_ts": keeps[0]["ts"] if keeps else None,
            "first_keep_latency_tasks": round(st.mean(x for _, x in lat), 1) if lat else None}


def cost_split(eps, learn, llm=None) -> dict:
    serve = sum(e["cost"] for e in eps)
    per = serve / max(1, len(eps))
    rep = learn.get("replay_tasks", 0)
    out = {"serving_tokens": serve, "serving_tasks": len(eps), "replay_task_execs": rep,
           "replay_execs_per_served": round(rep / max(1, len(eps)), 2),
           "replay_tokens_est": round(rep * per), "learning_share_est": round(rep * per / max(1, rep * per + serve), 3)}
    if llm:
        out.update(llm_calls=llm.get("calls", 0), llm_cache_hits=llm.get("cache_hits", 0),
                   llm_tokens=llm.get("prompt_tokens", 0) + llm.get("completion_tokens", 0),
                   llm_usd=round(llm.get("cost_usd", 0.0), 4))
    return out


def measure(stream, eps, verdicts, seed, shift, learn, llm=None, base=None) -> dict:
    base_ok, base_sig = base or baseline(stream, seed, shift)
    run_ok = [bool(e["success"]) for e in eps]
    return {"split": split(stream, run_ok, base_ok, seed, shift),
            "aulc": {"run": aulc(stream, run_ok, seed, shift), "baseline": aulc(stream, base_ok, seed, shift)},
            "auc_e": auc_e(verdicts), "auc_ka": auc_ka(stream, verdicts, run_ok, base_sig),
            "acceptance": acceptance(verdicts), "cost": cost_split(eps, learn, llm)}
