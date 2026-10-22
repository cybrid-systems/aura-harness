"""RSI layer tests (docs/rsi-design.md §4 invariants). Aura-backed ones skip without AURA_BIN."""
import json
import os
import unittest
from pathlib import Path

from aura_harness.harness import Candidate, seed_table
from aura_harness.rsi.admission import RetentionGate, target_veto
from aura_harness.rsi.plugins import PLUGINS, Library
from aura_harness.rsi.proposal import RuleSource
from aura_harness.rsi.targets import Target, target_of

HAVE = bool(os.environ.get("AURA_BIN"))
ROOT = Path(__file__).resolve().parents[1]


def key(r):
    return [(v["ts"], v["verdict"], v["chosen"]) for v in r["verdicts"]]


class PureTests(unittest.TestCase):
    def test_targets(self):
        tb = seed_table()
        self.assertEqual(target_of(Candidate("compress", tb["compress"], "", "", "x")), Target.STATE)
        self.assertEqual(target_of(Candidate("compress", None, "", "", "x", raw_aura="(lambda (k) 1)")), Target.CODE)
        c = Candidate("context-budget", None, "", "", "x", raw_aura="(lambda () 8000)")
        self.assertEqual(target_of(c), Target.CONTROL)
        self.assertIn("not admissible", target_veto(c))

    def test_plugins_cover_mutable(self):
        from aura_harness.harness import MUTABLE
        self.assertEqual(sorted(PLUGINS), sorted(MUTABLE))

    def test_library_dedups(self):
        lib = Library()
        a = lib.add("ttl", {"x": 1}, "d", "s", 1, 0)
        b = lib.add("ttl", {"x": 1}, "d", "s", 2, 0)
        self.assertIs(a, b)
        self.assertEqual(a.uses, 2)

    def test_source_gets_verdicts_only(self):
        s = RuleSource()
        with self.assertRaises(ValueError):
            s.feedback("sig", {"heldout": 3}, [])

    def test_retention_budget(self):
        g = RetentionGate(rho=0.1, decay_every=0)
        g.spent = 0
        self.assertEqual(g.check(0, 0, {}, {}, 0, 200), (True, {"suite": 0}))


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class AuraRSITests(unittest.TestCase):
    def test_retention_off_equals_legacy(self):
        from aura_harness.agent import run_stream
        from aura_harness.rsi.loop import run_rsi
        a = run_stream("aura-gated", 1, n=240)
        b = run_rsi(1, n=240)
        self.assertEqual(key(a), key(b))
        self.assertEqual(a["final_source"], b["final_source"])
        self.assertEqual(a["success"], b["success"])

    def test_supervisor_restart_preserves_state(self):
        from aura_harness.agent import run_stream
        from aura_harness.rsi.loop import run_rsi
        from aura_harness.rsi.supervisor import SupervisedAura
        a = run_stream("aura-gated", 2, n=240)
        h = SupervisedAura()
        h.inject = {3, 6, 9, 14, 21}           # kill before table / trial / verdict calls
        b = run_rsi(2, n=240, backend=h)
        self.assertGreaterEqual(b["restarts"], 5)
        self.assertEqual(key(a), key(b))
        self.assertEqual(a["final_source"], b["final_source"])

    def test_supervisor_survives_4670_trace(self):
        from aura_harness.rsi.supervisor import SupervisedAura
        os.environ["AURA_HARNESS_KNOBS"] = "1"
        try:
            h = SupervisedAura()
            last = None
            for line in (ROOT / "acceptance" / "4670" / "stdin.txt").read_text().splitlines():
                f = line.split("\t")
                if f[0] != "APPLY":
                    continue
                r = h.apply(int(f[1]), Candidate(f[2], None, "fuzz", "fuzz", f[4], raw_aura=f[3]))
                if r.get("ok"):
                    last = r["table"]
            self.assertEqual(json.dumps(h.table(), sort_keys=True), json.dumps(last, sort_keys=True))
            self.assertEqual(h.h.pipe.call("PING").get("pong"), True)
            h.close()
        finally:
            del os.environ["AURA_HARNESS_KNOBS"]
