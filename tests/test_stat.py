"""M5b statistical admission (pure parts)."""
import unittest
from types import SimpleNamespace as NS

from aura_harness.harness import Candidate, seed_table
from aura_harness.rsi.m2 import fresh_of
from aura_harness.rsi.stat import StatAdmission, hard_veto, sign_p


def outcomes(pairs, tok=(100, 100), steps=(3, 3)):
    b = {i: (x, tok[0], steps[0]) for i, (x, _) in enumerate(pairs)}
    c = {i: (y, tok[1], steps[1]) for i, (_, y) in enumerate(pairs)}
    return b, c, list(range(len(pairs)))


class Stat(unittest.TestCase):
    def test_sign_p(self):
        self.assertEqual(sign_p(0, 0), 1.0)
        self.assertAlmostEqual(sign_p(5, 0), 1 / 32)
        self.assertAlmostEqual(sign_p(1, 1), 0.75)
        self.assertAlmostEqual(sign_p(8, 2), 56 / 1024)

    def sa(self):
        s = StatAdmission()
        s.pending = {"look": 0, "cand": NS(desc="x")}
        return s

    def test_keep_wait_reject(self):
        s = self.sa()
        self.assertEqual(s.decide(*outcomes([(False, True)] * 8 + [(True, True)] * 8))[0], "keep")   # p=.0039
        s = self.sa()
        v, info = s.decide(*outcomes([(False, True)] * 5 + [(True, False)] * 2 + [(True, True)] * 9))
        self.assertEqual((v, s.pending["look"]), ("wait", 1))                                     # not yet
        s.pending["look"] = 3
        self.assertEqual(s.decide(*outcomes([(False, True)] * 5 + [(True, False)] * 2))[0], "reject")  # last look
        s = self.sa()                                       # concordant pairs carry no evidence
        self.assertEqual(s.decide(*outcomes([(True, True)] * 40))[1]["p"], 1.0)

    def test_pareto_on_jointly_solved_tasks(self):
        s = self.sa()
        v, info = s.decide(*outcomes([(False, True)] * 8 + [(True, True)] * 8, tok=(100, 200)))
        self.assertEqual((v, info.get("pareto")), ("reject", "regression"))
        s = self.sa()                                       # cost of newly solved tasks alone is not a regression
        self.assertEqual(s.decide(*outcomes([(False, True)] * 10, tok=(10, 900)))[0], "keep")

    def test_hard_veto(self):
        self.assertIsNotNone(hard_veto(Candidate("context-budget", None, "w", "s", "d", raw_aura="(lambda () 1)")))
        self.assertIsNotNone(hard_veto(Candidate("route-tool", None, "w", "s", "d", raw_aura="(lambda (n) 1)")))
        self.assertIsNone(hard_veto(Candidate("route-tool", dict(seed_table()["route"]), "w", "s", "d")))

    def test_selection_admission_disjoint_and_one_use(self):
        tasks = [NS(id=i, heldout=i % 2 == 0) for i in range(200)]
        s = StatAdmission()
        s.pending = {"ts": 50, "look": 0}
        ids = s.fresh_ids(tasks, 150)
        self.assertTrue(ids and all(fresh_of(i) and i > 50 and tasks[i].heldout for i in ids))
        sel = [t.id for t in tasks[10:51] if t.heldout and not fresh_of(t.id)]
        self.assertFalse(set(ids) & set(sel))
        s.pending = {"ts": 150, "look": 0}                  # the next decision only sees later tasks
        self.assertFalse(set(s.fresh_ids(tasks, 199)) & set(ids))
