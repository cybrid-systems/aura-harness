"""Acceptance checks for the Aura build in AURA_BIN.

Each acceptance/<name>/repro.aura runs from its own directory; the last non-empty stdout line must equal expect.txt.
Issue repros (#4583 #4584 #4585 #4586 copied from aura-memory; #4589 merge, #4610 #4615 #4617-#4624 filed from here) FAIL while the issue\nis open on that build;
harness-cycle is aura-harness's own snapshot / rebind / restore shape and must PASS.
"""
from __future__ import annotations

import resource
import subprocess
import sys

from .control import ROOT, aura_env

CHECKS = {
    "harness-cycle": "aura-harness: child-workspace trial + snapshot trial leave the root byte-identical; keep",
    "4583": "10 rebinds next to a self-recursive define stay flat (no 4x-per-rebind blow-up)",
    "4584": "2nd call of a workspace define whose sibling uses filter runs the right define",
    "4585": "a host-program loop is not >3x slower after one set-code",
    "4586": "an error inside a map callback reaches try",
    "4583-linear": "rebind 1001-1500 of the same body costs < 1.5x rebind 1-500 (aura#4583, reopened from here)",
    "4610": "1000 deleted child-workspace trials leave root rebind cost < 1.5x (aura#4610, filed from here)",
    "4615": "rebind of f with a 4x bigger caller of f costs < 8x (aura#4615, filed from here)",
    "4617": "workspace define calling a file-level fn by name keeps its frame's vector/list (aura#4617, filed from here)",
    "4618": "set! of a global in a workspace define stores; no const-fold after set! (aura#4618, filed from here)",
    "4619": "raise in a while body / non-final when, unless reaches try (aura#4619, filed from here)",
    "4620": "100M-deep recursion raises a catchable error under a 1.5 GB cap (aura#4620, filed from here)",
    "4621": "rest parameters in a workspace define (aura#4621, filed from here)",
    "4622": "a #\\( char literal in the first form doesn't make the file runner refuse the file (aura#4622, filed from here)",
    "4623": "second identical run of a tree-walked transformer gives the same list (aura#4623, c6a18e8a5 regression, filed from here)",
    "4623-reader": "8-line recursive list reader called twice on equal input gives the same tree (aura#4623 comment)",
    "4617-last": "a workspace caller reading a define that calls std-lib last gets the right list 200/200 times (aura#4617)",
    "4624": "unbound variable inside a map callback raises (aura#4624, filed from here)",
    "4626": "two map callbacks from sibling expressions of a workspace define both run (aura#4626, filed from here)",
    "4627": "(equal? (list 1 2) want) in a tail-call loop is never #f (aura#4627, c6a18e8a5 regression, filed from here)",
    "4626-sibcall": "one inline filter callback in a workspace define called 4x from a sibling list (the knob table) keeps the element every time (aura#4626 comment)",
    "4629-vec": "a fresh (vector x 0 0) in a map callback keeps its length across 10 hot-loop calls (aura#4629 comment, c6a18e8a5 regression)",
    "4630": "workspace compile at call-chain depth 12 (2 call sites per level) costs < 2.5x depth 10 (aura#4630, filed from here)",
    "merge": "workspace :merge child overrides the parent's define (cybrid-systems/aura#4589, filed from here)",
}


# checks whose unfixed behaviour is to grow until killed run under an address-space cap (MB)
MEM_CAP = {"4620": 1536}


def run_check(name: str) -> tuple[bool, str]:
    d = ROOT / "acceptance" / name
    aura, env = aura_env()
    if (d / "lib").exists():
        env["AURA_PATH"] = str(d / "lib") + ":" + env.get("AURA_PATH", "")
    try:
        cap = MEM_CAP.get(name)
        pre = (lambda: resource.setrlimit(resource.RLIMIT_AS, (cap << 20, cap << 20))) if cap else None
        p = subprocess.run([aura, "repro.aura"], cwd=str(d), env=env, capture_output=True, text=True, timeout=120,
                           preexec_fn=pre)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    lines = [l for l in p.stdout.splitlines() if l.strip() and not l.startswith("⚠")]
    got = lines[-1].strip() if lines else f"(no output, rc={p.returncode}) {p.stderr[-200:]}"
    return got == (d / "expect.txt").read_text().strip(), got


def main() -> int:
    own_bad = 0
    for name, what in CHECKS.items():
        ok, got = run_check(name)
        if name == "harness-cycle" and not ok:
            own_bad = 1
        print(f"{'PASS' if ok else 'FAIL'}  {name:13s} {what}\n      got: {got}")
    return own_bad


if __name__ == "__main__":
    sys.exit(main())
