"""M6 bench (dev world v2): M5 (scripted RSI M1 / LLM proposer) vs the M6 HarnessPro tiers (lite / medium / heavy),
ablations (router only, hook only, full), scripted vs LLM planner, label-based vs label-free admission, and the
synthesized-test vs LLM-judge failure-recall study. Phase 1 runs M5 per seed (its final table is M6's h0)."""
from __future__ import annotations

import copy
import json
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

M5_CONFIGS = {"M5 scripted (RSI M1)": {}, "M5 LLM proposer": {"proposer": "llm"}}
M6_CONFIGS = {"M6 full": dict(ablation="full"), "M6 router only": dict(ablation="router"),
              "M6 hook only": dict(ablation="hook"), "M6 full, scripted planner": dict(ablation="full", planner="scripted"),
              "M6 full, label-free (synth tests)": dict(ablation="full", label_free=True)}


def evaluate2(tb, tasks, seed):
    from .rsi.m6 import metrics, run_set
    eps = run_set(tb, tasks, seed)
    m = metrics(eps)
    return {"success": m["pr"], "tokens": m["cost"], "latency": m["latency"],
            "cost_of_pass": sum(e.cost for e in eps) / max(1, sum(e.success for e in eps)),
            "wrong_fix": sum(e.mode == "wrong-fix" for e in eps) / len(eps)}


def _eval_all(tb, seed):
    from .devbench import fresh_heldout
    from .devenv import ood_tasks
    return {"heldout": evaluate2(tb, fresh_heldout(seed, v2=True), seed), "ood": evaluate2(tb, ood_tasks(seed, v2=True), seed)}


