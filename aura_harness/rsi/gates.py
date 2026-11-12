"""Dual admission gates for one harness candidate.

Both gates have to pass before KEEP. Either failure leaves the candidate out of
the verdict, and the live harness is only updated through the existing Aura
VERDICT path (worldline trial already happened; ROLLBACK does not touch root).

Structure / intent (no model critique): the edit must be one scoped change on
the taxonomy node the evidence names. A blanket rewrite, a protected define,
or an edit that points the other way from the failure is rejected here.

Solution / harm: held-out replay must beat the live table under ``better()``,
and the edit must not be one of the legally shaped wipes ``better()`` used to
KEEP (every memory TTL cleared, every retry cleared, a compression limit
driven under the floor the closed grammar already refuses to cross).

``dual_thin`` is a stricter solution rule measured separately: a destructive
single-cell edit whose held-out win is only a few tasks and whose cost rises
more than 5% is rejected. It is off by default because that rule also drops
useful destructive edits; see results/gates/.
"""
from __future__ import annotations

from ..agent import better
from ..env import NEEDS_TOOLS, TRANSIENT
from ..harness import (
    COMPONENT,
    FACTS,
    KINDS,
    PROTECTED,
    Candidate,
    delegate_thresholds,
)

# Closed-grammar halving stops at 200 (proposer.candidates). Below that a
# "head/50" edit is in post-check range and still drops the key line.
COMPRESS_FLOOR = 200

# Failure mode -> admissible (component, edit kinds). Protected defines are
# absent on purpose: raising context-budget / max-steps is the closed
# grammar's naive proposal, and it is not a node of this taxonomy.
TAXONOMY: dict[str, dict[str, set[str]]] = {
    "tool-error": {
        "route-tool": {"reroute"},
        "retry-limit": {"raise-retry", "lower-retry", "zero-retry"},
    },
    "info-lost": {
        "compress": {"scale-limit-up", "switch-strategy", "joint-strategy-limit"},
    },
    "context-overflow": {
        "compress": {"scale-limit-down", "switch-strategy", "joint-strategy-limit"},
        "delegate": {"lower-threshold"},
    },
    "step-limit": {
        "delegate": {"lower-threshold"},
        "retry-limit": {"lower-retry", "zero-retry"},
    },
    "stale-memory": {
        "memory-ttl": {"lower-ttl", "zero-ttl"},
    },
    "handoff-loss": {
        "delegate": {"raise-threshold", "inline"},
    },
    "rediscover": {
        "memory-ttl": {"raise-ttl"},
    },
}

DESTRUCTIVE = {
    "lower-ttl", "zero-ttl", "wipe", "scale-limit-down", "lower-retry", "zero-retry",
    "raise-threshold", "inline", "blanket", "compress-floor",
}

# Known injected-harm labels. The original validation suite is the first two;
# "retry all 0" is the same shape on the retry table.
HARM_DESCS = (
    "HARM ttl all 0",
    "HARM compress all head/50",
    "HARM retry all 0",
)


def harm_candidates(tb: dict, sig: str) -> list[Candidate]:
    """Legally shaped harmful edits mixed into a proposal round.

    Values stay inside the post-check ranges, so the scope guard accepts them.
    ``sig`` is the round's real evidence signature: the edit does not follow it.
    """
    return [
        Candidate("memory-ttl", {k: 0 for k in tb["ttl"]}, "harm", sig, "HARM ttl all 0"),
        Candidate("compress", {k: ["head", 50] for k in tb["compress"]}, "harm", sig,
                  "HARM compress all head/50"),
        Candidate("retry-limit", {k: 0 for k in tb["retry"]}, "harm", sig, "HARM retry all 0"),
    ]


def parse_sig(sig: str) -> tuple[str, str]:
    mode, _, key = (sig or "").partition("|")
    return mode, key


def _norm(v):
    if isinstance(v, (list, tuple)):
        return tuple(v)
    return v


