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


def one(args):
    name, seed, n, noise = args
    from .admission import RetentionGate
    from .loop import run_rsi
    cfg = CONFIGS[name]
    ret = RetentionGate(rho=cfg[0], decay_every=cfg[1]) if cfg else None
    r = run_rsi(seed, n=n, noise=noise, retention=ret, label=name)
    keep = {k: r[k] for k in ("success", "heldout_success", "cost_per_task", "keep", "rollback", "windows",
                              "restarts", "library", "wall_s")}
    keep.update(config=name, seed=seed, retention=r.get("retention"))
    return keep


def run(seeds, n=400, noise=0.0, jobs=3, out="runs/rsi"):
    args = [(c, s, n, noise) for c in CONFIGS for s in seeds]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(one, args))
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "results.json").write_text(json.dumps(res, indent=1))
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
    md = "\n".join(lines) + "\n"
    (Path(out) / "results.md").write_text(md)
    return md
