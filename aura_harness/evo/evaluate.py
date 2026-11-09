"""Host-side simulator: genome -> (held-out success, tokens/task, latency).

Success and tokens are the bench's own metrics (aura_harness/env.py). Latency
is a deterministic model of the harness's own overhead, so the third objective
is reproducible across runs:

    latency_ms = 12 * steps + 40 * retries + 25 * delegated_subtasks
                 + 60 * summarize_calls

Steps, retries and delegation are trajectory facts; summarize_calls counts
model calls whose output kind is compressed with the summarize strategy (the
summarizer is the one compression path that spends an extra model call).
"""
from __future__ import annotations

import statistics

from ..env import Memory, make_stream, run_task
from ..harness import post_check, seed_table

STEP_MS = 12.0
RETRY_MS = 40.0
DELEGATE_MS = 25.0
SUMMARIZE_MS = 60.0


def latency_of(ep, table: dict) -> float:
    ms = STEP_MS * ep.steps + RETRY_MS * sum(ep.retry_tools.values())
    if ep.delegated:
        ms += DELEGATE_MS * max(1, ep.task.nsub)
    for _need, _tool, kind, _att in ep.calls:
        strat = table["compress"].get(kind, ["head", 800])[0]
        if strat == "summarize":
            ms += SUMMARIZE_MS
    return ms


def evaluate(table: dict, seeds=(0, 1, 2, 3, 4), n: int = 400, shift: int = 200) -> dict:
    """Success on held-out tasks; tokens over ALL tasks (the bench's cost_per_task
    basis, which is what the README's 8,377 number is); latency over held-out.

    Both token bases are returned: 'tokens' (all tasks, comparable to 8,377) and
    'tokens_heldout' (held-out only, used for the per-seed breakdown).
    """
    ok = tot = cost_all = n_all = cost_held = 0
    lat: list[float] = []
    per_seed = {}
    for s in seeds:
        mem = Memory(s)
        sok = sn = sall = shall = sheld = 0
        slat = []
        for t in make_stream(s, n, shift):
            ep = run_task(t, table, mem, s, shift)
            sall += 1
            shall += ep.cost
            if t.heldout:
                sn += 1
                sok += ep.success
                sheld += ep.cost
                slat.append(latency_of(ep, table))
        per_seed[s] = {"success": sok / sn if sn else 0.0,
                       "tokens": shall / sall if sall else 0.0,
                       "latency": statistics.mean(slat) if slat else 0.0}
        ok += sok
        tot += sn
        cost_all += shall
        n_all += sall
        cost_held += sheld
        lat.extend(slat)
    return {"success": ok / tot if tot else 0.0,
            "tokens": cost_all / n_all if n_all else 0.0,
            "tokens_heldout": cost_held / tot if tot else 0.0,
            "latency": statistics.mean(lat) if lat else 0.0,
            "n": tot, "n_all": n_all, "per_seed": per_seed}


def check(table: dict, boundary: dict) -> str | None:
    return post_check(table, boundary)


def boundary_of(tb: dict | None = None) -> dict:
    tb = tb or seed_table()
    return {"budget": tb["budget"], "max_steps": tb["max_steps"],
            "allowed": list(tb["allowed"]), "sandbox": tb["sandbox"]}


# ── the gated baseline, reconstructed from the bench's kept mutations ──
def table_from_kept(kept: list[str], base: dict | None = None) -> dict:
    """Apply the bench's kept-mutation descriptions to the seed table.

    The descriptions are exactly what aura_harness/proposer.py emits, e.g.
    "compress code-file head/1600", "ttl test-cmd=40", "route search->rg-json",
    "delegate refactor>=4", "retry sql|rate-limit=3".
    """
    tb = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
          for k, v in (base or seed_table()).items()}
    for d in kept:
        if d.startswith("compress "):
            _, kind, val = d.split()
            strat, lim = val.split("/")
            tb["compress"][kind] = [strat, int(lim)]
        elif d.startswith("route "):
            _, r = d.split()
            need, tool = r.split("->")
            tb["route"][need] = tool
        elif d.startswith("ttl "):
            _, f = d.split()
            fact, n = f.split("=")
            tb["ttl"][fact] = int(n)
        elif d.startswith("retry "):
            _, r = d.split()
            pair, n = r.split("=")
            tb["retry"][pair] = int(n)
        elif d.startswith("delegate "):
            _, r = d.split()
            kind, thr = r.split(">=")
            for n in range(1, 8):
                tb["delegate"][f"{kind}|{n}"] = "delegate" if n >= int(thr) else "inline"
        elif d.startswith("inline "):
            kind = d.split()[1]
            for n in range(1, 8):
                tb["delegate"][f"{kind}|{n}"] = "inline"
        else:
            raise ValueError(f"unknown kept description: {d}")
    return tb


def baseline_point(results: list[dict], seeds=(0, 1, 2, 3, 4)) -> dict:
    """The gated loop's five final tables, each re-scored on the same five streams.

    Returns the mean objective vector, i.e. the point the Pareto front must
    weakly dominate. Also returns the per-table vectors for the report.
    """
    pts = []
    for r in results:
        tb = table_from_kept(r["kept"])
        m = evaluate(tb, seeds)
        pts.append({"seed": r["seed"], "kept": r["kept"],
                    **{k: m[k] for k in ("success", "tokens", "tokens_heldout", "latency")}})
    mean = {k: statistics.mean(p[k] for p in pts) for k in ("success", "tokens", "latency")}
    return {"mean": mean, "per_table": pts}
