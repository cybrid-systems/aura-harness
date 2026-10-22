"""M3 bench: the RSI loop on real developer trajectories (devenv.py). Evolution on train repos, the gate on held-out
repos, then a post-hoc eval of the frozen seed harness vs the evolved one on fresh held-out-repo tasks and on an OOD
repo never used in evolution."""
from __future__ import annotations

import json
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CONFIGS = {
    "frozen seed harness": None,
    "RSI loop (M1)": {},
    "RSI + recombination (M2 pick)": {"recombine": True},
    "RSI + retention (rho=0.05)": "retention",
}


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
        r = run_rsi(seed, n=n, shift=shift, window=40, min_heldout=10, world="dev", retention=ret,
                    cfg=M2Config(**cfg) if isinstance(cfg, dict) else None, label=name)
    tb = r["final_table"]
    h_ok, h_cost = evaluate(tb, fresh_heldout(seed), seed)
    o_ok, o_cost = evaluate(tb, ood_tasks(seed), seed)
    return {"config": name, "seed": seed, "stream_success": r["success"], "keep": r["keep"],
            "rollback": r["rollback"], "kept": r["kept"], "restarts": r["restarts"],
            "heldout_success": h_ok, "heldout_tokens": h_cost, "ood_success": o_ok, "ood_tokens": o_cost,
            "wall_s": r.get("wall_s")}


def run(seeds=(0, 1, 2), n=160, shift=80, jobs=4, out="runs/dev"):
    args = [(c, s, n, shift) for c in CONFIGS for s in seeds]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(one, args))
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "results.json").write_text(json.dumps(res, indent=1))
    lines = [f"seeds {list(seeds)}, {n}-task evolution stream (test layout moves at task {shift}), "
             "eval: 40 fresh held-out-repo tasks + 30 OOD-repo tasks per seed", "",
             "| config | stream success | held-out success | held-out tokens / task | OOD success | OOD tokens / task | KEEP / ROLLBACK |",
             "|---|---|---|---|---|---|---|"]
    for c in CONFIGS:
        rs = [r for r in res if r["config"] == c]
        m = lambda k: st.mean(r[k] for r in rs)
        lines.append(f"| {c} | {100 * m('stream_success'):.1f}% | {100 * m('heldout_success'):.1f}% | "
                     f"{m('heldout_tokens'):,.0f} | {100 * m('ood_success'):.1f}% | {m('ood_tokens'):,.0f} | "
                     f"{m('keep'):.1f} / {m('rollback'):.1f} |")
    lines += ["", "Kept edits (seed 0, RSI loop): " + "; ".join(
        next(r for r in res if r["config"] == "RSI loop (M1)" and r["seed"] == seeds[0])["kept"])]
    md = "\n".join(lines) + "\n"
    (Path(out) / "results.md").write_text(md)
    return md