def _changes(cur: dict, new: dict) -> list[tuple]:
    keys = list(dict.fromkeys(list(cur) + list(new)))
    out = []
    for k in keys:
        a, b = _norm(cur.get(k)), _norm(new.get(k))
        if a != b:
            out.append((k, cur.get(k), new.get(k) if not isinstance(b, tuple) else list(b)))
    return out


def classify(c: Candidate, tb: dict) -> dict:
    """Diff one candidate against the live table.

    ``kind`` is an edit-kind name from the taxonomy, or ``noop`` / ``blanket``
    / ``wipe`` / ``free-form`` / ``protected``. ``cells`` lists changed keys.
    """
    if c.name in PROTECTED or c.name not in COMPONENT:
        return {"component": c.name, "kind": "protected", "cells": [], "changes": [], "task_kind": None}
    if c.raw_aura is not None or not isinstance(c.value, dict):
        return {"component": c.name, "kind": "free-form", "cells": [], "changes": [], "task_kind": None}
    cur = tb[COMPONENT[c.name]]
    changed = _changes(cur, c.value)
    cells = [k for k, _, _ in changed]
    base = {"component": c.name, "cells": cells, "changes": changed, "task_kind": None}
    if not changed:
        return dict(base, kind="noop")
    if c.name == "memory-ttl":
        if len(changed) > 1 and all(int(b) == 0 for _, _, b in changed):
            return dict(base, kind="wipe")
        if len(changed) != 1:
            return dict(base, kind="blanket")
        _, a, b = changed[0]
        if int(b) == 0 and int(a) > 0:
            return dict(base, kind="zero-ttl")
        if int(b) < int(a):
            return dict(base, kind="lower-ttl")
        if int(b) > int(a):
            return dict(base, kind="raise-ttl")
        return dict(base, kind="noop")
    if c.name == "compress":
        if len(changed) != 1:
            return dict(base, kind="blanket")
        _, a, b = changed[0]
        so, lo = a[0], int(a[1])
        sn, ln = b[0], int(b[1])
        if ln < COMPRESS_FLOOR and ln < lo:
            return dict(base, kind="compress-floor")
        if sn == so and ln > lo:
            return dict(base, kind="scale-limit-up")
        if sn == so and ln < lo:
            return dict(base, kind="scale-limit-down")
        if sn != so and ln == lo:
            return dict(base, kind="switch-strategy")
        if sn != so and ln != lo:
            return dict(base, kind="joint-strategy-limit")
        return dict(base, kind="noop")
    if c.name == "retry-limit":
        if len(changed) > 1 and all(int(b) == 0 for _, _, b in changed):
            return dict(base, kind="wipe")
        if len(changed) != 1:
            return dict(base, kind="blanket")
        _, a, b = changed[0]
        if int(b) == 0 and int(a) > 0:
            return dict(base, kind="zero-retry")
        if int(b) < int(a):
            return dict(base, kind="lower-retry")
        if int(b) > int(a):
            return dict(base, kind="raise-retry")
        return dict(base, kind="noop")
    if c.name == "route-tool":
        if len(changed) != 1:
            return dict(base, kind="blanket")
        return dict(base, kind="reroute")
    if c.name == "delegate":
        t0, t1 = delegate_thresholds(cur), delegate_thresholds(c.value)
        kinds = [k for k in sorted(set(t0) | set(t1)) if t0.get(k) != t1.get(k)]
        if len(kinds) != 1:
            return dict(base, kind="blanket" if kinds else "noop")
        k = kinds[0]
        a, b = t0.get(k), t1.get(k)
        base["task_kind"] = k
        if b is None:
            return dict(base, kind="inline")
        if a is None or b < a:
            return dict(base, kind="lower-threshold")
        return dict(base, kind="raise-threshold")
    if len(changed) != 1:
        return dict(base, kind="blanket")
    return dict(base, kind="unclassified")


