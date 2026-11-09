"""Genome <-> harness decision table.

A genome is a fixed-length vector of floats in [0, 1]; every gene is a knob in
the *mutable* policy layer. The four protected defines (context-budget,
max-steps, allowed-tools, sandbox-level) have no gene, so no proposal and no
recombination can name them. The projection is the structural half of the hard
constraint; post_check() in the runner is the dynamic half.

Gene layout (38):
  0-5    route-tool per need          (index into NEEDS_TOOLS[need])
  6-19   compress per output kind     (strategy index, limit 50..2000) x 7
  20-29  retry-limit per (tool, err)  (0..5)
  30-32  memory-ttl per fact          (0..300)
  33-37  delegate threshold per kind  (0=inline, n=delegate when nsub>=n)
"""
from __future__ import annotations

from ..env import NEEDS_TOOLS
from ..harness import FACTS, KINDS, NEEDS, TKINDS, delegate_map, seed_table

NEED_ORDER = NEEDS
STRATS = ["none", "head", "tail", "head-tail", "grep-errors", "summarize"]
RETRY_PAIRS = [("grep", "timeout"), ("rg-json", "timeout"), ("lsp-find", "not-found"),
               ("cat", "not-found"), ("sed", "bad-args"), ("apply-patch", "bad-args"),
               ("pytest", "timeout"), ("pytest-q", "timeout"), ("sql", "rate-limit"),
               ("journal", "timeout")]
TTL_FACTS = FACTS
DELEG_KINDS = TKINDS
DIM = len(NEED_ORDER) + 2 * len(KINDS) + len(RETRY_PAIRS) + len(TTL_FACTS) + len(DELEG_KINDS)

LIMIT_LO, LIMIT_HI = 50, 2000
TTL_HI = 300
DELEG_HI = 7


def clamp(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def _idx(v: float, n: int) -> int:
    return min(n - 1, int(clamp(v) * n))


def decode(g: list[float]) -> dict:
    """genome -> decision table (the same dict env.run_task consumes)."""
    if len(g) != DIM:
        raise ValueError(f"genome dim {len(g)} != {DIM}")
    tb = seed_table()
    i = 0
    for need in NEED_ORDER:
        opts = NEEDS_TOOLS[need]
        tb["route"][need] = opts[_idx(g[i], len(opts))]
        i += 1
    for kind in KINDS:
        tb["compress"][kind] = [STRATS[_idx(g[i], len(STRATS))],
                                LIMIT_LO + int(clamp(g[i + 1]) * (LIMIT_HI - LIMIT_LO))]
        i += 2
    for tool, err in RETRY_PAIRS:
        tb["retry"][f"{tool}|{err}"] = _idx(g[i], 6)
        i += 1
    for fact in TTL_FACTS:
        tb["ttl"][fact] = int(clamp(g[i]) * TTL_HI)
        i += 1
    thr: dict[str, int] = {}
    for kind in DELEG_KINDS:
        t = _idx(g[i], DELEG_HI + 1)          # 0 = inline
        if t:
            thr[kind] = t
        i += 1
    tb["delegate"] = delegate_map(thr)
    return tb


def encode(tb: dict) -> list[float]:
    """decision table -> a genome near it (used for the seed/initial parents)."""
    g: list[float] = []
    for need in NEED_ORDER:
        opts = NEEDS_TOOLS[need]
        tool = tb["route"][need]
        g.append((opts.index(tool) if tool in opts else 0) / len(opts))
    for kind in KINDS:
        s, lim = tb["compress"][kind]
        g.append((STRATS.index(s) if s in STRATS else 1) / len(STRATS))
        g.append((int(lim) - LIMIT_LO) / (LIMIT_HI - LIMIT_LO))
    for tool, err in RETRY_PAIRS:
        g.append(int(tb["retry"].get(f"{tool}|{err}", 1)) / 6.0)
    for fact in TTL_FACTS:
        g.append(int(tb["ttl"].get(fact, 0)) / TTL_HI)
    for kind in DELEG_KINDS:
        n = min([n for n in range(1, 8) if tb["delegate"].get(f"{kind}|{n}") == "delegate"],
                default=0)
        g.append(n / (DELEG_HI + 1))
    return g


def policy_source(g: list[float]) -> str:
    """The single mutable define, in the exact text aura/evo_server.aura renders."""
    ints = [int(round(clamp(v) * 10000)) for v in g]
    return "(define (harness-policy g) (list " + " ".join(str(i) for i in ints) + "))"


def source_genome(src: str) -> list[float] | None:
    """Parse a policy define back into a genome (the driver's own parser is the reference)."""
    import re
    body = src[src.find("(list"):]
    nums = re.findall(r"-?\d+", body)
    if len(nums) != DIM:
        return None
    return [clamp(int(n) / 10000.0) for n in nums]


def describe(g: list[float]) -> list[str]:
    tb = decode(g)
    out = []
    for need in NEED_ORDER:
        out.append(f"route {need}->{tb['route'][need]}")
    for kind in KINDS:
        s, lim = tb["compress"][kind]
        out.append(f"compress {kind} {s}/{lim}")
    for tool, err in RETRY_PAIRS:
        out.append(f"retry {tool}|{err}={tb['retry'][f'{tool}|{err}']}")
    for fact in TTL_FACTS:
        out.append(f"ttl {fact}={tb['ttl'][fact]}")
    for kind in DELEG_KINDS:
        th = min([n for n in range(1, 8) if tb["delegate"][f"{kind}|{n}"] == "delegate"], default=None)
        out.append(f"delegate {kind}>={th}" if th else f"inline {kind}")
    return out


def key(g: list[float]) -> tuple:
    return tuple(int(round(clamp(v) * 10000)) for v in g)
