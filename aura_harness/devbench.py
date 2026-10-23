"""M3 bench: the RSI loop on real developer trajectories (devenv.py). Evolution on train repos, the gate on held-out
repos, then a post-hoc eval of the frozen seed harness vs the evolved one on fresh held-out-repo tasks and on an OOD
repo never used in evolution."""
from __future__ import annotations

import json
import os
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CONFIGS = {  # noqa
    "frozen seed harness": None,
    "RSI loop (M1)": {},
    "RSI + recombination (M2 pick)": {"recombine": True},
    "RSI + retention (rho=0.05)": "retention",
    "RSI + LLM proposer (M5)": {"proposer": "llm"},
    "RSI + LLM+scripted hybrid (M5)": {"proposer": "hybrid"},
    "scripted + stat admission (M5b)": {"admission": "stat"},
    "LLM + stat admission (M5b)": {"proposer": "llm", "admission": "stat"},
}
M5B = ["frozen seed harness", "RSI loop (M1)", "scripted + stat admission (M5b)", "RSI + LLM proposer (M5)",
       "LLM + stat admission (M5b)"]


def false_keeps(keeps, seed):
    """a KEEP is false if, on the independent post-hoc fresh held-out set, the table after it scores below the
    table before it, or a later KEEP reverts its component entry to the pre-change value"""
    from .harness import COMPONENT
    ev = fresh_heldout(seed)
    bad = []
    for i, k in enumerate(keeps):
        b, a = evaluate(k["before"], ev, seed)[0], evaluate(k["after"], ev, seed)[0]
        comp = [c for c in k["before"] if k["before"][c] != k["after"][c]]
        changed = {(c, e) for c in comp for e in (k["after"][c] if isinstance(k["after"][c], dict) else [None])
                   if (k["after"][c].get(e) if e else k["after"][c]) != (k["before"][c].get(e) if e else k["before"][c])}
        reverted = any(all((l["after"][c].get(e) if e else l["after"][c]) == (k["before"][c].get(e) if e else k["before"][c])
                           for c, e in changed) and changed for l in keeps[i + 1:]) if changed else False
        if a < b or reverted:
            bad.append({"desc": k["desc"], "ts": k["ts"], "heldout_before": b, "heldout_after": a, "reverted": reverted})
    return bad
M5 = ["frozen seed harness", "RSI loop (M1)", "RSI + LLM proposer (M5)", "RSI + LLM+scripted hybrid (M5)"]


def _llm_factory(blend):
    from functools import partial
    from .rsi.llm import LLMClient, LLMProposer

    def make(**kw):
        return LLMProposer(client=LLMClient(), blend=blend, **kw)
    return make


def evaluate(table, tasks, seed):
    from .env import Memory, run_task
    mem = Memory(seed)
    ok = cost = 0
    for t in tasks:
        ep = run_task(t, table, mem, seed)
        ok += ep.success
        cost += ep.cost
    return ok / len(tasks), cost / len(tasks)


def fresh_heldout(seed, n=40):
    from dataclasses import replace
    from .devenv import make_stream
    xs = [t for t in make_stream(seed + 1000, 2 * n, shift=0) if t.heldout]
    return [replace(t, id=200000 + i) for i, t in enumerate(xs)]


