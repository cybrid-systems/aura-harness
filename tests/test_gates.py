"""Dual gates and the structured proposer. Pure checks, plus one Aura worldline check when AURA_BIN is set.

The harmful-KEEP regression does not run a 400-task stream: it scores the known
"ttl all 0" / "compress all head/50" / "retry all 0" shapes against a window
that ``better()`` would KEEP, and checks the live root stays untouched when the
verdict index is the gate's choice.
"""
import os
import unittest

from aura_harness.agent import better
from aura_harness.env import ERRLINE_KINDS
from aura_harness.harness import PROTECTED, Candidate, seed_table
from aura_harness.proposer import Proposer
from aura_harness.rsi.gates import (
    admit_index,
    harm_candidates,
    solution_gate,
    structure_gate,
)
from aura_harness.rsi.structured import StructuredProposer

HAVE = bool(os.environ.get("AURA_BIN"))


def _tb():
    tb = seed_table()
    tb["ttl"] = {"test-cmd": 40, "repo-layout": 40, "db-schema": 0}
    return tb


class StructureGateTests(unittest.TestCase):
    def test_known_harms_fail_even_when_the_signature_is_borrowed(self):
        tb = _tb()
        # The validation injector stamps the round's real signature onto the harm edit.
        for sig in ("rediscover|test-cmd", "info-lost|service-log", "stale-memory|test-cmd"):
            for c in harm_candidates(tb, sig):
                ok, why = structure_gate(c, tb)
                self.assertFalse(ok, (c.desc, sig, why))

    def test_localized_stale_zero_still_aligns(self):
        tb = _tb()
        m = dict(tb["ttl"])
        m["test-cmd"] = 0
        c = Candidate("memory-ttl", m, "stale-memory test-cmd", "stale-memory|test-cmd", "ttl test-cmd=0")
        ok, why = structure_gate(c, tb)
        self.assertTrue(ok, why)

    def test_rediscover_rejects_the_opposite_direction(self):
        tb = _tb()
        m = dict(tb["ttl"])
        m["test-cmd"] = 0
        c = Candidate("memory-ttl", m, "rediscover test-cmd", "rediscover|test-cmd", "ttl test-cmd=0")
        ok, why = structure_gate(c, tb)
        self.assertFalse(ok, why)
        up = dict(tb["ttl"])
        up["test-cmd"] = 80
        good = Candidate("memory-ttl", up, "rediscover test-cmd", "rediscover|test-cmd", "ttl test-cmd=80")
        ok, why = structure_gate(good, tb)
        self.assertTrue(ok, why)

    def test_protected_and_allowlist_contradictions(self):
        tb = seed_table()
        protected = Candidate("context-budget", None, "context-overflow bugfix", "context-overflow|bugfix",
                              "raise context-budget to 8000", raw_aura="(lambda () 8000)")
        ok, why = structure_gate(protected, tb)
        self.assertFalse(ok, why)
        self.assertIn(protected.name, PROTECTED)
        route = dict(tb["route"])
        route["search"] = "net-raw"
        bad = Candidate("route-tool", route, "tool-error grep|timeout", "tool-error|grep|timeout", "route search->net-raw")
        ok, why = structure_gate(bad, tb)
        self.assertFalse(ok, why)
        self.assertIn("allowlist", why)

    def test_transient_retry_direction(self):
        tb = seed_table()
        up = dict(tb["retry"])
        up["grep|timeout"] = 3
        good = Candidate("retry-limit", up, "tool-error grep|timeout", "tool-error|grep|timeout", "retry grep|timeout=3")
        self.assertTrue(structure_gate(good, tb)[0])
        down = dict(tb["retry"])
        down["grep|timeout"] = 0
        bad = Candidate("retry-limit", down, "tool-error grep|timeout", "tool-error|grep|timeout", "retry grep|timeout=0")
        self.assertFalse(structure_gate(bad, tb)[0])


