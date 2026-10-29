"""Agensh-style swarm on Aura fibers (Aura-backed test skips without AURA_BIN)."""
import os
import unittest

from aura_harness.swarm import forms, kv, run, run_expr


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

    @unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")
    def test_free_small_accepts(self):
        r = run("free", 4, 64, 8, 2000, timeout=300)
        self.assertEqual(r["accepted"], 1)

    @unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")
    def test_rebind_under_contention(self):
        # assert only on correctness: a stats-key corruption Aura bug can mangle counter names
        # a clean run takes ~1 s; the ~1/4-run deadlock (aura#4765) is fixed, so no retry
        r = run_expr("(run-rebind 4 64 8 2000 4)", {}, timeout=120)
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(r["done-valid"], 1)
        self.assertGreater(r.get("rebinds", 0), 0)

    @unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")
    def test_worker_failure_lease_takeover(self):
        r = run_expr("(run-fail 4 64 8 2000 3)", {})
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(r["join-error"], 1)
        self.assertEqual(r["claims-held"], 0)

    @unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")
    def test_cancel_partial_sound(self):
        r = run_expr("(run-cancel 4 1024 64 20000 200)", {})
        self.assertEqual(r["done-valid"], 1)
        self.assertEqual(r["claims-held"], 0)


if __name__ == "__main__":
    unittest.main()
