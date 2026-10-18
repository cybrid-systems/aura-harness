"""Acceptance checks for the Aura build in AURA_BIN.

Each acceptance/<name>/repro.aura runs from its own directory; the last non-empty stdout line must equal expect.txt.
Issue repros (#4583 #4584 #4585 #4586 copied from aura-memory; #4589 merge, #4610 #4615 #4617-#4622 filed from here) FAIL while the issue\nis open on that build;
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
