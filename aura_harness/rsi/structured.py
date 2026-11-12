"""Structured proposer: search a fixed taxonomy, still emit one-scope edits.

The closed grammar (``aura_harness.proposer.Proposer``) emits a flat bag of
single-cell table edits, one component at a time, including the protected
budget / step raises the scope guard is meant to block.

This proposer maps the same failure evidence onto ``gates.TAXONOMY`` and
expands that tree:

  failure mode → admissible component → edit kind → one concrete edit

Edit kinds that stay inside one component can compose. The flat grammar never
emits those joints: a strategy change and a limit change are separate
candidates, so the gate cannot pick ``compress service-log grep-errors/1600``
until two KEEPs happen to line up. The joint is still one define, one scope,
and it goes through the same scope guard.

No LLM. Ranking is a fixed preference per output kind (where the key line
sits), used only to keep the expansion inside ``max_candidates``. The gate,
not this ranking, decides KEEP.
"""
from __future__ import annotations

import copy

from ..env import NEEDS_TOOLS, TRANSIENT
from ..harness import Candidate, delegate_map, delegate_thresholds
from ..proposer import ALT_STRATS, Proposer
from .gates import COMPRESS_FLOOR

# Order is preference for an info-lost key line, not a search over papers.
# test-log: the failure summary is at the end. service-log: the error is in
# the middle of a multi-thousand-token buffer, so grep-errors beats a wider head.
PREF_STRAT = {
    "test-log": ["tail", "grep-errors", "head-tail", "summarize"],
    "service-log": ["grep-errors", "head-tail", "summarize", "tail"],
    "code-file": ["summarize", "head-tail", "grep-errors", "tail"],
    "search-results": ["head-tail", "summarize", "tail", "grep-errors"],
    "sql-rows": ["summarize", "head-tail", "tail", "grep-errors"],
    "patch-result": ["head-tail", "summarize", "tail", "grep-errors"],
    "config": ["summarize", "head-tail", "tail", "grep-errors"],
}


class StructuredProposer(Proposer):
    """Same observe / evidence / noise path as the closed grammar. Only candidate generation changes.

    ``joint_kinds`` limits which output kinds get a strategy×limit joint.
    ``None`` (the default) allows every kind. Restricting the joint to
    error-line kinds only was measured (results/gates, r3) and reverted:
    held-out fell from 65.4% to 62.8%, below the closed grammar.
    """

    max_candidates = 8
    joint_kinds = None

    def candidates(self, mode, key, info, tb, sig) -> list[Candidate]:
        ranked = _expand(mode, key, info, tb, sig, self)
        ranked.sort(key=lambda rc: (rc[0], rc[1].desc))
        out, seen = [], set()
        for _rank, c in ranked:
            if c.desc in seen:
                continue
            seen.add(c.desc)
            out.append(c)
            if len(out) >= self.max_candidates:
                break
        return out


def _tag(c: Candidate, mode: str, kind: str, rank: int) -> Candidate:
    c.meta["proposer"] = "structured"
    c.meta["taxonomy"] = {
        "mode": mode,
        "component": c.name,
        "edit": kind,
        "path": [mode, c.name, kind],
        "rank": rank,
    }
    return c


