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
