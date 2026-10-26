"""Agensh-style swarm on Aura fibers (Aura-backed test skips without AURA_BIN)."""
import os
import unittest

from aura_harness.swarm import forms, kv, run


class SwarmTest(unittest.TestCase):
    def test_forms_split(self):
        self.assertEqual(forms('(define a 1)\n; c\n(display "x)")'), ['(define a 1)', '(display "x)")'])

    def test_kv(self):
        self.assertEqual(kv("a=1;b=x;"), {"a": 1, "b": "x"})

    @unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")
    def test_epoch_small_accepts(self):
        r = run("epoch", 8, 64, 8, 400, timeout=300)
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(r["done"], 64)


if __name__ == "__main__":
    unittest.main()
