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
        q.push([C("a", "s1")], pending_descs=["p"], pending_sig="s0")
        q.push([C("a", "s1"), C("b", "s1")])                    # same sig: merge new descs only
        q.push([C("p", "s2")], pending_descs=["p"])             # same desc as pending -> dropped
        q.push([C("c", "s0")], pending_sig="s0")                 # pending signature -> dropped
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


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class StatLoop(unittest.TestCase):
    def test_fresh_sets_one_shot_and_alpha(self):
        from aura_harness.rsi.loop import run_rsi
        from aura_harness.rsi.m2 import M2Config
        r = run_rsi(0, n=400, cfg=M2Config(admission="stat"))
        log = [x for x in r["stat"]["log"] if x["verdict"] != "wait"]
        self.assertGreaterEqual(len(log), 2)
        spans = [tuple(x["fresh"]) for x in log]
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            self.assertLess(a1, b0)                              # decisions are serial: fresh windows never overlap
        for x in r["stat"]["log"]:
            self.assertEqual(x["alpha_look"], round(0.05 / 4, 4))  # Bonferroni over the 4 looks of one candidate
            self.assertGreater(x["fresh"][0], x["sel_ts"])       # fresh tasks arrive after the selection
        self.assertGreater(r["stat"]["queue"]["queued"], 0)


if __name__ == "__main__":
    unittest.main()
