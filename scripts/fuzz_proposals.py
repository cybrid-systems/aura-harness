"""Differential fuzzing of proposed harness code (Round 7).

Generates random, well-typed, terminating bodies for a mutable knob define (knob-0: x in {0,1,2,3} -> [0,100])
in the guard's allowed subset: integer arithmetic, if / cond / case / and / or / not, let / let* / letrec, named-let
loops, local lambdas, list / map / filter / reverse / append / member / length / list-ref, vectors and strings.
Each body is evaluated four ways and compared with a Python reference evaluator:
  apply   APPLY through the live guard (allowlist + fuel instrumentation, mutate:rebind on the root workspace)
  trial   TRIAL ws (the same body in a forked child workspace; ROLLBACK afterwards)
  nofuel  APPLY in a second process with AURA_HARNESS_FUEL=0 (uninstrumented workspace code)
  file    plain file-level Aura (one batch file of defines, no workspace)
A path that disagrees with the reference is a miscompile in Aura or in the harness's instrumentation; a guard
block on a body the reference evaluates is a false reject.

Round 9: --gen 2 adds strings and vector loops; --shrink N reduces up to N mismatching bodies per path to a small
body that is still wrong the same way (greedy subterm replacement, reference re-derived per step; file-path bodies that
only fail after earlier defines are re-run behind a reduced context).

  python3 scripts/fuzz_proposals.py --n 300 --seed 1 --out runs/fuzz/seed1.json
  python3 scripts/fuzz_proposals.py --n 300 --seed 1 --gen 2 --shrink 5 --out runs/fuzz/v2-s1.json
"""
from __future__ import annotations

import argparse, json, os, re, threading, random, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aura_harness.control import AuraHarness, aura_env  # noqa: E402
from aura_harness.harness import Candidate  # noqa: E402

FALSE = False


