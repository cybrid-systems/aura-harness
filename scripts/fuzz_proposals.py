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

  python3 scripts/fuzz_proposals.py --n 300 --seed 1 --out runs/fuzz/seed1.json
"""
from __future__ import annotations

import argparse, json, os, threading, random, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from aura_harness.control import AuraHarness, aura_env  # noqa: E402
from aura_harness.harness import Candidate  # noqa: E402

FALSE = False


class Gen:
    def __init__(self, r: random.Random, max_depth=5):
        self.r, self.max_depth, self.k = r, max_depth, 0

    def fresh(self, p):
        self.k += 1
        return f"{p}{self.k}"

    def int_(self, env, d):
        r = self.r
        ivars = [v for v, t in env if t == "int"]
        if d >= self.max_depth or r.random() < 0.15:
            return ("var", r.choice(ivars)) if ivars and r.random() < 0.6 else ("num", r.randint(-20, 20))
        c = r.choice(["arith", "arith", "mul", "div", "abs", "minmax", "if", "cond", "case", "let", "let*", "loop",
                      "len", "ref", "vec", "strlen", "lam", "letrec", "last"])
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
        if c == "letrec":
            g, m = self.fresh("g"), self.fresh("m")
            return ("letrec", g, m, n(), self.int_(env + [(m, "int")], d + 2), ("modulo", n(), ("num", 6)))
        raise AssertionError(c)

    def list_(self, env, d):
        r = self.r
        n = lambda: self.int_(env, d + 1)
        if d >= self.max_depth or r.random() < 0.3:
            return ("list", [n() for _ in range(r.randint(0, 4))])
        c = r.choice(["map", "filter", "reverse", "cons", "append"])
        y = self.fresh("y")
        if c == "map": return ("map", ("lambda", [y], self.int_(env + [(y, "int")], d + 1)), self.list_(env, d + 1))
        if c == "filter": return ("filter", ("lambda", [y], self.bool_(env + [(y, "int")], d + 1)), self.list_(env, d + 1))
        if c == "reverse": return ("reverse", self.list_(env, d + 1))
        if c == "cons": return ("cons", n(), self.list_(env, d + 1))
        return ("append", self.list_(env, d + 1), self.list_(env, d + 1))

    def bool_(self, env, d):
        r = self.r
        n = lambda: self.int_(env, d + 1)
        c = r.choice(["cmp", "cmp", "par", "not", "andor", "null", "member"] if d < self.max_depth else ["cmp"])
        if c == "cmp": return (r.choice(["<", ">", "=", "<=", ">="]), n(), n())
        if c == "par": return (r.choice(["even?", "odd?", "zero?", "positive?", "negative?"]), n())
        if c == "not": return ("not", self.bool_(env, d + 1))
        if c == "andor": return (r.choice(["and", "or"]), self.bool_(env, d + 1), self.bool_(env, d + 1))
        if c == "null": return ("null?", self.list_(env, d + 1))
        return ("member", n(), self.list_(env, d + 1))


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
    if t == "string-length": return len(str(E(e[1])))
    if t == "number->string": return str(E(e[1]))
    if t == "list": return [E(x) for x in e[1]]
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


def make_body(r):
    for _ in range(50):
        e = ("modulo", ("abs", Gen(r).int_([("x", "int")], 0)), ("num", 101))
        try:
            vals = [ev(e, {"x": x}) for x in range(4)]
        except RecursionError:
            continue
        src = "(lambda (x) " + to_aura(e) + ")"
        if len(src) < 3000:
            return src, vals
    raise RuntimeError("generator failed")


def knob_vals(table):
    k = table.get("knobs") if isinstance(table, dict) else None
    return list(k[0]) if k else None


def file_run(bodies, aura, env):
    with tempfile.NamedTemporaryFile("w", suffix=".aura", delete=False, dir=str(ROOT / "runs" / "fuzz")) as fh:
        for i, (src, _) in enumerate(bodies):
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
    a = ap.parse_args()
    r = random.Random(a.seed)
    bodies = [make_body(r) for _ in range(a.n)]
    paths = a.paths.split(",")
    res = {p: {} for p in paths}
    times = {}
    os.environ["AURA_HARNESS_KNOBS"] = "1"
    for p in [p for p in paths if p in ("apply", "trial", "nofuel")]:
        if p == "nofuel": os.environ["AURA_HARNESS_FUEL"] = "0"
        h = AuraHarness("ws")
        os.environ.pop("AURA_HARNESS_FUEL", None)
        t0 = time.perf_counter()
        for i, (src, _) in enumerate(bodies):
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
                    res[p][i] = knob_vals(tr["table"]) if tr.get("ok") else ("blocked", tr.get("reason"))
                    h.verdict(i, -1, [0], "fuzz")
                else:
                    ap_ = h.apply(i, c)
                    res[p][i] = knob_vals(ap_["table"]) if ap_.get("ok") else ("blocked", ap_.get("reason"))
            except Exception as ex:      # the control plane died (or the watchdog killed it): record and restart
                res[p][i] = ("timeout", f"> {a.call_timeout:g} s") if fired else ("crash", str(ex)[:300])
                try: h.close()
                except Exception: pass
                if p == "nofuel": os.environ["AURA_HARNESS_FUEL"] = "0"
                h = AuraHarness("ws"); os.environ.pop("AURA_HARNESS_FUEL", None)
            finally:
                timer.cancel()
        times[p] = round(time.perf_counter() - t0, 2)
        h.close()
    if "file" in paths:
        aura, env = aura_env()
        t0 = time.perf_counter()
        fr = file_run(bodies, aura, env)
        res["file"] = {i: fr.get(i, ("missing",)) for i in range(len(bodies))}
        times["file"] = round(time.perf_counter() - t0, 2)
    bad = []
    for i, (src, want) in enumerate(bodies):
        got = {p: res[p].get(i) for p in paths}
        wrong = {p: g for p, g in got.items() if g != want}
        if wrong:
            bad.append({"i": i, "want": want, "wrong": wrong, "src": src})
    summ = {"n": a.n, "seed": a.seed, "times_s": times,
            "mismatch": {p: sum(1 for b in bad if p in b["wrong"]) for p in paths},
            "blocked": {p: sum(1 for v in res[p].values() if isinstance(v, (tuple, list)) and v and v[0] == "blocked") for p in paths},
            "crash": {p: sum(1 for v in res[p].values() if isinstance(v, (tuple, list)) and v and v[0] == "crash") for p in paths},
            "timeout": {p: sum(1 for v in res[p].values() if isinstance(v, (tuple, list)) and v and v[0] == "timeout") for p in paths}}
    print(json.dumps(summ))
    for b in bad[:8]:
        print(json.dumps({k: b[k] for k in ("i", "want", "wrong")})[:600])
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summ, "bad": bad}, indent=1))


if __name__ == "__main__":
    main()
