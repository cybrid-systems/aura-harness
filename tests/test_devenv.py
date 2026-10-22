"""M3 dev environment: real repos, real tools (no Aura needed)."""
import copy
import unittest

from aura_harness import devenv as D
from aura_harness.env import Memory
from aura_harness.harness import seed_table


def tuned():
    tb = seed_table()
    tb["compress"]["test-log"] = ["grep-errors", 800]
    tb["route"]["edit"] = "apply-patch"
    tb["retry"]["grep|timeout"] = 3
    return tb


class DevEnvTests(unittest.TestCase):
    def setUp(self):
        D._CACHE.clear()
        self.st = D.make_stream(0, 40, 20)

    def test_seed_harness_loses_the_failure_in_verbose_output(self):
        ep = D.run_dev(self.st[0], seed_table(), Memory(0), 0)
        self.assertEqual((ep.mode, ep.fail["kind"]), ("info-lost", "test-log"))

    def test_tuned_harness_fixes_real_bugs(self):
        mem = Memory(0)
        ok = sum(D.run_dev(t, tuned(), mem, 0).success for t in self.st[:12])
        self.assertGreaterEqual(ok, 9)

    def test_naive_sed_breaks_on_slash(self):
        t = next(x for x in self.st if x.kind == "bugfix" and x.bugs[0][1] == "mean")
        tb = copy.deepcopy(tuned())
        tb["route"]["edit"] = "sed"
        ep = D.run_dev(t, tb, Memory(0), 0)
        self.assertEqual((ep.mode, ep.fail.get("tool"), ep.fail.get("err")), ("tool-error", "sed", "bad-args"))

    def test_compress_strategies(self):
        text = "\n".join(f"line {i}" for i in range(2000)) + "\nFAIL: test_x_0 (t)\n"
        self.assertNotIn("FAIL", D.compress(text, "head", 100))
        self.assertIn("FAIL", D.compress(text, "tail", 100))
        self.assertIn("FAIL", D.compress(text, "grep-errors", 100))
        self.assertEqual(D.compress("short", "head", 100), "short")

    def test_cache_is_exact(self):
        t = self.st[0]
        a = tuned()
        b = copy.deepcopy(a)
        b["ttl"]["db-schema"] = 99           # not consulted by a dev task: cache hit
        e1 = D.run_dev(t, a, Memory(0), 0)
        e2 = D.run_dev(t, b, Memory(0), 0)
        self.assertIs(e1, e2)
        c = copy.deepcopy(a)
        c["compress"]["test-log"] = ["head", 800]   # consulted: must re-run
        e3 = D._run(t, c, Memory(0), 0)
        self.assertEqual(D.run_dev(t, c, Memory(0), 0).success, e3.success)
        self.assertIsNot(D.run_dev(t, c, Memory(0), 0), e1)

    def test_heldout_and_ood_repos_are_disjoint_from_training(self):
        for t in D.make_stream(1, 100, 50):
            self.assertEqual(t.heldout, t.project in D.HELDOUT_REPOS)
        self.assertTrue(all(t.project in D.OOD_REPOS for t in D.ood_tasks(0)))
        self.assertFalse(set(D.OOD_REPOS) & set(D.TRAIN_REPOS + D.HELDOUT_REPOS))
