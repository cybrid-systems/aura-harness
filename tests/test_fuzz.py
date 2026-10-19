"""Pure-Python checks of the proposal fuzzer's generator, reference evaluator and shrinker (no Aura needed)."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fuzz_proposals as fz  # noqa: E402


class FuzzGenTests(unittest.TestCase):
    def test_v2_bodies_evaluate_in_range(self):
        r = random.Random(3)
        for _ in range(100):
            src, vals, e = fz.make_body(r, 2)
            self.assertEqual(fz.ref_vals(e), vals)
            self.assertEqual(fz.body_src(e), src)
            self.assertTrue(all(0 <= v <= 100 for v in vals))

    def test_string_and_vector_forms(self):
        e = ("sdigit", "t1", ("string-append", ("number->string", ("num", 12)), ("srev", ("number->string", ("num", 340)))), ("var", "x"))
        self.assertEqual([fz.ev(e, {"x": x}) for x in range(4)], [1, 2, 0, 4])   # "12043"
        v = ("vloop", "vv1", "i2", 4, ("*", ("var", "i2"), ("var", "i2")), ("var", "x"))
        self.assertEqual([fz.ev(v, {"x": x}) for x in range(4)], [0, 1, 4, 9])
        self.assertIn("vector-set! vv1 i2", fz.to_aura(v))

    def test_v3_hash_forms(self):
        r = random.Random(5)
        n = 0
        for _ in range(100):
            src, vals, e = fz.make_body(r, 3)
            self.assertEqual(fz.ref_vals(e), vals)
            n += "(hash)" in src
        self.assertGreater(n, 30)
        # i*i mod 3 = 0 1 1 0 1: keys "" "a" "a" "" "a" -> 2 distinct; "" holds its last write (i=3); list keys compare by equal?
        h = ("hloop", "hh1", "i2", 5, ("hstr", ("modulo", ("*", ("var", "i2"), ("var", "i2")), ("num", 3))), ("var", "i2"),
             ("hstr", ("num", 0)), ("num", 99), "ref")
        self.assertEqual(fz.ev(h, {"x": 0}), 3)
        self.assertEqual(fz.ev(h[:8] + ("count",), {"x": 0}), 2)
        self.assertEqual(fz.ev(h[:8] + ("rmcount",), {"x": 0}), 1)
        self.assertIs(fz.ev(h[:8] + ("has",), {"x": 0}), True)
        self.assertIn('(hash-set! hh1 (substring "abc" 0', fz.to_aura(h))
        lk = ("hloop", "hh1", "i2", 2, ("list", [("num", 1)]), ("var", "i2"), ("list", [("num", 1)]), ("num", 9), "ref")
        self.assertEqual(fz.ev(lk, {"x": 0}), 1)
        self.assertEqual(fz.kind(h[:8] + ("has",)), "bool")


class MultiKnobTests(unittest.TestCase):
    def tearDown(self):
        fz.KNOBS.clear()

    def test_knob_calls_follow_the_latest_callee(self):
        fz.KNOBS.clear()
        k1 = ("modulo", ("abs", ("+", ("kcall", 0, ("var", "x")), ("num", 1))), ("num", 101))
        fz.KNOBS[1] = k1
        self.assertEqual(fz.knob_table(2), [[10] * 4, [11] * 4])          # knob-0 is the seed's constant 10
        fz.KNOBS[0] = ("modulo", ("abs", ("*", ("var", "x"), ("num", 3))), ("num", 101))
        self.assertEqual(fz.knob_table(2), [[0, 3, 6, 9], [1, 4, 7, 10]])  # the caller sees the rebound callee
        self.assertEqual(fz.to_aura(("kcall", 0, ("num", 2))), "(knob-0 2)")

    def test_generator_only_calls_lower_knobs(self):
        r = random.Random(4)
        for _ in range(50):
            e = fz.Gen(r, knobs=range(2)).int_([("x", "int")], 0)
            src = fz.to_aura(e)
            self.assertNotIn("(knob-2", src)
            self.assertNotIn("(knob-3", src)


class ShrinkTests(unittest.TestCase):
    def test_shrinks_to_the_offending_form(self):
        r = random.Random(1)
        while True:
            src, vals, e = fz.make_body(r, 2)
            if "make-vector" in src and len(src) > 300:
                break
        small, calls = fz.shrink(e, lambda e2, want: "make-vector" in fz.body_src(e2), budget=400)
        out = fz.body_src(small)
        self.assertIn("make-vector", out)
        self.assertLess(len(out), 160)
        self.assertIsNotNone(fz.ref_vals(small))

    def test_kind_ignores_bindings(self):
        self.assertIsNone(fz.kind(("v12", ("num", 1))))
        self.assertEqual(fz.kind(("map", ("lambda", ["y1"], ("num", 0)), ("list", []))), "list")


if __name__ == "__main__":
    unittest.main()