def _expand(mode, key, info, tb, sig, prop: StructuredProposer) -> list[tuple[int, Candidate]]:
    out: list[tuple[int, Candidate]] = []
    why = f"{mode} {key}"

    def add(rank, kind, c: Candidate):
        out.append((rank, _tag(c, mode, kind, rank)))

    def route(rank, need, tool):
        m = dict(tb["route"])
        m[need] = tool
        add(rank, "reroute", Candidate("route-tool", m, why, sig, f"route {need}->{tool}"))

    def comp(rank, kind_edit, kind, strat, limit):
        m = copy.deepcopy(tb["compress"])
        m[kind] = [strat, int(limit)]
        add(rank, kind_edit, Candidate("compress", m, why, sig, f"compress {kind} {strat}/{int(limit)}"))

    def retry(rank, kind_edit, tool, err, n):
        m = dict(tb["retry"])
        m[f"{tool}|{err}"] = n
        add(rank, kind_edit, Candidate("retry-limit", m, why, sig, f"retry {tool}|{err}={n}"))

    def ttl(rank, kind_edit, fact, n):
        m = dict(tb["ttl"])
        m[fact] = n
        add(rank, kind_edit, Candidate("memory-ttl", m, why, sig, f"ttl {fact}={n}"))

    def deleg(rank, kind_edit, kind, thr):
        t = delegate_thresholds(tb["delegate"])
        if thr is None:
            t.pop(kind, None)
        else:
            t[kind] = thr
        desc = f"delegate {kind}>={thr}" if thr else f"inline {kind}"
        add(rank, kind_edit, Candidate("delegate", delegate_map(t), why, sig, desc))

    if mode == "tool-error":
        tool, err = key.split("|", 1)
        need = info.get("need") or next(n for n, ts in NEEDS_TOOLS.items() if tool in ts)
        need = "read" if need == "read-config" else need
        alts = sorted((t for t in NEEDS_TOOLS.get(need, []) if t != tool), key=lambda t: -prop._rate(need, t))
        cur = tb["retry"].get(key, 1)
        transient = info.get("transient", err in TRANSIENT)
        if transient:
            # Finer step than the closed grammar's +2-only jump. Both stay in range.
            if cur < 5:
                retry(0, "raise-retry", tool, err, min(cur + 1, 5))
            if cur + 1 < 5:
                retry(1, "raise-retry", tool, err, min(cur + 2, 5))
            for i, a in enumerate(alts[:2]):
                route(2 + i, need, a)
        else:
            for i, a in enumerate(alts[:2]):
                route(i, need, a)
            if cur > 0:
                retry(3, "zero-retry", tool, err, 0)
    elif mode == "info-lost":
        strat, lim = tb["compress"][key]
        lim = int(lim)
        pref = [s for s in PREF_STRAT.get(key, ALT_STRATS) if s != strat]
        if lim * 2 <= 2000:
            comp(1, "scale-limit-up", key, strat, lim * 2)
        for i, s2 in enumerate(pref):
            comp(2 + i, "switch-strategy", key, s2, lim)
        # Joint: preferred strategy at the scaled limit. One component, two attributes.
        allow_joint = prop.joint_kinds is None or key in prop.joint_kinds
        if lim * 2 <= 2000 and allow_joint:
            for i, s2 in enumerate(pref[:2]):
                comp(0 if i == 0 else 1, "joint-strategy-limit", key, s2, lim * 2)
    elif mode == "context-overflow":
        # No context-budget child. The closed grammar proposes that raise; the
        # scope guard blocks it. This search does not emit it.
        if info.get("nsub", 1) >= 2:
            deleg(0, "lower-threshold", key, max(2, info["nsub"]))
        big = info.get("biggest") or "code-file"
        strat, lim = tb["compress"][big]
        lim = int(lim)
        if lim // 2 >= COMPRESS_FLOOR:
            comp(1, "scale-limit-down", big, strat, lim // 2)
        if strat != "summarize":
            comp(2, "switch-strategy", big, "summarize", lim)
        half = lim // 2
        if strat != "summarize" and half >= COMPRESS_FLOOR:
            comp(0, "joint-strategy-limit", big, "summarize", half)
        pref = PREF_STRAT.get(big, [])
        if pref and pref[0] != strat and half >= COMPRESS_FLOOR and pref[0] != "summarize":
            comp(1, "joint-strategy-limit", big, pref[0], half)
    elif mode == "step-limit":
        if info.get("nsub", 1) >= 2:
            deleg(0, "lower-threshold", key, max(2, info["nsub"]))
        rt = info.get("retries") or {}
        if rt:
            (tool, err), _ = max(rt.items(), key=lambda kv: kv[1])
            retry(1, "zero-retry", tool, err, 0)
    elif mode == "stale-memory":
        cur = tb["ttl"].get(key, 0)
        if cur // 4 >= 5:
            ttl(0, "lower-ttl", key, cur // 4)
        ttl(1, "zero-ttl", key, 0)
    elif mode == "handoff-loss":
        t = delegate_thresholds(tb["delegate"]).get(key)
        if t is not None and t + 2 <= 7:
            deleg(0, "raise-threshold", key, t + 2)
        deleg(1, "inline", key, None)
    elif mode == "rediscover":
        cur = tb["ttl"].get(key, 0)
        if cur == 0:
            # 20 is inside the gap the closed grammar leaves between 0 and 40.
            ttl(1, "raise-ttl", key, 20)
            ttl(0, "raise-ttl", key, 40)
            ttl(2, "raise-ttl", key, 160)
        elif cur * 2 <= 1000:
            ttl(0, "raise-ttl", key, cur * 2)
            if cur + 20 <= 1000 and cur + 20 != cur * 2:
                ttl(1, "raise-ttl", key, cur + 20)
    return out