def one(args):
    name, seed, n, shift = args
    from .devenv import ood_tasks
    from .harness import seed_table
    cfg = CONFIGS[name]
    if cfg is None:
        tb = seed_table()
        from .devenv import make_stream
        st_ok, _ = evaluate(tb, make_stream(seed, n, shift), seed)
        r = {"success": st_ok, "keep": 0, "rollback": 0, "kept": [], "restarts": 0, "final_table": tb}
    else:
        from .rsi.admission import RetentionGate
        from .rsi.loop import run_rsi
        from .rsi.m2 import M2Config
        ret = RetentionGate() if cfg == "retention" else None
        cfg = dict(cfg) if isinstance(cfg, dict) else cfg
        prop = _llm_factory(cfg.pop("proposer")) if isinstance(cfg, dict) and "proposer" in cfg else None
        led = None
        if prop and os.environ.get("AURA_M5_LEDGER_DIR"):
            from .rsi.ledger import Ledger
            led = Ledger(Path(os.environ["AURA_M5_LEDGER_DIR"]) / f"{name.split()[2]}-{seed}.jsonl")
        r = run_rsi(seed, n=n, shift=shift, window=40, min_heldout=10, world="dev", retention=ret,
                    cfg=M2Config(**cfg) if isinstance(cfg, dict) else None, label=name, proposer=prop, ledger=led)
    tb = r["final_table"]
    h_ok, h_cost = evaluate(tb, fresh_heldout(seed), seed)
    o_ok, o_cost = evaluate(tb, ood_tasks(seed), seed)
    fk = false_keeps(r.get("keep_tables", []), seed)
    return {"config": name, "seed": seed, "stream_success": r["success"], "keep": r["keep"], "false_keeps": fk,
            "stat": r.get("stat"),
            "rollback": r["rollback"], "kept": r["kept"], "restarts": r["restarts"],
            "heldout_success": h_ok, "heldout_tokens": h_cost, "ood_success": o_ok, "ood_tokens": o_cost,
            "wall_s": r.get("wall_s"), "llm": r.get("llm"), "proposals": r.get("proposals")}


M3 = ["frozen seed harness", "RSI loop (M1)", "RSI + recombination (M2 pick)", "RSI + retention (rho=0.05)"]


def run(seeds=(0, 1, 2), n=160, shift=80, jobs=4, out="runs/dev", configs=None):
    configs = configs or M3
    args = [(c, s, n, shift) for c in configs for s in seeds]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(one, args))
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "results.json").write_text(json.dumps(res, indent=1))
    lines = [f"seeds {list(seeds)}, {n}-task evolution stream (test layout moves at task {shift}), "
             "eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed", "",
             "| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK | false KEEPs (rate) |",
             "|---|---|---|---|---|---|---|---|"]
    for c in configs:
        rs = [r for r in res if r["config"] == c]
        m = lambda k: st.mean(r[k] for r in rs)
        lines.append(f"| {c} | {100 * m('stream_success'):.1f}% | {100 * m('heldout_success'):.1f}% | "
                     f"{m('heldout_tokens'):,.0f} | {100 * m('ood_success'):.1f}% | {m('ood_tokens'):,.0f} | "
                     f"{m('keep'):.1f} / {m('rollback'):.1f} | "
                     f"{sum(len(r['false_keeps']) for r in rs)}/{sum(r['keep'] for r in rs)} "
                     f"({100 * sum(len(r['false_keeps']) for r in rs) / max(1, sum(r['keep'] for r in rs)):.0f}%) |")
    lr = [r for r in res if r.get("llm")]
    if lr:
        lines += ["", "| config | wall s / seed | LLM calls (cache hits) | candidates gated / KEEP by LLM / KEEP by script | "
                  "malformed responses / mutations | prompt+completion tokens | cost USD (total) |", "|---|---|---|---|---|---|---|"]
        for c in configs:
            rs = [r for r in res if r["config"] == c]
            if not rs:
                continue
            if not rs[0].get("llm"):
                lines.append(f"| {c} | {st.mean(r['wall_s'] or 0 for r in rs):.0f} | - | - | - | - | - |")
                continue
            S = lambda k: sum(r["llm"][k] for r in rs)
            lines.append(f"| {c} | {st.mean(r['wall_s'] or 0 for r in rs):.0f} | {S('calls')} ({S('cache_hits')}) | "
                         f"{S('llm_candidates')} / {S('llm_kept')} / {S('rule_kept')} | "
                         f"{S('malformed_responses')} / {S('malformed_mutations')} of {S('mutations')} | "
                         f"{S('prompt_tokens'):,}+{S('completion_tokens'):,} | {S('cost_usd'):.4f} |")
    lines += ["", "Kept edits (seed 0, RSI loop): " + "; ".join(
        next((r for r in res if r["config"] == "RSI loop (M1)" and r["seed"] == seeds[0]), {"kept": []})["kept"])]
    for r in res:
        if r.get("llm") and r["seed"] == seeds[0]:
            lines.append(f"Kept edits (seed {seeds[0]}, {r['config']}): " + "; ".join(r["kept"]))
    md = "\n".join(lines) + "\n"
    (Path(out) / "results.md").write_text(md)
    return md
