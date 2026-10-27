"""rsi-bench: the RSI loop over seeds and configurations (retention off / rho / strict), markdown table out."""
from __future__ import annotations

import json
import statistics as st
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CONFIGS = {
    "rsi, no retention (= legacy gated)": None,
    "rsi + retention rho=0.05, decay 50": (0.05, 50),
    "rsi + retention rho=0.02, decay 100": (0.02, 100),
    "rsi + retention strict (rho=0, no decay)": (0.0, 0),
}


M2 = {
    "M1 loop (retention off)": {},
    "+ proposal budget (4 -> 2)": {"budget": True},
    "+ critic (>= 2 projects)": {"critic": True},
    "+ pruner (every 100)": {"pruner": True},
    "+ fresh one-use validation": {"fresh": True},
    "+ library recombination": {"recombine": True},
    "all M2": {"budget": True, "critic": True, "pruner": True, "fresh": True, "recombine": True},
}
SETS = {"m1": CONFIGS, "m2": M2}


def one(args):
    name, seed, n, noise = args
    from .admission import RetentionGate
    from .loop import run_rsi
    from .m2 import M2Config
    if name in M2:
        r = run_rsi(seed, n=n, noise=noise, label=name, cfg=M2Config(**M2[name]), measure=True)
    else:
        cfg = CONFIGS[name]
        ret = RetentionGate(rho=cfg[0], decay_every=cfg[1]) if cfg else None
        r = run_rsi(seed, n=n, noise=noise, retention=ret, label=name, measure=True)
    keep = {k: r[k] for k in ("success", "heldout_success", "cost_per_task", "keep", "rollback", "windows",
                              "restarts", "library", "wall_s", "metrics")}
    keep.update(config=name, seed=seed, retention=r.get("retention"),
                m2={k: v for k, v in r["m2"].items() if k != "archive_members"})
    return keep


def run(seeds, n=400, noise=0.0, jobs=3, out="runs/rsi", which="m1"):
    CONFIGS_ = SETS[which]
    args = [(c, s, n, noise) for c in CONFIGS_ for s in seeds]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(one, args))
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "results.json").write_text(json.dumps(res, indent=1))
    if which == "m2":
        md = m2_table(res, seeds, n, noise)
        (Path(out) / "results.md").write_text(md)
        return md
    lines = [f"seeds {seeds}, {n} tasks, noise {noise}", "",
             "| config | success | held-out | window 1 / 2 / 3 / 4 | tokens / task | KEEP / ROLLBACK | retention checks / vetoes | restarts |",
             "|---|---|---|---|---|---|---|---|"]
    for c in CONFIGS:
        rs = [r for r in res if r["config"] == c]
        m = lambda k: st.mean(r[k] for r in rs)
        w = " / ".join(f"{100 * st.mean(r['windows'][i] for r in rs):.0f}" for i in range(4))
        ret = (f"{st.mean(r['retention']['checks'] for r in rs):.1f} / {st.mean(r['retention']['vetoes'] for r in rs):.1f}"
               if rs[0]["retention"] else "–")
        lines.append(f"| {c} | {100 * m('success'):.1f}% | {100 * m('heldout_success'):.1f}% | {w} | "
                     f"{m('cost_per_task'):,.0f} | {m('keep'):.1f} / {m('rollback'):.1f} | {ret} | {sum(r['restarts'] for r in rs)} |")
    from ..devbench import metrics_table
    lines += ["", metrics_table(res, list(CONFIGS))]
    md = "\n".join(lines) + "\n"
    (Path(out) / "results.md").write_text(md)
    return md


def m2_table(res, seeds, n, noise):
    lines = [f"seeds {seeds}, {n} tasks, noise {noise}", "",
             "| config | success | held-out | w3 / w4 | tokens / task | KEEP / ROLLBACK | budget cut | critic veto | "
             "fresh veto | pruned | recomb kept / offered | archive |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in M2:
        rs = [r for r in res if r["config"] == c]
        m = lambda f: st.mean(f(r) for r in rs)
        lines.append(
            f"| {c} | {100 * m(lambda r: r['success']):.1f}% | {100 * m(lambda r: r['heldout_success']):.1f}% | "
            f"{100 * m(lambda r: r['windows'][2]):.0f} / {100 * m(lambda r: r['windows'][3]):.0f} | "
            f"{m(lambda r: r['cost_per_task']):,.0f} | {m(lambda r: r['keep']):.1f} / {m(lambda r: r['rollback']):.1f} | "
            f"{m(lambda r: r['m2']['budget_cut']):.1f} | {m(lambda r: r['m2']['critic_veto']):.1f} | "
            f"{m(lambda r: r['m2']['fresh_veto']):.1f} | {m(lambda r: len(r['m2']['pruned'])):.1f} | "
            f"{m(lambda r: r['m2']['recomb_kept']):.1f} / {m(lambda r: r['m2']['recombined']):.1f} | "
            f"{m(lambda r: r['m2']['archive']):.1f} |")
    return "\n".join(lines) + "\n"
