"""Multi-seed benchmark over modes -> results/<name>.json + .md tables."""
from __future__ import annotations

import json
import statistics as st
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .agent import run_stream

ORDER = ["frozen", "file-reload", "aura-gated", "aura-nogate"]
LABEL = {"frozen": "frozen harness", "file-reload": "file-edit + reload (gated)",
         "aura-gated": "**Aura, gated**", "aura-nogate": "Aura, no gate"}
FMODES = ["info-lost", "tool-error", "context-overflow", "step-limit", "stale-memory", "handoff-loss", "model-error"]


def _one(args):
    mode, seed, kw = args
    return run_stream(mode, seed, **kw)


def run(modes, seeds, jobs=3, out_dir: Path | None = None, **kw) -> list[dict]:
    args = [(m, s, kw) for m in modes for s in seeds]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(_one, args))
    if out_dir:
        for r in res:
            d = out_dir / f"{r['mode']}-seed{r['seed']}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "verdicts.json").write_text(json.dumps(r["verdicts"], indent=1))
            (d / "audit.json").write_text(json.dumps(r["audit"], indent=1))
            (d / "final_harness.txt").write_text(r["final_source"])
            (d / "metrics.json").write_text(json.dumps({k: v for k, v in r.items()
                                                        if k not in ("verdicts", "audit", "final_source")}, indent=1))
    return res


def _m(xs):
    return st.mean(xs) if xs else 0.0


def tables(res: list[dict], title: str = "") -> str:
    by = {}
    for r in res:
        by.setdefault(r["mode"], []).append(r)
    seeds = sorted({r["seed"] for r in res})
    n = res[0]["n"]
    L = [f"### {title}" if title else "", f"seeds {seeds}, {n} tasks per stream, shift at task {res[0]['shift']}", ""]
    L += ["| mode | success (mean, min–max) | window 1 / 2 / 3 / 4 | held-out tasks | tokens / task | "
          "proposals | KEEP / ROLLBACK | blocked scope attempts |", "|---|---|---|---|---|---|---|---|"]
    for m in ORDER:
        rs = by.get(m)
        if not rs:
            continue
        s = [r["success"] for r in rs]
        w = [_m([r["windows"][i] for r in rs]) for i in range(4)]
        L.append(f"| {LABEL[m]} | {100*_m(s):.1f}% ({100*min(s):.1f}–{100*max(s):.1f}) | "
                 + " / ".join(f"{100*x:.0f}" for x in w)
                 + f" | {100*_m([r['heldout_success'] for r in rs]):.1f}% | {_m([r['cost_per_task'] for r in rs]):,.0f} | "
                 f"{_m([r['proposals'] for r in rs]):.1f} | {_m([r['keep'] for r in rs]):.1f} / "
                 f"{_m([r['rollback'] for r in rs]):.1f} | {_m([r['blocked'] for r in rs]):.1f} |")
    L += ["", "Failure modes (share of all tasks):", "",
          "| mode | " + " | ".join(FMODES) + " |", "|---|" + "---|" * len(FMODES)]
    for m in ORDER:
        rs = by.get(m)
        if not rs:
            continue
        c = Counter()
        for r in rs:
            c.update(r["failure_modes"])
        L.append(f"| {LABEL[m]} | " + " | ".join(f"{100*c[f]/(n*len(rs)):.1f}%" for f in FMODES) + " |")
    L += ["", "Tokens per task by window:", "", "| mode | w1 | w2 | w3 | w4 |", "|---|---|---|---|---|"]
    for m in ORDER:
        rs = by.get(m)
        if rs:
            L.append(f"| {LABEL[m]} | " + " | ".join(f"{_m([r['cost_windows'][i] for r in rs]):,.0f}" for i in range(4)) + " |")
    L += ["", "Gate / change latency (host-measured, p50 over all seeds' events) and stream wall time:", "",
          "| mode | per change (apply or verdict) p50 | gate total p50 | trial call p50 | stream wall s (mean) |",
          "|---|---|---|---|---|"]
    for m in ORDER:
        rs = by.get(m)
        if not rs:
            continue
        ch = [r["change"]["p50_ms"] for r in rs if r["change"]]
        ga = [r["gate"]["p50_ms"] for r in rs if r["gate"]]
        tr = [r["latency"]["TRIAL"]["p50_ms"] for r in rs if r["latency"].get("TRIAL")]
        L.append(f"| {LABEL[m]} | {(_m(ch)):.1f} ms | {(_m(ga)):.0f} ms | {(_m(tr)):.0f} ms | {_m([r['wall_s'] for r in rs]):.1f} |"
                 if ch else f"| {LABEL[m]} | – | – | – | {_m([r['wall_s'] for r in rs]):.1f} |")
    L += ["", "Kept mutations (count across seeds):", ""]
    for m in ORDER:
        rs = by.get(m)
        if rs and m != "frozen":
            c = Counter(k for r in rs for k in r["kept"])
            L.append(f"* {LABEL[m]}: " + ", ".join(f"`{k}` ×{v}" for k, v in c.most_common(12)))
    return "\n".join(L) + "\n"
