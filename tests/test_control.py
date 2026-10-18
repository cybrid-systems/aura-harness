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


if __name__ == "__main__":
    unittest.main()
