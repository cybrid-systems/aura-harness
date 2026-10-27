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
        self.P = s.open({"ts": 0, "look": 0, "cand": NS(desc="x")})
        return s

    def dec(self, s, args):
        return s.decide(*args, self.P)

    def test_keep_wait_reject(self):
        s = self.sa()
        self.assertEqual(self.dec(s, outcomes([(False, True)] * 8 + [(True, True)] * 8))[0], "keep")   # p=.0039
        s = self.sa()
        v, info = self.dec(s, outcomes([(False, True)] * 5 + [(True, False)] * 2 + [(True, True)] * 9))
        self.assertEqual((v, self.P["look"]), ("wait", 1))                                     # not yet
        self.P["look"] = 3
        self.assertEqual(self.dec(s, outcomes([(False, True)] * 5 + [(True, False)] * 2))[0], "reject")  # last look
        s = self.sa()                                       # concordant pairs carry no evidence
        self.assertEqual(self.dec(s, outcomes([(True, True)] * 40))[1]["p"], 1.0)

    def test_pareto_on_jointly_solved_tasks(self):
        s = self.sa()
        v, info = self.dec(s, outcomes([(False, True)] * 8 + [(True, True)] * 8, tok=(100, 200)))
        self.assertEqual((v, info.get("pareto")), ("reject", "regression"))
        s = self.sa()                                       # cost of newly solved tasks alone is not a regression
        self.assertEqual(self.dec(s, outcomes([(False, True)] * 10, tok=(10, 900)))[0], "keep")

    def test_hard_veto(self):
        self.assertIsNotNone(hard_veto(Candidate("context-budget", None, "w", "s", "d", raw_aura="(lambda () 1)")))
        self.assertIsNotNone(hard_veto(Candidate("route-tool", None, "w", "s", "d", raw_aura="(lambda (n) 1)")))
        self.assertIsNone(hard_veto(Candidate("route-tool", dict(seed_table()["route"]), "w", "s", "d")))

    def test_fresh_dealt_disjoint_one_shot_after_selection(self):
        tasks = [NS(id=i, heldout=i % 2 == 0) for i in range(300)]
        s = StatAdmission()
        A = s.open({"ts": 50, "cand": NS(desc="a")})
        s.assign(tasks, 80)
        B = s.open({"ts": 100, "cand": NS(desc="b")})        # 81..100 arrive with only A open
        s.assign(tasks, 160)                                 # the loop deals every step before it selects
        C = s.open({"ts": 160, "cand": NS(desc="c")})
        s.assign(tasks, 299)
        sets = [A["fresh"], B["fresh"], C["fresh"]]
        allids = [i for x in sets for i in x]
        self.assertEqual(len(allids), len(set(allids)))                       # disjoint
        for P, ids in zip((A, B, C), sets):
            self.assertTrue(ids and all(i > P["ts"] and fresh_of(i) and tasks[i].heldout for i in ids))
        sel = [t.id for t in tasks if t.heldout and not fresh_of(t.id)]
        self.assertFalse(set(allids) & set(sel))                              # never a selection task
        self.assertEqual(set(s.owner), set(allids))
        s.close(A); s.close(B); s.close(C)
        s.assign(tasks, 299)                                                   # no re-dealing
        self.assertEqual(len(s.owner), len(allids))
        self.assertTrue(all(i <= 50 or i in s.owner for i in range(300) if tasks[i].heldout and fresh_of(i)))

    def test_alpha_split_over_concurrent_family(self):
        s = StatAdmission()
        self.assertAlmostEqual(s.alpha_look * s.k * len(s.looks), s.alpha)   # Bonferroni: sum over family = alpha
        self.assertEqual(s.k, 3)
        for i in range(3):
            s.open({"ts": i, "cand": NS(desc=str(i))})
        self.assertTrue(s.full())
        with self.assertRaises(AssertionError):
            s.open({"ts": 9, "cand": NS(desc="x")})
        # 7 wins / 0 losses (p=.0078) passed the serial alpha/4=.0125 but not alpha/12=.0042
        v, info = s.decide(*outcomes([(False, True)] * 7 + [(True, True)] * 9), s.slots[0])
        self.assertEqual((v, info["alpha_look"]), ("wait", round(0.05 / 12, 5)))