class Gen:
    """v1: the Round 7 grammar (default; seeds reproduce). v2 adds strings (built by append / substring / reverse /
    named-let accumulation, read back by length / digit / comparison), vectors filled by vector-set! in a loop,
    vector<->list round trips and equal? on lists."""
    def __init__(self, r: random.Random, max_depth=5, v=1):
        self.r, self.max_depth, self.k, self.v = r, max_depth, 0, v

    def fresh(self, p):
        self.k += 1
        return f"{p}{self.k}"

    def int_(self, env, d):
        r = self.r
        ivars = [v for v, t in env if t == "int"]
        if d >= self.max_depth or r.random() < 0.15:
            return ("var", r.choice(ivars)) if ivars and r.random() < 0.6 else ("num", r.randint(-20, 20))
        c = r.choice(["arith", "arith", "mul", "div", "abs", "minmax", "if", "cond", "case", "let", "let*", "loop",
                      "len", "ref", "vec", "strlen", "lam", "letrec", "last"]
                     + (["slen", "sdigit", "sdigit", "vloop", "vloop"] if self.v >= 2 else []))
        n = lambda: self.int_(env, d + 1)
        if c == "arith": return (r.choice(["+", "-"]), n(), n())
        if c == "mul": return ("modulo", ("*", n(), n()), ("num", 9973))
        if c == "div": return (r.choice(["quotient", "remainder", "modulo"]), n(), ("+", ("num", 1), ("abs", n())))
        if c == "abs": return ("abs", n())
        if c == "minmax": return (r.choice(["min", "max"]), n(), n())
        if c == "if": return ("if", self.bool_(env, d + 1), n(), n())
        if c == "cond": return ("cond", [(self.bool_(env, d + 1), n()) for _ in range(r.randint(1, 3))], n())
        if c == "case": return ("case", ("modulo", n(), ("num", 4)), [([0, 1], n()), ([2], n())], n())
        if c == "let":
            v = self.fresh("v"); e = n()
            return ("let", [(v, e)], self.int_(env + [(v, "int")], d + 1))
        if c == "let*":
            v, w = self.fresh("v"), self.fresh("w")
            e1 = n(); e2 = self.int_(env + [(v, "int")], d + 1)
            return ("let*", [(v, e1), (w, e2)], self.int_(env + [(v, "int"), (w, "int")], d + 1))
        if c == "loop":
            i, s = self.fresh("i"), self.fresh("s")
            return ("loop", i, s, r.randint(0, 6), n(), self.int_(env + [(i, "int"), (s, "int")], d + 1))
        if c == "len": return ("length", self.list_(env, d + 1))
        if c == "ref":
            v = self.fresh("l")
            return ("let", [(v, self.list_(env, d + 1))],
                    ("if", ("null?", ("var", v)), n(), ("list-ref", ("var", v), ("modulo", n(), ("length", ("var", v))))))
        if c == "last":
            v = self.fresh("l")
            return ("let", [(v, self.list_(env, d + 1))], ("if", ("null?", ("var", v)), n(), ("last", ("var", v))))
        if c == "vec": return ("vector-ref", ("vector", n(), n(), n()), ("modulo", n(), ("num", 3)))
        if c == "strlen": return ("string-length", ("number->string", n()))
        if c == "lam":
            f, y = self.fresh("f"), self.fresh("y")
            body = self.int_(env + [(y, "int")], d + 2)
            return ("let", [(f, ("lambda", [y], body))], ("+", ("call", f, [n()]), ("call", f, [n()])))
        if c == "slen": return ("string-length", self.str_(env, d + 1))
        if c == "sdigit": return ("sdigit", self.fresh("t"), self.str_(env, d + 1), n())
        if c == "vloop":
            v, i = self.fresh("vv"), self.fresh("i")
            return ("vloop", v, i, r.randint(1, 6), self.int_(env + [(i, "int")], d + 1), n())
        if c == "letrec":
            g, m = self.fresh("g"), self.fresh("m")
            return ("letrec", g, m, n(), self.int_(env + [(m, "int")], d + 2), ("modulo", n(), ("num", 6)))
        raise AssertionError(c)

    def list_(self, env, d):
        r = self.r
        n = lambda: self.int_(env, d + 1)
        if d >= self.max_depth or r.random() < 0.3:
            return ("list", [n() for _ in range(r.randint(0, 4))])
        c = r.choice(["map", "filter", "reverse", "cons", "append"] + (["v2l"] if self.v >= 2 else []))
        if c == "v2l": return ("v2l", self.list_(env, d + 1))
        y = self.fresh("y")
        if c == "map": return ("map", ("lambda", [y], self.int_(env + [(y, "int")], d + 1)), self.list_(env, d + 1))
        if c == "filter": return ("filter", ("lambda", [y], self.bool_(env + [(y, "int")], d + 1)), self.list_(env, d + 1))
        if c == "reverse": return ("reverse", self.list_(env, d + 1))
        if c == "cons": return ("cons", n(), self.list_(env, d + 1))
        return ("append", self.list_(env, d + 1), self.list_(env, d + 1))

    def bool_(self, env, d):
        r = self.r
        n = lambda: self.int_(env, d + 1)
        c = r.choice(["cmp", "cmp", "par", "not", "andor", "null", "member"] + (["scmp", "equal"] if self.v >= 2 else [])
                     if d < self.max_depth else ["cmp"])
        if c == "scmp": return (r.choice(["string=?", "string<?", "string>?"]), self.str_(env, d + 1), self.str_(env, d + 1))
        if c == "equal": return ("equal?", self.list_(env, d + 1), self.list_(env, d + 1))
        if c == "cmp": return (r.choice(["<", ">", "=", "<=", ">="]), n(), n())
        if c == "par": return (r.choice(["even?", "odd?", "zero?", "positive?", "negative?"]), n())
        if c == "not": return ("not", self.bool_(env, d + 1))
        if c == "andor": return (r.choice(["and", "or"]), self.bool_(env, d + 1), self.bool_(env, d + 1))
        if c == "null": return ("null?", self.list_(env, d + 1))
        return ("member", n(), self.list_(env, d + 1))


    def str_(self, env, d):
        """non-empty digit strings (number->string of an abs), so substring / string->number stay total"""
        r = self.r
        n = lambda: self.int_(env, d + 1)
        if d >= self.max_depth or r.random() < 0.35:
            return ("number->string", ("abs", n()))
        c = r.choice(["sapp", "ssub", "srev", "sloop"])
        if c == "sapp": return ("string-append", self.str_(env, d + 1), self.str_(env, d + 1))
        if c == "ssub": return ("ssub", self.fresh("t"), self.str_(env, d + 1), n())
        if c == "srev": return ("srev", self.str_(env, d + 1))
        i, a = self.fresh("i"), self.fresh("a")
        return ("sloop", i, a, r.randint(0, 4), self.int_(env + [(i, "int")], d + 1))