class SolutionGateTests(unittest.TestCase):
    def test_better_would_keep_the_wipe_and_the_solution_gate_does_not(self):
        tb = _tb()
        # +3 held-out successes and +12% cost: the shape from the 2026-10-30 note.
        base, win = (15, 40, 100000), (18, 40, 112000)
        self.assertTrue(better(win, base))
        for c in harm_candidates(tb, "info-lost|service-log"):
            ok, why = solution_gate(win, base, c, tb)
            self.assertFalse(ok, (c.desc, why))

    def test_constructive_token_spend_still_passes(self):
        tb = seed_table()
        m = {k: list(v) for k, v in tb["compress"].items()}
        m["code-file"] = ["head", 1600]
        c = Candidate("compress", m, "info-lost code-file", "info-lost|code-file", "compress code-file head/1600")
        base, win = (4, 22, 190138), (5, 22, 222303)
        self.assertTrue(better(win, base))
        ok, why = solution_gate(win, base, c, tb)
        self.assertTrue(ok, why)
        self.assertTrue(structure_gate(c, tb)[0])

    def test_thin_rule_is_opt_in(self):
        tb = _tb()
        m = dict(tb["ttl"])
        m["test-cmd"] = 10          # destructive single cell, evidence-aligned
        c = Candidate("memory-ttl", m, "stale-memory test-cmd", "stale-memory|test-cmd", "ttl test-cmd=10")
        base, win = (15, 40, 100000), (16, 40, 112000)
        self.assertTrue(better(win, base))
        self.assertTrue(structure_gate(c, tb)[0])
        self.assertTrue(solution_gate(win, base, c, tb, thin=False)[0])
        ok, why = solution_gate(win, base, c, tb, thin=True)
        self.assertFalse(ok, why)

    def test_admit_skips_a_higher_scoring_harm_and_keeps_the_aligned_edit(self):
        tb = _tb()
        harms = harm_candidates(tb, "info-lost|service-log")
        m = {k: list(v) for k, v in tb["compress"].items()}
        m["service-log"] = ["grep-errors", 800]
        good = Candidate("compress", m, "info-lost service-log", "info-lost|service-log",
                         "compress service-log grep-errors/800")
        cands = harms + [good]
        # Harm scores strictly above the aligned edit, which still beats the base.
        base = (10, 40, 100000)
        scores = [(14, 40, 130000), (13, 40, 90000), (12, 40, 80000), (11, 40, 110000)]
        trials = [{"i": i, "ok": True} for i in range(4)]
        self.assertTrue(better(scores[0], base))
        best, info = admit_index(cands, trials, scores, base, tb)
        self.assertEqual(best, 3)
        self.assertEqual(cands[best].desc, good.desc)
        self.assertTrue(all(d.startswith("HARM") for d in info["structure_reject"]))
        self.assertIn(good.desc, info["passed"])


