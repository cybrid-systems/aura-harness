"""Runaway-proposal containment suite: proposed bodies that never terminate, recurse without bound or allocate
without bound, plus attempts to dodge the meter, and legitimate-but-busy bodies that must still pass.

Each (case, mode, fuel) runs in its own child process with a wall-clock timeout, so a hang or an OOM kill of the Aura
control plane is a recorded outcome, not the end of the suite. Modes: APPLY (guarded change on the root), TRIAL ws
(child worldline), TRIAL snap (snapshot/restore on the root). fuel=0 is the pre-R5 guard (token check only).
  python3 scripts/runaway.py --out results/runaway/runaway.json            # fuel on (default budget) and off
  python3 scripts/runaway.py --fuel 100000 --modes apply --cases loop,rec  # subset
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# name -> (define, body, expect)   expect: "reject" (must not be applied) | "pass" (legitimate, must be applied)
CASES = {
    "loop": ("route-tool", "(lambda (need) (let loop ((i 0)) (loop (+ i 1))))", "reject"),
    "rec": ("route-tool", "(lambda (need) (letrec ((f (lambda (n) (+ 1 (f (+ n 1)))))) (f 0)))", "reject"),
    "mutual": ("route-tool", "(lambda (need) (letrec ((ev (lambda (n) (od (+ n 1)))) (od (lambda (n) (ev (+ n 1))))) (ev 0)))", "reject"),
    "omega": ("route-tool", "(lambda (need) ((lambda (f) (f f)) (lambda (f) (f f))))", "reject"),
    "do": ("retry-limit", "(lambda (tool err) (do ((i 0 (+ i 1))) (#f i)))", "reject"),
    "while": ("retry-limit", "(lambda (tool err) (while #t 1))", "reject"),
    "cons-bomb": ("route-tool", "(lambda (need) (let loop ((acc (list))) (loop (cons acc acc))))", "reject"),
    "str-double": ("route-tool", '(lambda (need) (let loop ((s "x")) (loop (string-append s s))))', "reject"),
    "str-alias": ("route-tool", '(lambda (need) (let ((sa string-append)) (let loop ((s "x")) (loop (sa s s)))))', "reject"),
    "append-many": ("memory-ttl", "(lambda (fact) (length (append (list 1) (list 2 3) (list (list 4)))))", "pass"),
    "strapp-3": ("route-tool", '(lambda (need) (if (equal? (string-append "g" "r" "ep") "grep") "grep" "cat"))', "pass"),
    "vec-huge": ("route-tool", "(lambda (need) (vector-length (make-vector 2000000000 0)))", "reject"),
    "iota-huge": ("route-tool", '(lambda (need) (if (> (length (iota 300000000)) 0) "grep" "cat"))', "reject"),
    "slow-3M": ("route-tool", '(lambda (need) (let loop ((i 0)) (if (< i 3000000) (loop (+ i 1)) "grep")))', "reject"),
    "mech-cycle": ("memory-ttl", "(lambda (fact) (memory-ttl fact))", "reject"),
    "catch-fuel": ("route-tool", '(lambda (need) (try (let loop () (loop)) (catch (e) "grep")))', "reject"),
    "shadow-tick": ("route-tool", '(lambda (need) (let ((%tick (lambda () #f))) (let loop () (loop))))', "reject"),
    "clock": ("route-tool", '(lambda (need) (if (> (current-time-ms) 0) "grep" "cat"))', "reject"),
    "comment": ("route-tool", '(lambda (need) "grep") ; (set-code "")', "reject"),
    "busy-50k": ("route-tool", '(lambda (need) (let loop ((i 0)) (if (< i 50000) (loop (+ i 1)) "grep")))', "pass"),
    "vec-20k": ("memory-ttl", "(lambda (fact) (if (= (vector-length (make-vector 20000 0)) 20000) 3 0))", "pass"),
    "stdlib-fn": ("route-tool", '(lambda (need) (if (assoc need (list (list "search" 1))) "grep" "cat"))', "reject"),
    "case-table": ("route-tool", '(lambda (need) (case (string-length need) ((4) "grep") ((6) "cat") (else "sed")))', "pass"),
    "helpers": ("compress", '(lambda (kind) (let* ((n (string-length kind)) (lim (* 100 (min n 8)))) (list (if (even? n) "head" "tail") lim)))', "pass"),
}
MODES = ("apply", "ws", "snap")


def one(case: str, mode: str) -> dict:
    from aura_harness.control import AuraHarness
    from aura_harness.harness import Candidate
    name, body, _ = CASES[case]
    h = AuraHarness("snap" if mode == "snap" else "ws")
    c = Candidate(name, None, "runaway", "runaway", case, raw_aura=body)
    t = time.perf_counter()
    if mode == "apply":
        r = h.apply(1, c, actor="runaway")
    else:
        r = h.trial(1, [c], actor="runaway")[0]
        h.verdict(1, -1, [0], "runaway")
    ms = 1000 * (time.perf_counter() - t)
    alive = bool(h.pipe.call("PING").get("pong"))
    dec = h.decide("route", "search")
    h.close()
    return {"ok": bool(r.get("ok")), "reason": r.get("reason") or "", "ms": round(ms, 1), "alive": alive, "after": dec}


def run(case: str, mode: str, fuel: int, timeout: float) -> dict:
    env = dict(os.environ, AURA_HARNESS_FUEL=str(fuel))
    t = time.perf_counter()
    # own session: on timeout the whole group goes, including the spinning Aura grandchild
    p = subprocess.Popen([sys.executable, __file__, "--one", case, mode], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, cwd=ROOT, start_new_session=True)
    try:
        out, err_s = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        return {"outcome": "HANG", "ms": round(1000 * timeout), "alive": False, "reason": f"no reply in {timeout:.0f}s"}
    wall = round(1000 * (time.perf_counter() - t))
    line = [l for l in out.splitlines() if l.startswith("ONE ")]
    if not line:
        err = (err_s.strip().splitlines() or [""])[-1]
        killed = "rc=-9" in err_s
        return {"outcome": "KILLED" if killed else "CRASH", "ms": wall, "alive": False, "reason": err[:160]}
    r = json.loads(line[0][4:])
    return {"outcome": "APPLIED" if r["ok"] else "REJECTED", "ms": r["ms"], "alive": r["alive"], "reason": r["reason"],
            "after": r["after"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--one", nargs=2)
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--fuel", default="100000,0", help="comma list; 0 = pre-R5 guard")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.one:
        print("ONE " + json.dumps(one(*a.one)), flush=True)
        return
    rows = []
    for fuel in [int(x) for x in a.fuel.split(",")]:
        for case in a.cases.split(","):
            for mode in a.modes.split(","):
                r = run(case, mode, fuel, a.timeout)
                want = CASES[case][2]
                r.update(case=case, mode=mode, fuel=fuel, expect=want,
                         correct=(r["outcome"] == "APPLIED") == (want == "pass") and r["alive"])
                rows.append(r)
                print(f"fuel={fuel:<7} {case:<11} {mode:<5} {r['outcome']:<8} {r['ms']:>8} ms  alive={r['alive']!s:<5} "
                      f"{'ok ' if r['correct'] else 'BAD'} {r['reason'][:70]}", flush=True)
    summ = {}
    for fuel in sorted({r["fuel"] for r in rows}):
        rs = [r for r in rows if r["fuel"] == fuel]
        summ[str(fuel)] = {"runs": len(rs), "correct": sum(r["correct"] for r in rs),
                           "hang": sum(r["outcome"] == "HANG" for r in rs), "killed": sum(r["outcome"] == "KILLED" for r in rs),
                           "crash": sum(r["outcome"] == "CRASH" for r in rs),
                           "runaway_applied": sum(r["outcome"] == "APPLIED" and r["expect"] == "reject" for r in rs),
                           "legit_rejected": sum(r["outcome"] != "APPLIED" and r["expect"] == "pass" for r in rs),
                           "max_ms_contained": max([r["ms"] for r in rs if r["outcome"] == "REJECTED"] or [0])}
    print(json.dumps(summ, indent=1))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"aura": os.environ.get("AURA_PIN", ""), "summary": summ, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