def to_aura(e) -> str:
    t = e[0]
    if t == "num": return str(e[1])
    if t == "var": return e[1]
    if t in ("let", "let*"):
        return f"({t} (" + " ".join(f"({v} {to_aura(x)})" for v, x in e[1]) + f") {to_aura(e[2])})"
    if t == "lambda": return f"(lambda ({' '.join(e[1])}) {to_aura(e[2])})"
    if t == "call": return f"({e[1]} {' '.join(to_aura(a) for a in e[2])})"
    if t == "if": return f"(if {to_aura(e[1])} {to_aura(e[2])} {to_aura(e[3])})"
    if t == "cond": return "(cond " + " ".join(f"({to_aura(b)} {to_aura(x)})" for b, x in e[1]) + f" (else {to_aura(e[2])}))"
    if t == "case":
        return f"(case {to_aura(e[1])} " + " ".join(f"(({' '.join(map(str, ks))}) {to_aura(x)})" for ks, x in e[2]) + f" (else {to_aura(e[3])}))"
    if t == "loop":
        _, i, s, k, init, body = e
        return f"(let loop (({i} 0) ({s} {to_aura(init)})) (if (>= {i} {k}) {s} (loop (+ {i} 1) (modulo (+ {s} {to_aura(body)}) 99991))))"
    if t == "letrec":
        _, g, m, base, step, arg = e
        return f"(letrec (({g} (lambda ({m}) (if (<= {m} 0) {to_aura(base)} (+ {to_aura(step)} ({g} (- {m} 1))))))) ({g} {to_aura(arg)}))"
    if t == "sdigit":       # one digit of a non-empty digit string
        _, v, S, N = e
        return f"(let (({v} {to_aura(S)})) (let (({v}j (modulo {to_aura(N)} (string-length {v})))) (string->number (substring {v} {v}j (+ {v}j 1)))))"
    if t == "ssub":         # non-empty prefix
        _, v, S, N = e
        return f"(let (({v} {to_aura(S)})) (substring {v} 0 (+ 1 (modulo {to_aura(N)} (string-length {v})))))"
    if t == "srev": return f"(list->string (reverse (string->list {to_aura(e[1])})))"
    if t == "sloop":
        _, i, a, k, E = e
        return f'(let loop (({i} 0) ({a} "0")) (if (>= {i} {k}) {a} (loop (+ {i} 1) (string-append {a} (number->string (abs {to_aura(E)}))))))'
    if t == "vloop":        # vector filled by vector-set! in a named let, then read back
        _, v, i, k, E, N = e
        return (f"(let (({v} (make-vector {k} 0))) (let loop (({i} 0)) (if (< {i} {k}) (begin (vector-set! {v} {i} {to_aura(E)}) (loop (+ {i} 1)))"
                f" (vector-ref {v} (modulo {to_aura(N)} {k})))))")
    if t == "v2l": return f"(vector->list (list->vector {to_aura(e[1])}))"
    if t == "list": return "(list" + "".join(" " + to_aura(x) for x in e[1]) + ")"
    if t == "vector": return "(vector " + " ".join(to_aura(x) for x in e[1:]) + ")"
    return "(" + t + "".join(" " + to_aura(x) for x in e[1:]) + ")"