def one_m5(args):
    name, seed, n, out = args
    from .devbench import _llm_factory
    from .rsi.loop import run_rsi
    cfg = dict(M5_CONFIGS[name])
    prop = _llm_factory(cfg.pop("proposer")) if "proposer" in cfg else None
    r = run_rsi(seed, n=n, shift=n // 2, window=40, min_heldout=10, world="dev2", label=name, proposer=prop)
    res = {"config": name, "seed": seed, "stream_success": r["success"], "keep": r["keep"], "kept": r["kept"],
           "final_table": r["final_table"], "wall_s": r.get("wall_s"), "llm": r.get("llm"), **_eval_all(r["final_table"], seed)}
    Path(out, f"m5-{name.split()[1]}-{seed}.json").write_text(json.dumps(res))
    return res


def one_m6(args):
    name, seed, n, out, h0 = args
    from .rsi.ledger import Ledger
    from .rsi.m6 import run_m6
    led = Ledger(Path(out, "ledgers", f"{name.replace(' ', '_').replace(',', '')}-{seed}.jsonl"))
    r = run_m6(seed, n=n, shift=n // 2, start_table=h0, ledger=led, **M6_CONFIGS[name])
    r["config"] = name
    r["eval"] = {}
    for tier, m in r["tiers"].items():
        r["eval"][tier] = _eval_all(m["table"], seed)
    Path(out, f"m6-{name.replace(' ', '_').replace(',', '')}-{seed}.json").write_text(json.dumps(r, default=str))
    return r


def recall(seeds, out, tables):
    """failure recall of synthesized tests vs an LLM judge, on claimed-success episodes of fresh held-out + OOD tasks
    under every table in `tables` (lite/compact tiers produce plausible wrong fixes)"""
    from .devbench import fresh_heldout
    from .devenv import ood_tasks
    from .rsi.llm import LLMClient
    from .rsi.m6 import Judge, TestSynth, recall_study, run_set
    c = LLMClient(max_calls=2000, max_tokens=4_000_000)
    synth, judge = TestSynth(c), Judge(c)
    eps, seen = [], set()
    for seed in seeds:
        for tb in tables[seed]:
            for e in run_set(tb, fresh_heldout(seed, v2=True) + ood_tasks(seed, v2=True), seed):
                k = (e.task.project, e.task.bugs, json.dumps(e.final_src, sort_keys=True))
                if e.claimed and k not in seen:
                    seen.add(k)
                    eps.append(e)
    r = recall_study(eps, synth, judge)
    r["synth_stats"], r["judge_stats"], r["llm"] = synth.n, judge.n, dict(c.u)
    Path(out, "recall.json").write_text(json.dumps(r, indent=1))
    return r


def all_compact(tb):
    t = copy.deepcopy(tb)
    t["tier"] = {k: "compact" for k in t["tier"]}
    return t


def run(seeds=(0, 1, 2), n=160, jobs=5, out="results/m6", m6=None, skip_m5=False, do_recall=True):
    Path(out, "ledgers").mkdir(parents=True, exist_ok=True)
    m6 = m6 or list(M6_CONFIGS)
    if skip_m5:
        r5 = [json.loads(Path(out, f"m5-{c.split()[1]}-{s}.json").read_text()) for c in M5_CONFIGS for s in seeds]
    else:
        with ProcessPoolExecutor(jobs) as ex:
            r5 = list(ex.map(one_m5, [(c, s, n, out) for c in M5_CONFIGS for s in seeds]))
    h0 = {r["seed"]: r["final_table"] for r in r5 if r["config"] == "M5 scripted (RSI M1)"}
    with ProcessPoolExecutor(jobs) as ex:
        r6 = list(ex.map(one_m6, [(c, s, n, out, h0[s]) for c in m6 for s in seeds]))
    rec = None
    if do_recall:
        tabs = {s: [h0[s], all_compact(h0[s])] + [m["table"] for r in r6 if r["seed"] == s for m in r["tiers"].values()]
                for s in seeds}
        rec = recall(seeds, out, tabs)
    md = report(r5, r6, rec, seeds, n)
    Path(out, "results.md").write_text(md)
    return md


def report(r5, r6, rec, seeds, n):
    L = [f"dev world v2, seeds {list(seeds)}, {n}-task stream; eval on 40 fresh held-out-repo + 30 OOD-repo tasks "
         "per seed. tokens = simulated context + reasoning tokens per task; latency = simulated model seconds per "
         "task; cost-of-pass = tokens / success.", "",
         "| config | tier | held-out success | held-out tokens | held-out latency s | held-out cost-of-pass | OOD success | "
         "OOD tokens | wrong-fix rate (HO) | wall s / seed | LLM USD (total) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    M = lambda xs: st.mean(xs) if xs else 0

    def row(name, tier, evs, wall, usd):
        h, o = [e["heldout"] for e in evs], [e["ood"] for e in evs]
        L.append(f"| {name} | {tier} | {100 * M([x['success'] for x in h]):.1f}% | {M([x['tokens'] for x in h]):,.0f} | "
                 f"{M([x['latency'] for x in h]):.1f} | {M([x['cost_of_pass'] for x in h]):,.0f} | "
                 f"{100 * M([x['success'] for x in o]):.1f}% | {M([x['tokens'] for x in o]):,.0f} | "
                 f"{100 * M([x['wrong_fix'] for x in h]):.1f}% | {wall:.0f} | {usd} |")
    for c in M5_CONFIGS:
        rs = [r for r in r5 if r["config"] == c]
        usd = f"{sum((r['llm'] or {}).get('cost_usd', 0) for r in rs):.4f}" if rs and rs[0].get("llm") else "-"
        row(c, "-", rs, M([r["wall_s"] or 0 for r in rs]), usd)
    for c in dict.fromkeys(r["config"] for r in r6):
        rs = [r for r in r6 if r["config"] == c]
        usd = f"{sum((r['llm'] or {}).get('cost_usd', 0) for r in rs):.4f}" if rs[0].get("llm") else "-"
        for tier in ("lite", "medium", "heavy"):
            row(c, tier, [r["eval"][tier] for r in rs], M([r["wall_s"] for r in rs]), usd)
    L += ["", "| config | tier admitted (lite/medium/heavy, of seeds) | pool candidates evaluated | guard-blocked plans | "
          "plans LLM / scripted | malformed mutations | LLM calls (cache hits) |", "|---|---|---|---|---|---|---|"]
    for c in dict.fromkeys(r["config"] for r in r6):
        rs = [r for r in r6 if r["config"] == c]
        adm = "/".join(str(sum(r["admission"][t]["admitted"] and r["admission"][t]["id"] != "h0" for r in rs))
                       for t in ("lite", "medium", "heavy"))
        P = lambda k: sum(r["planner_stats"][k] for r in rs)
        llm = f"{sum(r['llm']['calls'] for r in rs)} ({sum(r['llm']['cache_hits'] for r in rs)})" if rs[0].get("llm") else "-"
        L.append(f"| {c} | {adm} | {sum(r['stats']['evaluated'] for r in rs)} | {sum(r['stats']['guard_blocked'] for r in rs)} | "
                 f"{P('llm_plans')} / {P('scripted_plans')} | {P('malformed_mutations')} of {P('mutations')} | {llm} |")
    L.append("")
    for r in r6:
        if r["seed"] == seeds[0]:
            L.append(f"Tiers ({r['config']}, seed {seeds[0]}): " + "; ".join(
                f"{t}={r['tiers'][t]['id']} [{r['tiers'][t].get('desc') or 'h0'}]" for t in ("lite", "medium", "heavy")))
    if rec:
        L += ["", f"Label-free failure recall on {rec['claimed']} distinct claimed-success episodes "
              f"({rec['claimed_but_wrong']} are wrong fixes by the hidden grader):", "",
              "| signal | failure recall | false alarms on correct fixes | no signal |", "|---|---|---|---|"]
        for k in ("synth", "judge"):
            if k in rec:
                L.append(f"| {'synthesized tests (10/function, fixed)' if k == 'synth' else 'LLM judge'} | "
                         f"{100 * rec[k]['failure_recall']:.1f}% ({rec[k]['caught']}/{rec['claimed_but_wrong']}) | "
                         f"{100 * rec[k]['false_alarm']:.1f}% | {rec[k]['no_signal']} |")
    return "\n".join(L) + "\n"
