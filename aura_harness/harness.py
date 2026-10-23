"""Harness components as tables <-> code.

The live harness is code (Aura workspace defines, or a Python file for the file-edit baseline). The proposer reads it
back as a materialised decision table (TABLE), edits ONE component, and compiles that component to a new body:
Lisp for `mutate:rebind`, Python for the file-edit baseline. Both compile from the same edit, so the two backends make
identical decisions and differ only in how a change is applied, versioned and rolled back.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

NEEDS = ["search", "read", "edit", "test", "query-db", "logs"]
KINDS = ["search-results", "code-file", "test-log", "service-log", "sql-rows", "patch-result", "config"]
TOOLS = ["grep", "rg-json", "lsp-find", "cat", "sed", "apply-patch", "pytest", "pytest-q", "sql", "journal"]
ERRS = ["timeout", "rate-limit", "bad-args", "not-found"]
FACTS = ["test-cmd", "repo-layout", "db-schema"]
TKINDS = ["bugfix", "feature", "data", "triage", "refactor"]
NSUBS = [1, 2, 3, 4, 5, 6, 7]
STRATEGIES = ["none", "head", "tail", "head-tail", "grep-errors", "summarize", "fold"]
TIERS = ["compact", "lean", "standard", "deep"]          # M6 task tiers (HarnessPro profiles), cheapest first
MUTABLE = ["route-tool", "compress", "retry-limit", "memory-ttl", "delegate", "task-tier", "tool-budget"]
PROTECTED = ["context-budget", "max-steps", "allowed-tools", "sandbox-level"]
COMPONENT = {"route-tool": "route", "compress": "compress", "retry-limit": "retry", "memory-ttl": "ttl",
             "delegate": "delegate", "task-tier": "tier", "tool-budget": "hook"}


@dataclass
class Candidate:
    name: str                       # define to rebind
    value: object                   # the component's new full mapping (or a raw value for protected/raw proposals)
    why: str
    sig: str                        # evidence signature it answers
    desc: str                       # short human label, e.g. "compress test-log tail/800"
    raw_aura: str | None = None     # free-form Lisp body (LLM hook, or a naive proposer touching a protected define)
    meta: dict = field(default_factory=dict)

    def aura_body(self) -> str:
        return self.raw_aura if self.raw_aura is not None else to_lisp(self.name, self.value)

    def py_body(self) -> str | None:
        return None if self.raw_aura is not None or self.name not in MUTABLE else to_python(self.name, self.value)


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _lisp_val(v) -> str:
    if isinstance(v, (list, tuple)):
        return "(list " + " ".join(_lisp_val(x) for x in v) + ")"
    if isinstance(v, str):
        return q(v)
    return str(v)


def _default(values) -> object:
    c = Counter(repr(v) for v in values)
    best = c.most_common(1)[0][0]
    for v in values:
        if repr(v) == best:
            return v


def to_lisp(name: str, m: dict) -> str:
    """compile one component mapping into a flat-cond lambda (tables compile to flat conds)"""
    if name == "route-tool":
        d = _default(list(m.values()))
        arms = " ".join(f"((equal? need {q(k)}) {q(v)})" for k, v in m.items() if v != d)
        return f"(lambda (need) (cond {arms} (else {q(d)})))"
    if name == "compress":
        d = _default(list(m.values()))
        arms = " ".join(f"((equal? kind {q(k)}) {_lisp_val(v)})" for k, v in m.items() if list(v) != list(d))
        return f"(lambda (kind) (cond {arms} (else {_lisp_val(d)})))"
    if name == "retry-limit":
        d = _default(list(m.values()))
        arms = " ".join(f"((and (equal? tool {q(k.split('|')[0])}) (equal? err {q(k.split('|')[1])})) {v})"
                        for k, v in m.items() if v != d)
        return f"(lambda (tool err) (cond {arms} (else {d})))"
    if name == "memory-ttl":
        d = _default(list(m.values()))
        arms = " ".join(f"((equal? fact {q(k)}) {v})" for k, v in m.items() if v != d)
        return f"(lambda (fact) (cond {arms} (else {d})))"
    if name == "delegate":
        # per task kind: delegate when nsub >= threshold
        thr = delegate_thresholds(m)
        arms = " ".join(f"((and (equal? kind {q(k)}) (>= nsub {t})) \"delegate\")" for k, t in thr.items())
        return f"(lambda (kind nsub) (cond {arms} (else \"inline\")))"
    if name == "task-tier":
        d = _default(list(m.values()))
        arms = " ".join(f"((and (equal? kind {q(k.split('|')[0])}) (= nsub {k.split('|')[1]})) {q(v)})"
                        for k, v in m.items() if v != d)
        return f"(lambda (kind nsub) (cond {arms} (else {q(d)})))"
    if name == "tool-budget":
        d = _default(list(m.values()))
        arms = " ".join(f"((equal? tier {q(k)}) {_lisp_val(v)})" for k, v in m.items() if list(v) != list(d))
        return f"(lambda (tier) (cond {arms} (else {_lisp_val(d)})))"
    raise ValueError(name)


def to_python(name: str, m: dict) -> str:
    """the same component as a Python function (file-edit baseline)"""
    fn = name.replace("-", "_")
    if name == "route-tool":
        return f"def {fn}(need):\n    return {dict(m)!r}.get(need, 'cat')\n"
    if name == "compress":
        return f"def {fn}(kind):\n    return {dict((k, list(v)) for k, v in m.items())!r}.get(kind, ['head', 800])\n"
    if name == "retry-limit":
        return f"def {fn}(tool, err):\n    return {dict(m)!r}.get(tool + '|' + err, 1)\n"
    if name == "memory-ttl":
        return f"def {fn}(fact):\n    return {dict(m)!r}.get(fact, 0)\n"
    if name == "delegate":
        thr = delegate_thresholds(m)
        return (f"def {fn}(kind, nsub):\n    t = {thr!r}.get(kind)\n"
                f"    return 'delegate' if t is not None and nsub >= t else 'inline'\n")
    if name == "task-tier":
        return f"def {fn}(kind, nsub):\n    return {dict(m)!r}.get(f'{{kind}}|{{nsub}}', 'standard')\n"
    if name == "tool-budget":
        return f"def {fn}(tier):\n    return {dict((k, list(v)) for k, v in m.items())!r}.get(tier, [0, 0, 0])\n"
    raise ValueError(name)


def delegate_thresholds(m: dict) -> dict:
    thr = {}
    for k in TKINDS:
        ns = [n for n in NSUBS if m.get(f"{k}|{n}") == "delegate"]
        if ns:
            thr[k] = min(ns)
    return thr


def delegate_map(thr: dict) -> dict:
    return {f"{k}|{n}": ("delegate" if k in thr and n >= thr[k] else "inline") for k in TKINDS for n in NSUBS}


def normalize(tb: dict) -> dict:
    """TABLE json -> python table used by env.run_task"""
    t = dict(tb)
    t["compress"] = {k: list(v) for k, v in tb["compress"].items()}
    if "hook" in tb:
        t["hook"] = {k: list(v) for k, v in tb["hook"].items()}
    return t


def hook_ok(v, max_steps=30) -> bool:
    """staged tool-budget thresholds [economy strict finalize]: all 0 (hook off) or 1 <= e <= s <= f <= max_steps"""
    return (isinstance(v, list) and len(v) == 3 and all(type(x) is int for x in v)
            and (v == [0, 0, 0] or 1 <= v[0] <= v[1] <= v[2] <= max_steps))


def post_check(tb: dict, boundary: dict) -> str | None:
    """the same post-condition server.aura enforces (used by the file-edit backend)"""
    if [tb["budget"], tb["max_steps"], tb["allowed"], tb["sandbox"]] != [boundary["budget"], boundary["max_steps"],
                                                                       boundary["allowed"], boundary["sandbox"]]:
        return "protected boundary value changed"
    if any(tb["route"][n] not in boundary["allowed"] for n in NEEDS):
        return "routes to a tool outside allowed-tools"
    for k in KINDS:
        v = tb["compress"][k]
        if not (isinstance(v, list) and len(v) == 2 and v[0] in STRATEGIES and isinstance(v[1], int)
                and 50 <= v[1] <= boundary["budget"]):
            return "compress value out of range"
    if any(not (isinstance(v, int) and 0 <= v <= 5) for v in tb["retry"].values()):
        return "retry-limit out of range [0,5]"
    if any(not (isinstance(v, int) and 0 <= v <= 1000) for v in tb["ttl"].values()):
        return "memory-ttl out of range [0,1000]"
    if any(v not in ("delegate", "inline") for v in tb["delegate"].values()):
        return "delegate value not delegate|inline"
    if any(v not in TIERS for v in tb["tier"].values()):
        return "task-tier value not a tier"
    if any(not hook_ok(tb["hook"].get(t), boundary["max_steps"]) for t in TIERS):
        return "tool-budget thresholds out of range"
    return None


def seed_table() -> dict:
    """the seed harness (aura/harness_seed.aura) as a table; tests check it equals the Aura TABLE"""
    return {
        "route": {"search": "grep", "read": "cat", "edit": "sed", "test": "pytest", "query-db": "sql", "logs": "journal"},
        "compress": {k: ["head", 800] for k in KINDS},
        "retry": {f"{t}|{e}": 1 for t in TOOLS for e in ERRS},
        "ttl": {f: 0 for f in FACTS},
        "delegate": {f"{k}|{n}": "inline" for k in TKINDS for n in NSUBS},
        "tier": {f"{k}|{n}": "standard" for k in TKINDS for n in NSUBS},
        "hook": {t: [0, 0, 0] for t in TIERS},
        "budget": 4000, "max_steps": 30,
        "allowed": list(TOOLS), "sandbox": "restricted",
    }
