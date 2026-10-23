"""CLI: python3 -m aura_harness {bench,run,latency,guard,acceptance,source}"""
from __future__ import annotations

import argparse
import json
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
    rb = sub.add_parser("rsi-bench")
    rb.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    rb.add_argument("--n", type=int, default=400)
    rb.add_argument("--noise", type=float, default=0.0)
    rb.add_argument("--jobs", type=int, default=3)
    rb.add_argument("--out", default="runs/rsi")
    rb.add_argument("--set", default="m1", choices=["m1", "m2"])
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
    elif a.cmd == "rsi-bench":
        from .rsi.bench import run as rsib
        print(rsib(a.seeds, a.n, a.noise, a.jobs, a.out, a.set))
    elif a.cmd == "source":
        from .control import AuraHarness
        h = AuraHarness()
        print(h.source())
        h.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