def _extreme_policy(c: Candidate, tb: dict, mode: str, key: str) -> str | None:
    """Reject a whole-table extreme even when the diff happens to be one cell.

    ``ttl all 0`` is a different proposal from ``ttl <fact>=0``: the value map
    clears every fact. When some other fact is still carried, or the evidence
    is not "this fact went stale", that map contradicts the evidence. The same
    shape applies to every retry forced to 0 and every compress kind forced
    under the floor.
    """
    if not isinstance(c.value, dict):
        return None
    if c.name == "memory-ttl" and c.value and all(int(v) == 0 for v in c.value.values()):
        cleared = [k for k, v in tb["ttl"].items() if int(v) > 0 and k != key]
        if cleared or mode != "stale-memory":
            return "clears memory the evidence does not name"
    if c.name == "retry-limit" and c.value and all(int(v) == 0 for v in c.value.values()):
        others = [k for k, v in tb["retry"].items() if k != key and int(v) > 0]
        if others or mode != "tool-error":
            return "clears retries the evidence does not name"
    if c.name == "compress" and c.value and all(
            isinstance(v, (list, tuple)) and len(v) == 2 and int(v[1]) < COMPRESS_FLOOR for v in c.value.values()):
        return "compress policy is under the floor for every kind"
    return None


def _transient(mode: str, key: str) -> bool | None:
    if mode != "tool-error" or "|" not in key:
        return None
    err = key.split("|", 1)[1]
    return err in TRANSIENT


def _cells_match(edit: dict, mode: str, key: str) -> bool:
    cells = edit["cells"]
    comp = edit["component"]
    if mode == "info-lost":
        return comp == "compress" and cells == [key]
    if mode in ("stale-memory", "rediscover"):
        return comp == "memory-ttl" and cells == [key] and key in FACTS
    if mode == "tool-error":
        if "|" not in key:
            return False
        tool = key.split("|", 1)[0]
        if comp == "retry-limit":
            return cells == [key]
        if comp == "route-tool":
            need = next((n for n, ts in NEEDS_TOOLS.items() if tool in ts), None)
            return need is not None and cells == [need]
        return False
    if mode in ("context-overflow", "step-limit", "handoff-loss"):
        if comp == "delegate":
            return edit.get("task_kind") == key
        if comp == "compress" and mode == "context-overflow":
            return len(cells) == 1 and cells[0] in KINDS
        if comp == "retry-limit" and mode == "step-limit":
            return len(cells) == 1
        return False
    return False


def _direction_ok(edit: dict, mode: str, key: str) -> bool:
    kind = edit["kind"]
    allowed = TAXONOMY.get(mode, {}).get(edit["component"], ())
    if kind not in allowed:
        return False
    transient = _transient(mode, key)
    if transient is True and kind in ("lower-retry", "zero-retry"):
        return False
    if transient is False and kind == "raise-retry":
        return False
    return True


def _protected_contradiction(edit: dict, tb: dict) -> str | None:
    """Mutable edits that would still fight the protected boundary."""
    if edit["component"] == "compress":
        for _, _, new in edit["changes"]:
            if int(new[1]) > int(tb["budget"]):
                return "compress limit exceeds the protected context budget"
    if edit["component"] == "route-tool":
        allowed = set(tb["allowed"])
        for _, _, new in edit["changes"]:
            if new not in allowed:
                return "route leaves the protected tool allowlist"
    if edit["component"] == "retry-limit":
        for _, _, new in edit["changes"]:
            if not isinstance(new, int) or isinstance(new, bool) or not 0 <= int(new) <= 5:
                return "retry-limit outside the guarded range"
    if edit["component"] == "memory-ttl":
        for _, _, new in edit["changes"]:
            if not isinstance(new, int) or isinstance(new, bool) or not 0 <= int(new) <= 1000:
                return "memory-ttl outside the guarded range"
    return None


