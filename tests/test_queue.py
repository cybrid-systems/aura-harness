"""3a: candidates queued while another is pending stat admission (rsi/proposal.CandidateQueue + loop invariants)."""
import os
import unittest

from aura_harness.harness import Candidate
from aura_harness.rsi.proposal import CandidateQueue

HAVE = bool(os.environ.get("AURA_BIN"))


def C(desc, sig):
    return Candidate(name="route-tool", value="(x)", why="w", sig=sig, desc=desc)


class Queue(unittest.TestCase):
    def test_dedup_merge_bound(self):
        q = CandidateQueue(cap=2)
        q.push([C("a", "s1")], pending_descs=["p"], pending_sigs=["s0"])
        q.push([C("a", "s1"), C("b", "s1")])                    # same sig: merge new descs only
        q.push([C("p", "s2")], pending_descs=["p"])             # same desc as pending -> dropped
        q.push([C("c", "s0")], pending_sigs=["s0"])                 # pending signature -> dropped
        q.push([C("d", "s3")])
        q.push([C("e", "s4")])                                   # full
        self.assertEqual([(s, [c.desc for c in cs]) for s, cs in q.q], [("s1", ["a", "b"]), ("s3", ["d"])])
        self.assertEqual((q.n["merged"], q.n["dropped_dup"], q.n["dropped_full"]), (1, 3, 1))

    def test_pop_rechecks_noop(self):
        q = CandidateQueue()
        q.push([C("a", "s1")])
        q.push([C("b", "s2"), C("c", "s2")])
        got = q.pop({}, lambda c, tb: c.desc in ("a", "b"))
        self.assertEqual([c.desc for c in got], ["c"])
        self.assertEqual(q.n["dropped_noop"], 2)
        self.assertIsNone(q.pop({}, lambda c, tb: False))


class Conflicts(unittest.TestCase):
    def test_same_component_displaced_other_rebased(self):
        from types import SimpleNamespace as NS
        from aura_harness.harness import seed_table
        from aura_harness.rsi.loop import _resolve_conflicts
        from aura_harness.rsi.stat import StatAdmission
        tb0 = seed_table()
        s, q = StatAdmission(), CandidateQueue()
        mk = lambda name, desc, ts: s.open({"ts": ts, "cand": C(desc, desc).__class__(name=name, value=None, why="w",
                                            sig=desc, desc=desc), "cands": [C(desc, desc)], "table": dict(tb0)})
        P = mk("route-tool", "r1", 1)
        Q = mk("route-tool", "r2", 2)
        R = mk("compress", "c1", 3)
        Q["fresh"] = [5, 7]
        R["table"]["compress"] = "NEW-COMPRESS"
        tb1 = dict(tb0, route="KEPT-ROUTE")
        _resolve_conflicts(s, P, P["cand"], tb1, q, 40)
        self.assertNotIn(Q, s.slots)                                   # same component -> displaced, re-queued
        self.assertEqual(q.q[0][0], "r2")
        self.assertEqual(s.log[-1]["verdict"], "conflict")
        self.assertEqual(s.log[-1]["fresh_spent"], 2)                  # its fresh tasks stay spent
        self.assertEqual((R["table"]["route"], R["table"]["compress"]), ("KEPT-ROUTE", "NEW-COMPRESS"))  # re-based


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class StatLoop(unittest.TestCase):
    def test_parallel_admission_invariants(self):
        from aura_harness.rsi.loop import run_rsi
        from aura_harness.rsi.m2 import M2Config
        r = run_rsi(0, n=1000, shift=500, cfg=M2Config(admission="stat"))
        st = r["stat"]
        dec = [x for x in st["log"] if x["verdict"] in ("keep", "reject", "wait")]
        self.assertTrue(dec)
        final = {}
        for x in dec:
            final[x["slot"]] = x
            self.assertEqual(x["alpha_look"], round(0.05 / 12, 5))
            self.assertTrue(all(i > x["sel_ts"] for i in x["fresh_ids"]))
            self.assertLessEqual(x["concurrent"], 3)
        seen = set()
        for x in final.values():                                       # one-shot: no fresh id in two slots
            self.assertFalse(seen & set(x["fresh_ids"]))
            seen |= set(x["fresh_ids"])
        self.assertTrue(all(str(i) in {str(k) for k in st["owner"]} for i in seen))

    def test_proposer_sees_only_verdicts(self):
        from aura_harness.rsi.loop import run_rsi
        from aura_harness.rsi.m2 import M2Config
        from aura_harness.proposer import Proposer
        got = []

        class Spy(Proposer):
            def feedback(self, sig, verdict, blocked):
                got.append((sig, verdict, tuple(blocked)))
                super().feedback(sig, verdict, blocked)
        run_rsi(0, n=1000, shift=500, cfg=M2Config(admission="stat"), proposer=lambda **kw: Spy(**kw))
        self.assertTrue(got)
        self.assertTrue(all(v in ("KEEP", "ROLLBACK") and isinstance(s, str) for s, v, _ in got))


if __name__ == "__main__":
    unittest.main()
