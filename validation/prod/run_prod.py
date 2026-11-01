#!/usr/bin/env python3
"""Run the aura-harness production validation suite (orch/observe/fiber/COW/EDSL/GC).

Each validation/prod/pNN_*.aura file is prepended with validation/prod/lib.aura and run with
$AURA_BIN --load under a pty (Aura block-buffers stdout on a pipe) with a hard timeout.
Lines "@@check.<id>=pass|FAIL ...", "@@bench.<id>=...", "@@info.<id>=..." and "@@done=ok"
are collected into validation/results.json and validation/results.md.

  python3 validation/prod/run_prod.py            # all files, serially
  python3 validation/prod/run_prod.py v04 v06     # a subset
  VAL_TIMEOUT=300 VAL_JOBS=2 python3 validation/prod/run_prod.py

Exit status is 0 only if every file finished (@@done) and every check passed, unless
--allow-known is given, in which case checks listed in KNOWN_FAIL (open upstream issues) are
tolerated.
"""
import json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from runone import run as run_file  # noqa: E402

# check id -> upstream issue documenting the failure (filled in after filing)
KNOWN_FAIL = json.loads((HERE / "known_failures.json").read_text()) if (HERE / "known_failures.json").exists() else {}

LINE = re.compile(r"^@@([^=]+)=(.*)$")


def run_one(path: Path, timeout: int):
    lib = (HERE / "lib.aura").read_text()
    with tempfile.NamedTemporaryFile("w", suffix=".aura", delete=False, dir="/tmp") as tf:
        tf.write(lib + "\n" + path.read_text())
        tmp = tf.name
    try:
        r = run_file(tmp, timeout)
    finally:
        os.unlink(tmp)
    checks, benches, infos, done = {}, {}, {}, False
    for raw in r["out"].splitlines():
        m = LINE.match(raw.strip())
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if k.startswith("check."):
            checks[k[6:]] = v
        elif k.startswith("bench."):
            benches[k[6:]] = v
        elif k.startswith("info."):
            infos[k[5:]] = v
        elif k == "done":
            done = True
    tail = "\n".join(r["out"].splitlines()[-15:]) if not done else ""
    return {"file": path.name, "rc": r["rc"], "timed_out": r["timed_out"], "secs": round(r["secs"], 2),
            "done": done, "checks": checks, "bench": benches, "info": infos, "tail": tail}


def main(argv):
    allow_known = "--allow-known" in argv
    sel = [a for a in argv if not a.startswith("--")]
    files = sorted(p for p in HERE.glob("p[0-9]*.aura") if not sel or any(p.name.startswith(s) for s in sel))
    timeout = int(os.environ.get("VAL_TIMEOUT", "300"))
    jobs = max(1, int(os.environ.get("VAL_JOBS", "1")))
    t0 = time.time()
    with ThreadPoolExecutor(jobs) as ex:
        results = list(ex.map(lambda p: run_one(p, timeout), files))
    aura_rev = os.environ.get("AURA_REV", "")
    summary = {"aura_bin": os.environ.get("AURA_BIN", ""), "aura_rev": aura_rev,
               "wall_secs": round(time.time() - t0, 1), "files": results}
    (HERE / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    md = [f"# validation results (aura {aura_rev or '?'})", "",
          "| file | done | secs | pass | fail |", "|---|---|---|---|---|"]
    bad = 0
    for r in results:
        fails = [k for k, v in r["checks"].items() if not v.startswith("pass")]
        unexpected = [k for k in fails if not (allow_known and k in KNOWN_FAIL)]
        unfinished_ok = allow_known and ("file:" + r["file"]) in KNOWN_FAIL
        bad += len(unexpected) + (0 if r["done"] or unfinished_ok else 1)
        md.append(f"| {r['file']} | {'yes' if r['done'] else 'NO'} | {r['secs']} | {len(r['checks']) - len(fails)} | {len(fails)} |")
    md += ["", "## checks", ""]
    for r in results:
        for k, v in r["checks"].items():
            tag = "PASS" if v.startswith("pass") else ("FAIL (known: %s)" % KNOWN_FAIL[k] if k in KNOWN_FAIL else "FAIL")
            md.append(f"- `{k}`: **{tag}**" + ("" if v.startswith("pass") else f" — {v[5:]}"))
        if not r["done"]:
            kn = KNOWN_FAIL.get("file:" + r["file"])
            md.append(f"- `{r['file']}`: did not finish (rc={r['rc']} timed_out={r['timed_out']})" + (f" (known: {kn})" if kn else "") + f"\n```\n{r['tail']}\n```")
    md += ["", "## benchmarks", "", "| id | value |", "|---|---|"]
    for r in results:
        for k, v in r["bench"].items():
            md.append(f"| `{k}` | {v} |")
    md += ["", "## observations", ""]
    for r in results:
        for k, v in r["info"].items():
            md.append(f"- `{k}`: {v}")
    (HERE / "results.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