def structure_gate(c: Candidate, tb: dict) -> tuple[bool, str]:
    """Intent side. ``c.sig`` is the evidence the proposer claims to answer."""
    edit = classify(c, tb)
    if edit["kind"] == "protected":
        return False, "protected boundary"
    if edit["kind"] == "free-form":
        return False, "free-form body has no taxonomy edit"
    if edit["kind"] == "noop":
        return False, "no-op edit"
    claimed = (c.meta or {}).get("taxonomy") or {}
    if claimed:
        if claimed.get("component") not in (None, c.name):
            return False, "stated component does not match the edit"
        if claimed.get("edit") not in (None, edit["kind"]):
            return False, "stated edit kind does not match the diff"
        if claimed.get("mode") and claimed["mode"] != parse_sig(c.sig)[0]:
            return False, "stated failure mode does not match the evidence signature"
    mode, key = parse_sig(c.sig)
    extreme = _extreme_policy(c, tb, mode, key)
    if extreme:
        return False, extreme
    if mode not in TAXONOMY:
        return False, f"no taxonomy node for evidence {mode or '(empty)'}"
    if c.name not in TAXONOMY[mode]:
        return False, f"{c.name} is not a component of {mode}"
    if edit["kind"] in ("blanket", "wipe", "compress-floor"):
        return False, f"{edit['kind']} does not match a single evidence key"
    if not _direction_ok(edit, mode, key):
        return False, f"{edit['kind']} contradicts {mode}"
    if not _cells_match(edit, mode, key):
        return False, "edit does not target the evidence key"
    bad = _protected_contradiction(edit, tb)
    if bad:
        return False, bad
    return True, "aligned"


def _harm_reason(c: Candidate, tb: dict, score, base, thin: bool) -> str | None:
    edit = classify(c, tb)
    kind = edit["kind"]
    mode, key = parse_sig(c.sig)
    extreme = _extreme_policy(c, tb, mode, key)
    if extreme:
        return extreme
    if kind == "wipe" and c.name == "memory-ttl":
        return "memory wipe (ttl cleared across facts)"
    if kind == "wipe" and c.name == "retry-limit":
        return "retry wipe (every retry cleared)"
    if kind == "compress-floor":
        return f"compress limit below {COMPRESS_FLOOR}"
    if kind == "blanket":
        return "blanket edit"
    if kind == "protected":
        return "protected boundary"
    # A limit that classify called something else can still sit under the floor
    # when several cells move (blanket already returned) — single cell is covered
    # by compress-floor. Multi-cell head/50 is blanket.
    if thin and kind in DESTRUCTIVE and score is not None and base is not None:
        gain = score[0] - base[0]
        cost_ratio = score[2] / max(1, base[2])
        if gain <= 4 and cost_ratio > 1.05:
            return "destructive edit: held-out gain <=4 with cost >+5%"
    return None


def solution_gate(score, base, c: Candidate, tb: dict, thin: bool = False) -> tuple[bool, str]:
    """Result side. ``score`` and ``base`` are ``(ok, n, cost)`` on held-out tasks."""
    harm = _harm_reason(c, tb, score, base, thin)
    if harm:
        return False, harm
    if not better(score, base):
        return False, "held-out does not improve"
    return True, "improve"


def admit_index(cands: list[Candidate], ok_trials: list[dict], scores: list, base, tb: dict,
                thin: bool = False) -> tuple[int, dict]:
    """Pick the trial index to KEEP, or -1. Both gates must pass for that index.

    Among candidates that pass, the order is the same lexicographic rule as
    ``better()`` (more held-out successes, then lower cost). A candidate that
    fails either gate is skipped, not applied.
    """
    info = {"structure_reject": {}, "solution_reject": {}, "passed": []}
    best, bs = -1, base
    by_i = {r["i"]: s for r, s in zip(ok_trials, scores)}
    for r in ok_trials:
        i = r["i"]
        c = cands[i]
        s = by_i[i]
        ok_s, why_s = structure_gate(c, tb)
        if not ok_s:
            info["structure_reject"][c.desc] = why_s
            continue
        ok_r, why_r = solution_gate(s, base, c, tb, thin=thin)
        if not ok_r:
            info["solution_reject"][c.desc] = why_r
            continue
        info["passed"].append(c.desc)
        if better(s, bs):
            best, bs = i, s
    return best, info
