import random
import unittest

from aura_harness.env import Memory, make_stream, run_task
from aura_harness.harness import (MUTABLE, COMPONENT, delegate_map, normalize, post_check, seed_table, to_python)


class EnvTests(unittest.TestCase):
    def test_deterministic_and_paired(self):
        tb = normalize(seed_table())
        a = [run_task(t, tb, Memory(0), 0).summary() for t in make_stream(0, 120, 60)]
        b = [run_task(t, tb, Memory(0), 0).summary() for t in make_stream(0, 120, 60)]
        self.assertEqual(a, b)

    def test_heldout_split_about_half(self):
        s = make_stream(1, 400)
        self.assertTrue(150 < sum(t.heldout for t in s) < 250)

    def test_shift_changes_mix(self):
        s = make_stream(2, 400, 200)
        ref = lambda xs: sum(t.kind in ("triage", "refactor") for t in xs) / len(xs)
        self.assertGreater(ref(s[200:]), ref(s[:200]) + .2)

    def test_better_harness_helps(self):
        tb = normalize(seed_table())
        good = normalize(seed_table())
        good["compress"].update({"test-log": ["tail", 800], "service-log": ["grep-errors", 800],
                                 "code-file": ["head", 1600]})
        good["route"]["edit"] = "apply-patch"
        ok = lambda t: sum(run_task(x, t, m, 0).success for m in [Memory(0)] for x in make_stream(0, 200, 400))
        self.assertGreater(ok(good), ok(tb) + 40)

    def test_python_compile_matches_table(self):
        r = random.Random(0)
        tb = normalize(seed_table())
        tb["compress"]["test-log"] = ["tail", 400]
        tb["retry"]["sql|rate-limit"] = 3
        tb["ttl"]["test-cmd"] = 40
        tb["delegate"] = delegate_map({"refactor": 3})
        tb["route"]["search"] = "lsp-find"
        ns = {}
        for name in MUTABLE:
            exec(to_python(name, tb[COMPONENT[name]]), ns)
        self.assertEqual(ns["route_tool"]("search"), "lsp-find")
        self.assertEqual(ns["compress"]("test-log"), ["tail", 400])
        self.assertEqual(ns["retry_limit"]("sql", "rate-limit"), 3)
        self.assertEqual(ns["memory_ttl"]("test-cmd"), 40)
        self.assertEqual(ns["delegate"]("refactor", 3), "delegate")
        self.assertEqual(ns["delegate"]("refactor", 2), "inline")
        b = {"budget": 4000, "max_steps": 30, "allowed": seed_table()["allowed"], "sandbox": "restricted"}
        self.assertIsNone(post_check(tb, b))
        tb["retry"]["sql|rate-limit"] = 9
        self.assertIsNotNone(post_check(tb, b))


if __name__ == "__main__":
    unittest.main()
