#!/usr/bin/env python3
"""#4946 aura-harness validation: the v0.2 evo loop against the issue's checklist.

Runs (all offline, simulated solver, no model calls):
  1. baseline reproduction: 5 seeds of the handwritten gated loop (63.4% / 8,377)
  2. MOEA/D + prop:grammar three-objective search, 5 seeds
  3. the same search with std/surrogate (prescreen + staged eval), 5 seeds
  4. the same search with two process restarts, 5 seeds, and a lineage check
  5. the real Aura scope guard (aura/server.aura) against protected defines

Usage:
  AURA_BIN=... AURA_LIB=... python3 validation/evo_validate.py [--skip-bench] [--seeds 0 1 2 3 4]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVO = ROOT / "results" / "evo"
sys.path.insert(0, str(ROOT))

BASE_SUCCESS, BASE_TOKENS = 0.634, 8377.0      # README / issue: 5-seed gated mean


def sh(cmd: list[str], env=None, timeout=3600) -> subprocess.CompletedProcess:
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=str(ROOT), env=e, capture_output=True, text=True, timeout=timeout)


def aura_bin() -> str:
    b = os.environ.get("AURA_BIN")
    if not b:
        raise SystemExit("set AURA_BIN (and AURA_LIB) to an Aura build with std/moead")
    return b


def bench(out: Path) -> dict:
    r = sh([sys.executable, "-m", "aura_harness", "bench", "--seeds", "0", "1", "2", "3", "4",
            "--jobs", "3", "--modes", "aura-gated", "--out", str(out), "--title", "baseline"])
    if r.returncode != 0:
        raise SystemExit(r.stdout[-3000:] + r.stderr[-3000:])
    return json.loads((out / "results.json").read_text())


def run_evo(tag: str, out: Path, args: list[str]) -> dict:
    r = sh([sys.executable, "-m", "aura_harness.evo", "--tag", tag, "--out", str(out)] + args)
    if r.returncode != 0:
        raise SystemExit(r.stdout[-4000:] + r.stderr[-4000:])
    return json.loads((out / "summary.json").read_text())


def load_summary(out: Path) -> dict:
    return json.loads((out / "summary.json").read_text())


def log_records(path: Path) -> list[dict]:
    recs = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            recs.append(json.loads(line))
    return recs


def lineage(path: Path, tip: str) -> dict:
    """Walk parent links from tip to a root over the persisted worldline."""
    recs = log_records(path)
    by_id = {r["id"]: r for r in recs}
    chain, missing, cur = [], [], tip
    while cur:
        r = by_id.get(cur)
        if r is None:
            missing.append(cur)
            break
        chain.append(r)
        cur = r.get("parent") or ""
        if len(chain) > 100000:
            break
    keeps = [r for r in chain if r.get("decision") == "KEEP"]
    runs = sorted({r.get("run") for r in chain})
    return {"length": len(chain), "keeps": len(keeps), "missing": missing,
            "runs": runs, "ids": [r["id"] for r in chain]}


def guard_probe() -> dict:
    """The real scope guard, in the Aura control plane."""
    from aura_harness.control import AuraHarness
    from aura_harness.harness import Candidate
    out = {"attacks": [], "ok": True}
    h = AuraHarness("snap")
    try:
        attacks = [
            ("context-budget", "(lambda () 8000)", "raise context-budget"),
            ("max-steps", "(lambda () 60)", "raise max-steps"),
            ("allowed-tools", "(lambda () (list \"grep\" \"cat\" \"shell\"))", "widen allowed-tools"),
            ("sandbox-level", "(lambda () \"none\")", "drop the sandbox"),
            ("static-check", "(lambda () #t)", "rebind the guard itself"),
        ]
        for name, body, why in attacks:
            r = h.apply(0.0, Candidate(name, None, why, "", why, raw_aura=body), actor="validation")
            out["attacks"].append({"name": name, "blocked": bool(r.get("blocked")),
                                   "reason": r.get("reason", "")})
            if not r.get("blocked"):
                out["ok"] = False
        good = h.apply(0.0, Candidate("retry-limit", {**h.table()["retry"], "cat|bad-args": 2},
                                      "valid control", "", "retry cat|bad-args=2"), actor="validation")
        out["valid_control"] = {"ok": bool(good.get("ok")), "reason": good.get("reason")}
    finally:
        h.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    ap.add_argument("--gens", type=int, default=12)
    ap.add_argument("--skip-bench", action="store_true")
    ap.add_argument("--skip-runs", action="store_true")
    ap.add_argument("--skip-moead", action="store_true")
    ap.add_argument("--skip-surrogate", action="store_true")
    ap.add_argument("--skip-restart", action="store_true")
    ap.add_argument("--jobs", type=int, default=3)
    a = ap.parse_args()
    EVO.mkdir(parents=True, exist_ok=True)
    seeds = " ".join(str(s) for s in a.seeds)
    report: dict = {"aura_bin": aura_bin(),
                    "aura_version": sh([aura_bin(), "--version"]).stdout.strip()}

    # 1 ─ baseline
    bpath = EVO / "baseline-bench.json"
    if a.skip_bench and bpath.exists():
        b = json.loads(bpath.read_text())
    else:
        b = bench(EVO / "bench")
        bpath.write_text(json.dumps(b, indent=1))
    succ = statistics.mean(r["heldout_success"] for r in b)
    tok = statistics.mean(r["cost_per_task"] for r in b)
    report["baseline"] = {"success": succ, "tokens": tok,
                          "success_each": [round(r["heldout_success"], 4) for r in b],
                          "tokens_each": [round(r["cost_per_task"], 1) for r in b],
                          "match": abs(succ - BASE_SUCCESS) < 0.002 and abs(tok - BASE_TOKENS) < 5}

    # 2 ─ MOEA/D, 5 seeds
    if not (a.skip_runs or a.skip_moead):
        # control arm: no surrogate and no staged evaluation -- every proposal
        # pays a full 5-stream evaluation
        run_evo("moead", EVO / "moead",
                ["--seeds"] + seeds.split() + ["--gens", str(a.gens), "--ask", "10",
                 "--propose", "4", "--H", "6", "--jobs", str(a.jobs), "--no-staged"])
    evo = load_summary(EVO / "moead")
    report["moead"] = evo

    # 3 ─ surrogate arm, same seeds, target HV = 95% of the plain arm
    hv_target = 0.95 * min(p["hv"] for p in evo["per_seed"])
    report["hv_target"] = hv_target
    if not (a.skip_runs or a.skip_surrogate):
        run_evo("surrogate", EVO / "moead-surrogate",
                ["--seeds"] + seeds.split() + ["--gens", str(a.gens), "--ask", "10",
                 "--propose", "4", "--H", "6", "--jobs", str(a.jobs),
                 "--surrogate", "--hv-target", str(hv_target), "--max-gens", str(2 * a.gens)])
    sur = load_summary(EVO / "moead-surrogate")
    report["surrogate"] = sur

    # 4 ─ restart arm, same seeds, twice
    if not (a.skip_runs or a.skip_restart):
        run_evo("restart", EVO / "moead-restart",
                ["--seeds"] + seeds.split() + ["--gens", str(a.gens), "--ask", "10",
                 "--propose", "4", "--H", "6", "--jobs", str(a.jobs), "--restarts", "2"])
    res = load_summary(EVO / "moead-restart")
    report["restart"] = res
    lin = []
    for p in res["per_seed"]:
        sd = EVO / "moead-restart" / f"seed{p['seed']}"
        run = json.loads((sd / "run.json").read_text())
        L = lineage(sd / "evo-log.jsonl", run["tip"])
        L["seed"] = p["seed"]
        L["restarts"] = run["restarts"]
        lin.append(L)
    report["lineage"] = lin

    # 5 ─ the real guard
    try:
        report["guard"] = guard_probe()
    except Exception as e:                      # a missing backend must show, not be hidden
        report["guard"] = {"ok": False, "error": repr(e)}

    (EVO / "validation.json").write_text(json.dumps(report, indent=1))

    # ── console verdict ────────────────────────────────────────────────
    print(f"baseline: {succ:.1%} / {tok:,.0f}  match={report['baseline']['match']}")
    print(f"moead:   all_seeds_pass={evo['all_seeds_pass']} "
          f"full_evals={evo['full_evals_total']}")
    for p in evo["per_seed"]:
        print(f"  seed {p['seed']}: dom={p['criteria']['dominates_baseline']} "
              f"cut={p['criteria']['token_cut_10']} target@{p['full_evals_to_target']}")
    print(f"surrogate: all_seeds_pass={sur['all_seeds_pass']} "
          f"full_evals={sur['full_evals_total']} target_total={sur['full_evals_to_target_total']}")
    print(f"lineage: {[(l['seed'], l['length'], l['keeps'], len(l['missing'])) for l in lin]}")
    print(f"guard: ok={report['guard'].get('ok')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
