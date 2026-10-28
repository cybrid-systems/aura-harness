"""CLI: python3 -m aura_harness {bench,run,latency,guard,acceptance,source}"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aura_harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench")
    b.add_argument("--modes", nargs="+", default=["frozen", "file-reload", "aura-gated", "aura-nogate"])
    b.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    b.add_argument("--n", type=int, default=400)
    b.add_argument("--shift", type=int, default=200)
    b.add_argument("--noise", type=float, default=0.0)
    b.add_argument("--window", type=int, default=80)
    b.add_argument("--worldlines", default="ws", choices=["ws", "snap"])
    b.add_argument("--jobs", type=int, default=3)
    b.add_argument("--out", default="runs/bench")
    b.add_argument("--title", default="")
    r = sub.add_parser("run")
    r.add_argument("--mode", default="aura-gated")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--n", type=int, default=400)
    r.add_argument("--worldlines", default="ws", choices=["ws", "snap"])
    r.add_argument("--noise", type=float, default=0.0)
    lt = sub.add_parser("latency")
    lt.add_argument("--n", type=int, default=20)
    sub.add_parser("guard")
    sub.add_parser("acceptance")
    sub.add_parser("source")
    au = sub.add_parser("audit")
    au.add_argument("action", choices=["run", "list", "show", "rollback", "table"])
    au.add_argument("id", nargs="?", type=int)
    au.add_argument("--ledger", default="runs/audit/ledger.jsonl")
    au.add_argument("--seed", type=int, default=0)
    au.add_argument("--n", type=int, default=400)
    au.add_argument("--world", default="sim", choices=["sim", "dev"])
    db = sub.add_parser("dev-bench")
    db.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    db.add_argument("--n", type=int, default=160)
    db.add_argument("--jobs", type=int, default=4)
    db.add_argument("--out", default="runs/dev")
    db.add_argument("--set", default="m3", choices=["m3", "m5", "m5b"], help="m5: scripted vs LLM proposer (AURA_LLM_MODE)")
    m6 = sub.add_parser("m6-bench", help="M6: HarnessPro tiers vs M5 on dev world v2 (AURA_LLM_MODE)")
    m6.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    m6.add_argument("--n", type=int, default=160)
    m6.add_argument("--jobs", type=int, default=5)
    m6.add_argument("--out", default="results/m6")
    m6.add_argument("--skip-m5", action="store_true", help="reuse the phase-1 M5 results in --out")
    m6.add_argument("--no-recall", action="store_true")
    ti = sub.add_parser("tiers", help="M6 runtime tier choice: show lite/medium/heavy of a run, optionally deploy one")
    ti.add_argument("run_json", help="results/m6/m6-<config>-<seed>.json")
    ti.add_argument("--tier", choices=["lite", "medium", "heavy"])
    ti.add_argument("--apply", action="store_true", help="deploy --tier on a fresh Aura control plane (guarded APPLY)")
    rb = sub.add_parser("rsi-bench")
    rb.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    rb.add_argument("--n", type=int, default=400)
    rb.add_argument("--noise", type=float, default=0.0)
    rb.add_argument("--jobs", type=int, default=3)
    rb.add_argument("--out", default="runs/rsi")
    rb.add_argument("--set", default="m1", choices=["m1", "m2"])
    tr = sub.add_parser("trace", help="one traced run (RSI / swarm / supervisor) + validation, optional OTLP/JSON export")
    tr.add_argument("what", choices=["rsi", "swarm", "supervisor"])
    tr.add_argument("--seed", type=int, default=0)
    tr.add_argument("--n", type=int, default=400, help="rsi: stream tasks")
    tr.add_argument("--N", type=int, default=4, help="swarm/supervisor: workers")
    tr.add_argument("--K", type=int, default=256)
    tr.add_argument("--F", type=int, default=32)
    tr.add_argument("--otlp", help="write OTLP/JSON (ExportTraceServiceRequest) here")
    tr.add_argument("--jsonl", help="write one span per line here")
    a = ap.parse_args(argv)

    if a.cmd == "bench":
        from .bench import run, tables
        out = Path(a.out)
        res = run(a.modes, a.seeds, jobs=a.jobs, out_dir=out, n=a.n, shift=a.shift, noise=a.noise,
                  window=a.window, worldlines=a.worldlines)
        md = tables(res, a.title)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.md").write_text(md)
        (out / "results.json").write_text(json.dumps([{k: v for k, v in x.items() if k not in ("audit", "final_source")}
                                                      for x in res], indent=1))
        print(md)
    elif a.cmd == "run":
        from .agent import run_stream
        x = run_stream(a.mode, a.seed, n=a.n, worldlines=a.worldlines, noise=a.noise)
        for v in x["verdicts"]:
            print(f"t={v['ts']:3d} {v['verdict']:8s} {v['chosen'] or '':38s} why={v['why']:28s} "
                  f"blocked={v['blocked']} scores={json.dumps(v.get('scores', {}).get('base'))}")
        print(json.dumps({k: v for k, v in x.items() if k not in ("verdicts", "audit", "final_source")}, indent=1))
    elif a.cmd == "latency":
        from .latency import main as lat
        lat(a.n)
    elif a.cmd == "guard":
        from .guard import main as g
        return g()
    elif a.cmd == "acceptance":
        from .acceptance import main as acc
        return acc()
    elif a.cmd == "audit":
        from .audit import main as aud
        return aud(a)
    elif a.cmd == "dev-bench":
        from .devbench import run as devb
        from .devbench import M5, M5B
        print(devb(a.seeds, a.n, a.n // 2, a.jobs, a.out, {"m5": M5, "m5b": M5B}.get(a.set)))
    elif a.cmd == "m6-bench":
        from .m6bench import run as m6b
        print(m6b(a.seeds, a.n, a.jobs, a.out, skip_m5=a.skip_m5, do_recall=not a.no_recall))
    elif a.cmd == "tiers":
        from .rsi.m6 import deploy_tier
        r = json.loads(open(a.run_json).read())
        for t in ("lite", "medium", "heavy"):
            m = r["tiers"][t]
            print(f"{t:6s} {m['id']:6s} pr={m['pr']:.3f} tokens={m['cost']:,.0f} latency={m['latency']:.1f}s "
                  f"admitted={r['admission'][t]['admitted']}  {m.get('desc') or ''}")
        if a.tier and a.apply:
            print(json.dumps(deploy_tier(r["tiers"][a.tier]["table"], a.tier), indent=1))
    elif a.cmd == "rsi-bench":
        from .rsi.bench import run as rsib
        print(rsib(a.seeds, a.n, a.noise, a.jobs, a.out, a.set))
    elif a.cmd == "trace":
        from .obs import Tracer
        t = Tracer("aura-harness", mode=a.what, aura_bin=os.environ.get("AURA_BIN", "aura"))
        if a.what == "rsi":
            from .rsi.loop import run_rsi
            x = run_rsi(a.seed, n=a.n, tracer=t)
            res = {"kept": x.get("kept"), **x["trace"]}
        elif a.what == "swarm":
            from .swarm import run as srun
            r = srun("free", a.N, a.K, a.F, 200000, tracer=t)
            res = {"summary": t.summary(), "validation": r["trace"], "tasks_per_s": r.get("tasks-per-s")}
        else:
            from .swarm import run_supervisor
            r = run_supervisor(a.N, a.K, a.F, tracer=t)
            res = {"summary": t.summary(), "validation": r["trace"]}
        if a.otlp:
            t.write_otlp(a.otlp)
        if a.jsonl:
            t.write_jsonl(a.jsonl)
        print(json.dumps(res, indent=1, default=str))
        return 0 if (res.get("validation") or {}).get("ok") else 1
    elif a.cmd == "source":
        from .control import AuraHarness
        h = AuraHarness()
        print(h.source())
        h.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