class StructuredProposerTests(unittest.TestCase):
    def test_joint_edit_is_one_scope_and_absent_from_the_closed_grammar(self):
        tb = seed_table()
        info = {"kind": "service-log", "strategy": "head", "limit": 800}
        sig = "info-lost|service-log"
        closed = {c.desc for c in Proposer().candidates("info-lost", "service-log", info, tb, sig)}
        structured = StructuredProposer().candidates("info-lost", "service-log", info, tb, sig)
        descs = [c.desc for c in structured]
        self.assertIn("compress service-log grep-errors/1600", descs)
        self.assertNotIn("compress service-log grep-errors/1600", closed)
        for c in structured:
            self.assertEqual(c.name, "compress")
            self.assertIsNone(c.raw_aura)
            self.assertNotIn(c.name, PROTECTED)
            ok, why = structure_gate(c, tb)
            self.assertTrue(ok, (c.desc, why))
            self.assertEqual(c.meta["taxonomy"]["path"][0], "info-lost")
            self.assertEqual(c.meta["proposer"], "structured")

    def test_overflow_does_not_propose_the_protected_budget(self):
        tb = seed_table()
        info = {"nsub": 4, "biggest": "service-log"}
        cs = StructuredProposer().candidates("context-overflow", "refactor", info, tb, "context-overflow|refactor")
        names = {c.name for c in cs}
        self.assertNotIn("context-budget", names)
        self.assertTrue(names <= {"compress", "delegate"})
        closed = Proposer().candidates("context-overflow", "refactor", info, tb, "context-overflow|refactor")
        self.assertIn("context-budget", {c.name for c in closed})
        for c in cs:
            ok, why = structure_gate(c, tb)
            self.assertTrue(ok, (c.desc, why))

    def test_code_file_joint_is_searched_by_default(self):
        tb = seed_table()
        cs = StructuredProposer().candidates("info-lost", "code-file", {"kind": "code-file"}, tb, "info-lost|code-file")
        descs = [c.desc for c in cs]
        self.assertIn("compress code-file head/1600", descs)
        self.assertIn("compress code-file summarize/1600", descs)
        narrowed = StructuredProposer()
        narrowed.joint_kinds = ERRLINE_KINDS
        narrow = [c.desc for c in narrowed.candidates("info-lost", "code-file", {"kind": "code-file"}, tb, "info-lost|code-file")]
        self.assertNotIn("compress code-file summarize/1600", narrow)

    def test_rediscover_searches_the_gap_under_40(self):
        tb = seed_table()
        sig = "rediscover|test-cmd"
        closed = {c.desc for c in Proposer().candidates("rediscover", "test-cmd", {}, tb, sig)}
        structured = {c.desc for c in StructuredProposer().candidates("rediscover", "test-cmd", {}, tb, sig)}
        self.assertIn("ttl test-cmd=20", structured)
        self.assertNotIn("ttl test-cmd=20", closed)
        self.assertIn("ttl test-cmd=40", structured)
        self.assertIn("ttl test-cmd=160", structured)


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class AuraWorldlineTests(unittest.TestCase):
    def test_dual_gate_rollback_does_not_touch_root(self):
        from aura_harness.control import AuraHarness
        h = AuraHarness("ws")
        try:
            tb = h.table()
            carried = dict(tb["ttl"], **{"test-cmd": 40, "repo-layout": 40})
            # two localized raises, applied one at a time so each edit stays one-scope
            self.assertTrue(h.apply(0, Candidate("memory-ttl", dict(tb["ttl"], **{"test-cmd": 40}),
                                                 "setup", "rediscover|test-cmd", "ttl test-cmd=40"))["ok"])
            self.assertTrue(h.apply(1, Candidate("memory-ttl", carried, "setup", "rediscover|repo-layout",
                                                 "ttl repo-layout=40"))["ok"])
            live = h.table()
            harm = harm_candidates(live, "info-lost|service-log")[0]
            good_map = {k: list(v) for k, v in live["compress"].items()}
            good_map["service-log"] = ["grep-errors", 800]
            good = Candidate("compress", good_map, "info-lost service-log", "info-lost|service-log",
                             "compress service-log grep-errors/800")
            trials = h.trial(2, [harm, good])
            self.assertTrue(all(t["ok"] for t in trials), trials)
            # Harm wins the window; the gate must not hand that index to VERDICT.
            base, scores = (10, 40, 100000), [(14, 40, 120000), (11, 40, 110000)]
            self.assertTrue(better(scores[0], base))
            best, info = admit_index([harm, good], trials, scores, base, live)
            self.assertEqual(best, 1, info)
            vr = h.verdict(2, best, {"base": base, "gates": info}, "info-lost service-log")
            self.assertEqual(vr["verdict"], "KEEP")
            root = h.table()
            self.assertEqual(root["ttl"], carried)
            self.assertEqual(root["compress"]["service-log"], ["grep-errors", 800])
            self.assertEqual(root["budget"], 4000)
            ops = [e["op"] for e in h.log()]
            self.assertIn("trial-ws", ops)
            self.assertIn("keep", ops)
            # A rejected harm index is a ROLLBACK and the carried facts survive.
            again = h.trial(3, [harm])
            self.assertTrue(again[0]["ok"])
            best2, info2 = admit_index([harm], again, [(14, 40, 120000)], base, h.table())
            self.assertEqual(best2, -1, info2)
            vr2 = h.verdict(3, best2, {"base": base, "gates": info2}, "info-lost service-log")
            self.assertEqual(vr2["verdict"], "ROLLBACK")
            self.assertEqual(h.table()["ttl"], carried)
            self.assertTrue(any(e["op"] == "rollback" for e in h.log()))
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