def tdiv(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def ev(e, env):
    t = e[0]
    E = lambda x: ev(x, env)
    if t == "num": return e[1]
    if t == "var": return env[e[1]]
    if t == "+": return E(e[1]) + E(e[2])
    if t == "-": return E(e[1]) - E(e[2])
    if t == "*": return E(e[1]) * E(e[2])
    if t == "modulo": a, b = E(e[1]), E(e[2]); return a % b if b > 0 else -((-a) % (-b))
    if t == "quotient": return tdiv(E(e[1]), E(e[2]))
    if t == "remainder": a, b = E(e[1]), E(e[2]); return a - b * tdiv(a, b)
    if t == "abs": return abs(E(e[1]))
    if t == "min": return min(E(e[1]), E(e[2]))
    if t == "max": return max(E(e[1]), E(e[2]))
    if t == "if": return E(e[2]) if truthy(E(e[1])) else E(e[3])
    if t == "cond":
        for b, x in e[1]:
            if truthy(E(b)): return E(x)
        return E(e[2])
    if t == "case":
        k = E(e[1])
        for ks, x in e[2]:
            if k in ks: return E(x)
        return E(e[3])
    if t == "let":
        env2 = dict(env); env2.update({v: E(x) for v, x in e[1]}); return ev(e[2], env2)
    if t == "let*":
        env2 = dict(env)
        for v, x in e[1]: env2[v] = ev(x, env2)
        return ev(e[2], env2)
    if t == "lambda": return ("closure", e[1], e[2], env)
    if t == "call": return apply_(env[e[1]], [E(a) for a in e[2]])
    if t == "loop":
        _, i, s, k, init, body = e
        iv, sv = 0, E(init)
        while iv < k:
            env2 = dict(env); env2[i] = iv; env2[s] = sv
            iv, sv = iv + 1, (sv + ev(body, env2)) % 99991
        return sv
    if t == "letrec":
        _, g, m, base, step, arg = e
        def rec(mv):
            if mv <= 0: return E(base)
            env2 = dict(env); env2[m] = mv
            return ev(step, env2) + rec(mv - 1)
        return rec(E(arg))
    if t == "length": return len(E(e[1]))
    if t == "list-ref": return E(e[1])[E(e[2])]
    if t == "last": return E(e[1])[-1]
    if t == "vector-ref": return [E(x) for x in e[1][1:]][E(e[2])]
    if t == "string-length": v = E(e[1]); return len(v if isinstance(v, str) else str(v))
    if t == "number->string": return str(E(e[1]))
    if t == "list": return [E(x) for x in e[1]]
    if t == "sdigit":
        sv = E(e[2]); j = E(e[3]) % len(sv); return int(sv[j])
    if t == "ssub":
        sv = E(e[2]); return sv[:1 + E(e[3]) % len(sv)]
    if t == "srev": return E(e[1])[::-1]
    if t == "sloop":
        _, i, a, k, X = e
        av = "0"
        for iv in range(k):
            env2 = dict(env); env2[i] = iv; av += str(abs(ev(X, env2)))
        return av
    if t == "string-append": return E(e[1]) + E(e[2])
    if t in ("string=?", "string<?", "string>?"):
        a, b = E(e[1]), E(e[2]); return {"string=?": a == b, "string<?": a < b, "string>?": a > b}[t]
    if t == "equal?": return E(e[1]) == E(e[2])
    if t == "vloop":
        _, v, i, k, X, N = e
        vec = []
        for iv in range(k):
            env2 = dict(env); env2[i] = iv; vec.append(ev(X, env2))
        return vec[E(N) % k]
    if t == "v2l": return list(E(e[1]))
    if t == "map": f = E(e[1]); return [apply_(f, [v]) for v in E(e[2])]
    if t == "filter": f = E(e[1]); return [v for v in E(e[2]) if truthy(apply_(f, [v]))]
    if t == "reverse": return list(reversed(E(e[1])))
    if t == "cons": return [E(e[1])] + E(e[2])
    if t == "append": return E(e[1]) + E(e[2])
    if t in ("<", ">", "=", "<=", ">="):
        a, b = E(e[1]), E(e[2])
        return {"<": a < b, ">": a > b, "=": a == b, "<=": a <= b, ">=": a >= b}[t]
    if t == "even?": return E(e[1]) % 2 == 0
    if t == "odd?": return E(e[1]) % 2 == 1
    if t == "zero?": return E(e[1]) == 0
    if t == "positive?": return E(e[1]) > 0
    if t == "negative?": return E(e[1]) < 0
    if t == "not": return not truthy(E(e[1]))
    if t == "and": return truthy(E(e[1])) and truthy(E(e[2]))
    if t == "or": return truthy(E(e[1])) or truthy(E(e[2]))
    if t == "null?": return E(e[1]) == []
    if t == "member":
        v, l = E(e[1]), E(e[2])
        return l[l.index(v):] if v in l else FALSE
    raise AssertionError(t)


def truthy(v):
    return v is not False


def apply_(f, args):
    _, ps, body, cenv = f
    env2 = dict(cenv); env2.update(zip(ps, args)); return ev(body, env2)


def body_src(e) -> str:
    return "(lambda (x) " + to_aura(e) + ")"


def ref_vals(e):
    """reference knob table for body e, or None if e doesn't evaluate to 4 ints in [0, 100] (shrinker candidates)"""
    try:
        vals = [ev(e, {"x": x}) for x in range(4)]
    except (RecursionError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, AssertionError):
        return None
    return vals if all(type(v) is int and 0 <= v <= 100 for v in vals) else None


def make_body(r, v=1):
    for _ in range(50):
        e = ("modulo", ("abs", Gen(r, v=v).int_([("x", "int")], 0)), ("num", 101))
        try:
            vals = [ev(e, {"x": x}) for x in range(4)]
        except RecursionError:
            continue
        src = body_src(e)
        if len(src) < 3000:
            return src, vals, e
    raise RuntimeError("generator failed")


# ---- shrinker: greedy, kind-preserving subterm replacement (Round 9) ----
LISTY = {"list", "map", "filter", "reverse", "cons", "append", "v2l"}
BOOLY = {"<", ">", "=", "<=", ">=", "even?", "odd?", "zero?", "positive?", "negative?", "not", "and", "or", "null?",
         "member", "string=?", "string<?", "string>?", "equal?"}
STRY = {"number->string", "string-append", "ssub", "srev", "sloop"}


def kind(e):
    """None for non-nodes: let bindings / loop headers are (fresh-name, ...) tuples, fresh names are letters+digits"""
    if not (isinstance(e, tuple) and e and isinstance(e[0], str)) or re.fullmatch(r"[a-z]+[0-9]+", e[0]): return None
    t = e[0]
    if t == "lambda": return "fn"
    return "list" if t in LISTY else "bool" if t in BOOLY else "str" if t in STRY else "int"


def subterms(e, path=()):
    """(path, node) for every expression node, root first (breadth-first, so big cuts are tried first)"""
    out, q = [], [(path, e)]
    while q:
        p, x = q.pop(0)
        if kind(x) is not None: out.append((p, x))
        if isinstance(x, (tuple, list)):
            for j, c in enumerate(x):
                if isinstance(c, (tuple, list)): q.append((p + (j,), c))
    return out


def replace_at(e, path, new):
    if not path: return new
    j = path[0]
    seq = list(e); seq[j] = replace_at(e[j], path[1:], new)
    return tuple(seq) if isinstance(e, tuple) else seq


def shrink_options(x):
    k = kind(x)
    opts = [c for p, c in subterms(x)[1:] if kind(c) == k]
    if k == "int": opts = [("num", 0), ("num", 1), ("var", "x")] + opts
    elif k == "list":
        opts = [("list", []), ("list", [("num", 1)])] + opts
        if x[0] == "list":       # drop one element of a literal list
            opts += [("list", x[1][:j] + x[1][j + 1:]) for j in range(len(x[1]))]
    elif k == "bool": opts = [("=", ("num", 0), ("num", 0)), ("=", ("num", 0), ("num", 1))] + opts
    elif k == "str": opts = [("number->string", ("num", 7))] + opts
    return opts


def shrink(e, still_bad, budget=300):
    """smallest body found that still_bad(e, want) accepts; returns (e, calls)"""
    calls, improved = 0, True
    while improved and calls < budget:
        improved = False
        cur = len(body_src(e))
        for p, x in subterms(e):
            for o in shrink_options(x):
                e2 = replace_at(e, p, o)
                if len(body_src(e2)) >= cur: continue
                want = ref_vals(e2)
                if want is None: continue
                calls += 1
                if still_bad(e2, want):
                    e, improved = e2, True
                    break
                if calls >= budget: break
            if improved or calls >= budget: break
    return e, calls


def knob_vals(table):
    k = table.get("knobs") if isinstance(table, dict) else None
    return list(k[0]) if k else None


def file_run(bodies, aura, env):
    with tempfile.NamedTemporaryFile("w", suffix=".aura", delete=False, dir=str(ROOT / "runs" / "fuzz")) as fh:
        for i, (src, *_) in enumerate(bodies):
            fh.write(f"(define fz{i} {src})\n")
            fh.write(f'(display (list "FZ" {i} (fz{i} 0) (fz{i} 1) (fz{i} 2) (fz{i} 3))) (newline)\n')
        path = fh.name
    p = subprocess.run([aura, path], capture_output=True, text=True, env=env, timeout=600, errors="replace")
    os.unlink(path)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith("(FZ "):
            parts = line.strip("()").split()
            try: out[int(parts[1])] = [int(x) for x in parts[2:6]]
            except ValueError: out[int(parts[1])] = parts[2:]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--paths", default="apply,trial,nofuel,file")
    ap.add_argument("--out", default="")
    ap.add_argument("--call-timeout", type=float, default=60.0, help="kill + restart the control plane after this many s per body")
    ap.add_argument("--gen", type=int, default=1, help="generator version (1 = Round 7 grammar, 2 = + strings / vector loops / equal?)")
    ap.add_argument("--shrink", type=int, default=0, help="shrink up to this many mismatching bodies per path")
    ap.add_argument("--shrink-budget", type=int, default=200, help="max candidate runs per shrunk body")
    a = ap.parse_args()
    r = random.Random(a.seed)
    bodies = [make_body(r, a.gen) for _ in range(a.n)]
    paths = a.paths.split(",")
    res = {p: {} for p in paths}
    times, runners = {}, {}
    os.environ["AURA_HARNESS_KNOBS"] = "1"
    for p in [p for p in paths if p in ("apply", "trial", "nofuel")]:
        if p == "nofuel": os.environ["AURA_HARNESS_FUEL"] = "0"
        h = AuraHarness("ws")
        os.environ.pop("AURA_HARNESS_FUEL", None)
        hs = [h]
        def run1(i, src, p=p, hs=hs):
            h = hs[0]
            c = Candidate("knob-0", None, "fuzz", "fuzz", f"fuzz {i}", raw_aura=src)
            fired = []
            def kill(h=h, fired=fired):
                fired.append(1)
                try: h.pipe.p.kill()
                except Exception: pass
            timer = threading.Timer(a.call_timeout, kill); timer.start()
            try:
                if p == "trial":
                    tr = h.trial(i, [c])[0]
                    out = knob_vals(tr["table"]) if tr.get("ok") else ("blocked", tr.get("reason"))
                    h.verdict(i, -1, [0], "fuzz")
                    return out
                ap_ = h.apply(i, c)
                return knob_vals(ap_["table"]) if ap_.get("ok") else ("blocked", ap_.get("reason"))
            except Exception as ex:      # the control plane died (or the watchdog killed it): record and restart
                try: h.close()
                except Exception: pass
                if p == "nofuel": os.environ["AURA_HARNESS_FUEL"] = "0"
                hs[0] = AuraHarness("ws"); os.environ.pop("AURA_HARNESS_FUEL", None)
                return ("timeout", f"> {a.call_timeout:g} s") if fired else ("crash", str(ex)[:300])
            finally:
                timer.cancel()
        t0 = time.perf_counter()
        for i, (src, *_) in enumerate(bodies):
            res[p][i] = run1(i, src)
        times[p] = round(time.perf_counter() - t0, 2)
        runners[p] = (run1, hs)
    aura, env = aura_env()
    runners["file"] = (lambda i, src: file_run([(src,)], aura, env).get(0, ("missing",)), None)
    if "file" in paths:
        t0 = time.perf_counter()
        fr = file_run(bodies, aura, env)
        res["file"] = {i: fr.get(i, ("missing",)) for i in range(len(bodies))}
        times["file"] = round(time.perf_counter() - t0, 2)
    bad = []
    for i, (src, want, _) in enumerate(bodies):
        got = {p: res[p].get(i) for p in paths}
        wrong = {p: g for p, g in got.items() if g != want}
        if wrong:
            bad.append({"i": i, "want": want, "wrong": wrong, "src": src})
    shrunk, ids = {}, iter(range(100000, 10**9))
    if a.shrink:
        for p in paths:
            run1 = runners[p][0]
            for b in [b for b in bad if p in b["wrong"] and not (isinstance(b["wrong"][p], (tuple, list)) and b["wrong"][p] and b["wrong"][p][0] == "timeout")][:a.shrink]:
                g0 = b["wrong"][p]
                cls = "value" if isinstance(g0, list) else str(g0[0])
                def still_bad(e, want, run1=run1, cls=cls, g0=g0):
                    g = run1(next(ids), body_src(e))
                    if g == want: return False
                    if cls == "value": return isinstance(g, list)
                    return isinstance(g, (tuple, list)) and len(g) > 0 and g[0] == g0[0] and str(g[1:2])[:40] == str(g0[1:2])[:40]
                t0 = time.perf_counter()
                e0 = bodies[b["i"]][2]
                ctx = None
                if not still_bad(e0, b["want"]) and p == "file":
                    # file batches are one process: the body may only fail after the defines before it. Re-run it
                    # behind them; if that fails, drop context chunks (halves, quarters, ...) while it still fails.
                    ctx = [bodies[j][0] for j in range(b["i"])]
                    def in_ctx(src, ctx_):
                        return file_run([(c,) for c in ctx_] + [(src,)], aura, env).get(len(ctx_), ("missing",))
                    def bad_ctx(ctx_, e, want, cls=cls, g0=g0):
                        g = in_ctx(body_src(e), ctx_)
                        if g == want: return False
                        return isinstance(g, list) if cls == "value" else (isinstance(g, (tuple, list)) and g and g[0] == g0[0])
                    if bad_ctx(ctx, e0, b["want"]):
                        k = 2
                        while len(ctx) >= 1 and k <= 2 * max(1, len(ctx)):
                            step = max(1, len(ctx) // k); cut = False
                            for lo in range(0, len(ctx), step):
                                c2 = ctx[:lo] + ctx[lo + step:]
                                if bad_ctx(c2, e0, b["want"]):
                                    ctx, cut = c2, True
                                    break
                            if not cut:
                                if step == 1: break
                                k *= 2
                        still_bad = lambda e, want, ctx=ctx: bad_ctx(ctx, e, want)
                    else:
                        ctx = None
                if ctx is None and not still_bad(e0, b["want"]):
                    b.setdefault("shrunk", {})[p] = {"repro": False}
                    shrunk.setdefault(p, []).append({"i": b["i"], "repro": False})
                    continue
                e1, calls = shrink(e0, still_bad, a.shrink_budget)
                w1 = ref_vals(e1)
                got1 = in_ctx(body_src(e1), ctx) if ctx is not None else run1(next(ids), body_src(e1))
                rec = {"i": b["i"], "repro": True, "src": body_src(e1), "want": w1, "got": got1,
                       "calls": calls, "chars": [len(b["src"]), len(body_src(e1))], "s": round(time.perf_counter() - t0, 1)}
                if ctx is not None: rec["context"] = ctx
                b.setdefault("shrunk", {})[p] = rec
                shrunk.setdefault(p, []).append(rec)
    summ = {"n": a.n, "seed": a.seed, "times_s": times,
            "mismatch": {p: sum(1 for b in bad if p in b["wrong"]) for p in paths},
            "blocked": {p: sum(1 for v in res[p].values() if isinstance(v, (tuple, list)) and v and v[0] == "blocked") for p in paths},
            "crash": {p: sum(1 for v in res[p].values() if isinstance(v, (tuple, list)) and v and v[0] == "crash") for p in paths},
            "timeout": {p: sum(1 for v in res[p].values() if isinstance(v, (tuple, list)) and v and v[0] == "timeout") for p in paths},
            "gen": a.gen}
    if a.shrink:
        summ["shrunk"] = {p: {"tried": len(v), "repro": sum(1 for x in v if x["repro"])} for p, v in shrunk.items()}
    for p, (run1, hs) in runners.items():
        if hs:
            try: hs[0].close()
            except Exception: pass
    print(json.dumps(summ))
    for p, v in shrunk.items():
        for x in v:
            if x["repro"]:
                cx = f" after {len(x['context'])} context defines" if "context" in x else " (isolated)"
                print(f"SHRUNK {p} #{x['i']} {x['chars'][0]}->{x['chars'][1]} chars{cx}, {x['calls']} runs: {x['src']}  want {x['want']} got {x['got']}")
            else: print(f"SHRUNK {p} #{x['i']}: does not reproduce in isolation")
    for b in bad[:8]:
        print(json.dumps({k: b[k] for k in ("i", "want", "wrong")})[:600])
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summ, "bad": bad}, indent=1))


if __name__ == "__main__":
    main()
