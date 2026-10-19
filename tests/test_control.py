"""Control-plane tests against a real Aura (skipped without AURA_BIN)."""
import json
import os
import random
import unittest

from aura_harness.env import Episode, Task

HAVE = bool(os.environ.get("AURA_BIN"))


def j(x):
    return json.dumps(x, sort_keys=True)


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class ControlTests(unittest.TestCase):
    def setUp(self):
        from aura_harness.control import AuraHarness
        self.h = AuraHarness("ws")

    def tearDown(self):
        self.h.close()

    def test_seed_table_matches(self):
        from aura_harness.harness import normalize, seed_table
        self.assertEqual(j(self.h.table()), j(normalize(seed_table())))

    def test_trials_leave_root_untouched_both_modes(self):
        from aura_harness.harness import Candidate
        tb = self.h.table()
        src0 = self.h.source()
        m = dict(tb["route"], search="lsp-find")
        c = Candidate("route-tool", m, "t", "t", "route search->lsp-find")
        for mode in ("ws", "snap"):
            self.h.worldlines = mode
            r = self.h.trial(1, [c])
            self.assertTrue(r[0]["ok"])
            self.assertEqual(r[0]["table"]["route"]["search"], "lsp-find")
            self.assertEqual(self.h.source(), src0, mode)
            self.assertEqual(self.h.decide("route", "search"), "grep")

    def test_keep_and_rollback_logged(self):
        from aura_harness.harness import Candidate
        tb = self.h.table()
        c = Candidate("compress", dict(tb["compress"], **{"test-log": ["tail", 800]}), "w", "s", "compress test-log tail/800")
        self.h.trial(5, [c])
        r = self.h.verdict(5, -1, {"base": [1, 2, 3]}, "w")
        self.assertEqual(r["verdict"], "ROLLBACK")
        self.assertEqual(self.h.decide("compress", "test-log"), ["head", 800])
        self.h.trial(6, [c])
        r = self.h.verdict(6, 0, {"base": [1, 2, 3]}, "w")
        self.assertEqual(r["verdict"], "KEEP")
        self.assertEqual(self.h.decide("compress", "test-log"), ["tail", 800])
        ops = [e["op"] for e in self.h.log()]
        self.assertEqual(ops, ["trial-ws", "rollback", "trial-ws", "keep"])
        # ws-mode KEEP promotes with `workspace :merge` (aura#4589 fixed): one define, no appended duplicate
        self.assertEqual(self.h.source().count("(define compress"), 1)

    def test_keep_snap_mode_reapplies(self):
        from aura_harness.harness import Candidate
        tb = self.h.table()
        self.h.worldlines = "snap"
        c = Candidate("compress", dict(tb["compress"], **{"test-log": ["tail", 800]}), "w", "s", "compress test-log tail/800")
        self.h.trial(7, [c])
        r = self.h.verdict(7, 0, {"base": [1, 2, 3]}, "w")
        self.assertEqual(r["verdict"], "KEEP")
        self.assertEqual(self.h.decide("compress", "test-log"), ["tail", 800])
        self.assertEqual(self.h.source().count("(define compress"), 1)

    def test_random_compiled_candidates_match_python(self):
        """Lisp compile (Aura) and Python compile (file baseline) give the same table for random edits"""
        from aura_harness.harness import COMPONENT, MUTABLE, NEEDS, Candidate, delegate_map, to_python, KINDS
        from aura_harness.env import NEEDS_TOOLS
        r = random.Random(7)
        for i in range(12):
            tb = self.h.table()
            name = r.choice(MUTABLE)
            v = json.loads(json.dumps(tb[COMPONENT[name]]))
            if name == "route-tool":
                n = r.choice(NEEDS)
                v[n] = r.choice(NEEDS_TOOLS[n])
            elif name == "compress":
                v[r.choice(KINDS)] = [r.choice(["tail", "head-tail", "summarize", "grep-errors"]), r.choice([400, 1600])]
            elif name == "retry-limit":
                v[r.choice(list(v))] = r.randint(0, 5)
            elif name == "memory-ttl":
                v[r.choice(list(v))] = r.choice([0, 40, 160])
            else:
                v = delegate_map({"refactor": r.randint(2, 6)})
            res = self.h.apply(i, Candidate(name, v, "rand", "rand", f"rand {i}"))
            self.assertTrue(res["ok"], res)
            ns = {}
            exec(to_python(name, v), ns)
            fn = ns[name.replace("-", "_")]
            got = res["table"][COMPONENT[name]]
            for k, want in got.items():
                args = k.split("|")
                if name == "delegate":
                    args[1] = int(args[1])
                self.assertEqual(j(fn(*args)), j(want), (name, k))

    def test_proposer_cannot_raise_its_own_budget(self):
        from aura_harness.proposer import Proposer
        p = Proposer(min_evidence=3)
        tb = self.h.table()
        cands = None
        for i in range(3):
            ep = Episode(Task(i, 1, "refactor", "api", 5, False))
            ep.mode, ep.fail = "context-overflow", {"need": "read", "tool": "cat", "kind": "code-file"}
            ep.biggest_kind = "code-file"
            cands = p.observe(ep, tb)
        self.assertEqual(cands[0].name, "context-budget")
        trials = self.h.trial(3, cands)
        self.assertFalse(trials[0]["ok"])
        self.assertIn("protected define", trials[0]["reason"])
        self.assertTrue(all(t["ok"] for t in trials[1:]))
        self.h.verdict(3, -1, {}, "test")
        self.assertEqual(self.h.decide("budget"), 4000)
        blocked = [e for e in self.h.log() if e["op"] == "blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["name"], "context-budget")
        self.assertEqual(blocked[0]["actor"], "proposer")
        p.feedback(cands[0].sig, "ROLLBACK", [cands[0].desc])
        for i in range(3, 12):
            ep = Episode(Task(i, 1, "refactor", "api", 5, False))
            ep.mode, ep.fail, ep.biggest_kind = "context-overflow", {"kind": "code-file"}, "code-file"
            c2 = p.observe(ep, tb)
            if c2:
                self.assertNotIn("context-budget", [c.name for c in c2])

    def test_guard_suite(self):
        from aura_harness.guard import run_aura
        rows, same, budget, ok, log = run_aura()
        self.assertTrue(all(v == "BLOCKED" for _, _, v, _ in rows))
        self.assertTrue(same)
        self.assertEqual(budget, 4000)
        self.assertTrue(ok)


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class EquivalenceTest(unittest.TestCase):
    def test_aura_and_file_backends_make_identical_decisions(self):
        from aura_harness.agent import run_stream
        a = run_stream("aura-gated", 3, n=160, shift=80)
        f = run_stream("file-reload", 3, n=160, shift=80)
        strip = lambda vs: [(v["ts"], v["verdict"], v["chosen"], v["candidates"], v["scores"]) for v in vs]
        self.assertGreater(len(a["verdicts"]), 3)
        self.assertEqual(strip(a["verdicts"]), strip(f["verdicts"]))
        self.assertEqual(a["success"], f["success"])
        self.assertEqual(a["cost_per_task"], f["cost_per_task"])


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class KnobTests(unittest.TestCase):
    """AURA_HARNESS_KNOBS=N: N extra mutable defines, range-checked by the same guard."""
    N = 6

    def setUp(self):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_KNOBS"] = str(self.N)
        try:
            self.h = AuraHarness("ws")
        finally:
            os.environ.pop("AURA_HARNESS_KNOBS", None)

    def tearDown(self):
        self.h.close()

    def k(self, i, body):
        from aura_harness.harness import Candidate
        return Candidate(f"knob-{i}", None, "t", "t", f"knob-{i}", raw_aura=body)

    def test_seed_table_has_knobs_and_base_unchanged(self):
        from aura_harness.harness import normalize, seed_table
        tb = self.h.table()
        self.assertEqual(tb.pop("knobs"), [[10] * 4] * self.N)
        self.assertEqual(j(tb), j(normalize(seed_table())))

    def test_knob_apply_guarded(self):
        r = self.h.apply(1, self.k(3, "(lambda (x) (cond ((equal? x 1) 77) (else 10)))"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["table"]["knobs"][3], [10, 77, 10, 10])
        r = self.h.apply(2, self.k(4, "(lambda (x) (cond (else 101)))"))
        self.assertFalse(r["ok"])
        self.assertIn("knob value out of range", r["reason"])
        self.assertEqual(self.h.table()["knobs"][4], [10] * 4)

    def test_knobs_all_not_mutable(self):
        from aura_harness.harness import Candidate
        r = self.h.apply(1, Candidate("knobs-all", None, "t", "t", "x", raw_aura="(lambda () (list))"))
        self.assertFalse(r["ok"])

    def test_knob_trials_leave_root_untouched(self):
        src0 = self.h.source()
        for mode in ("ws", "snap"):
            self.h.worldlines = mode
            r = self.h.trial(1, [self.k(0, "(lambda (x) (cond (else 42)))"), self.k(1, "(lambda (x) (cond (else -1)))")])
            self.assertTrue(r[0]["ok"])
            self.assertEqual(r[0]["table"]["knobs"][0], [42] * 4)
            self.assertFalse(r[1]["ok"])
            self.h.verdict(1, -1, {"base": [0]}, "rollback")
            self.assertEqual(self.h.source(), src0, mode)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class PathWeightTests(unittest.TestCase):
    """AURA_HARNESS_PATH_MAX: knob bodies calling lower knobs at many sites are rejected before the rebind (aura#4630)."""

    def setUp(self):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_KNOBS"] = "4"
        try:
            self.h = AuraHarness("ws")
        finally:
            os.environ.pop("AURA_HARNESS_KNOBS", None)

    def tearDown(self):
        self.h.close()

    def k(self, i, body):
        from aura_harness.harness import Candidate
        return Candidate(f"knob-{i}", None, "t", "t", f"knob-{i}", raw_aura=body)

    def test_heavy_call_paths_rejected_light_ones_pass(self):
        many = lambda j: "(lambda (x) (modulo (+ " + " ".join([f"(knob-{j} x)"] * 40) + ") 101))"
        self.assertTrue(self.h.apply(1, self.k(1, many(0)))["ok"])            # weight 41
        r = self.h.apply(2, self.k(2, many(1)))                                # weight 1641 > 1024
        self.assertFalse(r["ok"])
        self.assertIn("call-path weight 1641", r["reason"])
        ok = self.h.apply(3, self.k(2, "(lambda (x) (modulo (+ (knob-1 x) (knob-1 1)) 101))"))   # weight 83
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["table"]["knobs"][1], [97, 97, 97, 97])           # 40 * 10 mod 101
        self.assertEqual(ok["table"]["knobs"][2], [93, 93, 93, 93])           # (97 + 97) mod 101


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class HofWrapTests(unittest.TestCase):
    """map / filter / for-each in proposed code run as workspace loops (%map ...): with the native primitives, two
    callbacks from sibling expressions of one workspace define get an invalid closure (aura#4626)."""
    BODY = "(lambda (x) (+ (length (filter (lambda (a) (> a 1)) (list 1 2 3))) (car (map (lambda (b) (* b 10)) (list 4)))))"

    def start(self, wrap):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_KNOBS"] = "1"
        os.environ["AURA_HARNESS_HOF_WRAP"] = wrap
        try:
            return AuraHarness("ws")
        finally:
            os.environ.pop("AURA_HARNESS_KNOBS", None); os.environ.pop("AURA_HARNESS_HOF_WRAP", None)

    def test_two_callbacks_give_the_right_value(self):
        from aura_harness.harness import Candidate
        h = self.start("1")
        try:
            adm = h.pipe.call("ADMIT", "knob-0", self.BODY)
            self.assertFalse(adm["reason"])
            self.assertIn("(%filter (lambda (a)", adm["body"]); self.assertIn("(%map (lambda (b)", adm["body"])
            r = h.apply(1, Candidate("knob-0", None, "t", "t", "t", raw_aura=self.BODY))
            self.assertTrue(r["ok"], r.get("reason"))
            self.assertEqual(r["table"]["knobs"], [[42] * 4])
            src = h.source()
            self.assertIn("(filter (lambda (a)", src); self.assertNotIn("%map", src); self.assertNotIn("%filter", src)
            n = h.pipe.call("ADMIT", "knob-0", "(lambda (x) (length (map (lambda (a b) a) (list 1) (list 2))))")
            self.assertIn("n-ary map", n["reason"])
        finally:
            h.close()

    def test_native_hofs_hit_aura_4626(self):
        # documents the Aura bug the wrap avoids; flip to assertEqual once aura#4626 is fixed on the pin
        from aura_harness.harness import Candidate
        h = self.start("0")
        try:
            r = h.apply(1, Candidate("knob-0", None, "t", "t", "t", raw_aura=self.BODY))
            self.assertNotEqual(r.get("table", {}).get("knobs"), [[42] * 4])
        finally:
            h.close()


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class HashWrapTests(unittest.TestCase):
    """String hash keys are stored as "s:" + key (AURA_HARNESS_HASH_WRAP): hash-set! and (hash ...) silently drop the
    key "" (aura#4631; found by the fuzzer's --gen 3). SOURCE shows the plain body."""
    BODY = ('(lambda (x) (let ((h (hash "" 1 "a" 2))) (hash-set! h "" (+ x 10)) (hash-remove! h "a")'
            ' (+ (hash-ref h "" 0) (* 20 (length (hash-keys h))) (if (hash-has-key? h "a") 50 0)'
            ' (if (string=? (car (hash-keys h)) "") 3 0))))')
    WANT = [[33, 34, 35, 36]]

    def start(self, wrap):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_KNOBS"] = "1"
        os.environ["AURA_HARNESS_HASH_WRAP"] = wrap
        try:
            return AuraHarness("ws")
        finally:
            os.environ.pop("AURA_HARNESS_KNOBS", None); os.environ.pop("AURA_HARNESS_HASH_WRAP", None)

    def test_empty_key_round_trips(self):
        from aura_harness.harness import Candidate
        h = self.start("1")
        try:
            r = h.apply(1, Candidate("knob-0", None, "t", "t", "t", raw_aura=self.BODY))
            self.assertTrue(r["ok"], r.get("reason"))
            self.assertEqual(r["table"]["knobs"], self.WANT)
            src = h.source()
            self.assertIn('(hash "" 1 "a" 2)', src); self.assertIn('(hash-set! h "" (+ x 10))', src)
            self.assertNotIn("%hk", src); self.assertNotIn("%hash", src)
            n = h.pipe.call("ADMIT", "knob-0", "(lambda (x) (let ((f hash-ref)) 0))")
            self.assertIn("hash operation used as a value", n["reason"])
        finally:
            h.close()

    def test_unwrapped_hits_aura_4631(self):
        # documents the Aura bug the wrap avoids; flip once aura#4631 is fixed on the pin
        from aura_harness.harness import Candidate
        h = self.start("0")
        try:
            r = h.apply(1, Candidate("knob-0", None, "t", "t", "t", raw_aura=self.BODY))
            self.assertNotEqual(r.get("table", {}).get("knobs"), self.WANT)
        finally:
            h.close()


class StdWrapTests(unittest.TestCase):
    """Allowlisted std-lib functions that are file-level Aura defines (last, list-tail, assq, even?, ...) run as
    workspace %versions: a workspace define calling the file-level one by name has its frame's lists reclaimed mid-call,
    so a caller define read wrong values on every 5th read (aura#4617; found by scripts/fuzz_proposals.py)."""
    BODY = ("(lambda (x) (+ (length (list 5 6 0 (last (list x (list x))))) (if (even? x) 10 20) (expt 2 3)"
            " (cadr (assq 'b (list (list 'a 1) (list 'b 2)))) (car (list-tail (list 7 8 9) 2))))")
    WANT = [[33, 43, 33, 43]]

    def start(self, wrap):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_KNOBS"] = "1"
        os.environ["AURA_HARNESS_STD_WRAP"] = wrap
        try:
            return AuraHarness("ws")
        finally:
            os.environ.pop("AURA_HARNESS_KNOBS", None); os.environ.pop("AURA_HARNESS_STD_WRAP", None)

    def test_std_calls_stay_right_over_repeated_reads(self):
        from aura_harness.harness import Candidate
        h = self.start("1")
        try:
            adm = h.pipe.call("ADMIT", "knob-0", self.BODY)
            self.assertFalse(adm["reason"])
            for n in ("%last", "%even?", "%expt", "%assq", "%list-tail"):
                self.assertIn("(" + n + " ", adm["body"])
            r = h.apply(1, Candidate("knob-0", None, "t", "t", "t", raw_aura=self.BODY))
            self.assertTrue(r["ok"], r.get("reason"))
            self.assertEqual([h.table()["knobs"] for _ in range(12)], [self.WANT] * 12)
            src = h.source()
            self.assertIn("(last (list x", src); self.assertNotIn("%last", src); self.assertNotIn("%even?", src)
            for bad in ("string-upcase", "symbol->string"):
                rr = h.pipe.call("ADMIT", "knob-0", "(lambda (x) (string-length (" + bad + " x)))")
                self.assertIn("symbol not allowed: " + bad, rr["reason"])
        finally:
            h.close()

    def test_file_level_last_hits_aura_4617(self):
        # documents the Aura bug the wrap avoids; flip once aura#4617 is fixed on the pin
        h = self.start("0")
        try:
            body = "(lambda (x) (length (list 5 6 0 (last (list x (list x))))))"
            from aura_harness.harness import Candidate
            r = h.apply(1, Candidate("knob-0", None, "t", "t", "t", raw_aura=body))
            reads = [r.get("table", {}).get("knobs")] + [h.table().get("knobs") for _ in range(11)]
            self.assertNotEqual(reads, [[[4, 4, 4, 4]]] * 12)
        finally:
            h.close()


class RunawayTests(unittest.TestCase):
    """Runaway containment (fuel metering): runaway bodies fail their trial, the process survives, legitimate loops
    still pass with the right value."""

    def setUp(self):
        from aura_harness.control import AuraHarness
        self.h = AuraHarness("ws")

    def tearDown(self):
        self.h.close()

    def cand(self, name, body):
        from aura_harness.harness import Candidate
        return Candidate(name, None, "test", "test", "test", raw_aura=body)

    def test_runaway_bodies_fail_and_process_survives(self):
        from aura_harness.harness import normalize, seed_table
        for body in ["(lambda (need) (let loop ((i 0)) (loop (+ i 1))))",
                     "(lambda (need) (letrec ((f (lambda (n) (+ 1 (f (+ n 1)))))) (f 0)))",
                     '(lambda (need) (let loop ((s "x")) (loop (string-append s s))))',
                     "(lambda (need) (while #t 1))"]:
            r = self.h.apply(1, self.cand("route-tool", body))
            self.assertFalse(r["ok"], body)
            self.assertTrue(r["reason"].startswith("fuel exhausted"), r["reason"])
            t = self.h.trial(1, [self.cand("route-tool", body)])[0]
            self.h.verdict(1, -1, [0], "test")
            self.assertFalse(t["ok"])
        self.assertEqual(j(self.h.table()), j(normalize(seed_table())))

    def test_meter_dodges_rejected_statically(self):
        for body, why in [('(lambda (need) (try (let loop () (loop)) (catch (e) "grep")))', "forbidden symbol in body: try"),
                          ("(lambda (need) (let ((%tick (lambda () #f))) (let loop () (loop))))", "forbidden symbol in body: %"),
                          ('(lambda (need) (let ((sa string-append)) (sa "g" "rep")))', "allocator used as a value"),
                          ('(lambda (need) (if (assoc need (list (list "search" 1))) "grep" "cat"))', "symbol not allowed: assoc"),
                          ('(lambda (need) (if (> (current-time-ms) 0) "grep" "cat"))', "symbol not allowed: current-time-ms"),
                          ('(lambda (need) "grep") ; x', "unsupported syntax: ;")]:
            r = self.h.pipe.call("ADMIT", "route-tool", body)
            self.assertIn(why, r["reason"] or "", body)

    def test_legit_loops_pass_with_right_value(self):
        # a vector filled in a loop and read afterwards: wrong on ~1 call in 40 while %tick was a file-level function
        # (aura#4617); also while -> named let, and the list-argument allocator wrappers (aura#4621)
        for body, want in [("(lambda (fact) (let ((v (vector 0))) (let lp ((k 0)) (if (< k 3) (begin (vector-set! v 0 (+ k 1)) (lp (+ k 1))) #f)) (vector-ref v 0)))", 3),
                           ("(lambda (fact) (let ((v (make-vector 1 0))) (while (< (vector-ref v 0) 4) (vector-set! v 0 (+ (vector-ref v 0) 1))) (vector-ref v 0)))", 4),
                           ("(lambda (fact) (length (append (list 1) (list 2 3) (list (list 4)))))", 4),
                           ('(lambda (fact) (string-length (string-append "a" "bc" (string-append "d" "e"))))', 5),
                           ("(lambda (fact) (do ((i 0 (+ i 1)) (s 0 (+ s i))) ((= i 4) s)))", 6)]:
            for _ in range(2):
                r = self.h.apply(1, self.cand("memory-ttl", body))
                self.assertTrue(r["ok"], (body, r.get("reason")))
                self.assertTrue(all(v == want for v in r["table"]["ttl"].values()), body)

    def test_source_is_clean_raw_is_instrumented(self):
        self.h.apply(1, self.cand("memory-ttl", '(lambda (fact) (string-length (string-append "a" "b")))'))
        src, raw = self.h.source(), self.h.pipe.call("SOURCE", "raw")["source"]
        self.assertNotIn("%", src)
        self.assertIn("(string-append \"a\" \"b\")", src)
        self.assertIn("(define %tick", raw)
        self.assertIn("(%tick)", raw)

    def test_compaction_keeps_the_meter(self):
        self.h.apply(1, self.cand("memory-ttl", "(lambda (fact) 3)"))
        self.h.pipe.call("COMPACT")
        r = self.h.apply(2, self.cand("route-tool", "(lambda (need) (let loop () (loop)))"))
        self.assertFalse(r["ok"])
        self.assertTrue(r["reason"].startswith("fuel exhausted"))
        self.assertEqual(self.h.decide("ttl", "repo-layout"), 3)


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class FuelOffTests(unittest.TestCase):
    def test_fuel_zero_is_the_token_guard(self):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_FUEL"] = "0"
        try:
            h = AuraHarness("ws")
        finally:
            os.environ.pop("AURA_HARNESS_FUEL", None)
        try:
            body = "(lambda (fact) (let lp ((i 0)) (if (< i 3) (lp (+ i 1)) i)))"
            r = h.pipe.call("ADMIT", "memory-ttl", body)
            self.assertEqual(r["fuel"], 0)
            self.assertEqual(r["body"], body)
            self.assertNotIn("(define %tick", h.pipe.call("SOURCE", "raw")["source"])
        finally:
            h.close()
