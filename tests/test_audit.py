"""M4 audit: ledger, why/diff views, one-command rollback (Aura-backed parts skip without AURA_BIN)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from aura_harness.harness import Candidate, seed_table, to_lisp
from aura_harness.rsi.ledger import Ledger, pretty, table_delta

HAVE = bool(os.environ.get("AURA_BIN"))


def j(x):
    return json.dumps(x, sort_keys=True)


class LedgerPureTests(unittest.TestCase):
    def test_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "l.jsonl")
            led = Ledger(p)
            tb = seed_table()
            tb2 = json.loads(j(tb))
            tb2["ttl"]["test-cmd"] = 40
            c = Candidate("memory-ttl", tb2["ttl"], "why", "rediscover|test-cmd", "ttl test-cmd=40")
            led.admit("keep", 5, c, tb, tb2, "gate", {"evidence": c.sig})
            led2 = Ledger(p)
            self.assertEqual(led2.next_id, 2)
            r = led2.get(1)
            self.assertEqual(r["delta"], {"test-cmd": [0, 40]})
            self.assertEqual(r["old_body"], to_lisp("memory-ttl", seed_table()["ttl"]))
            s = led2.show(1)
            for part in ("WHY", "DIFF (body)", "DIFF (decision table)", "audit rollback 1"):
                self.assertIn(part, s)

    def test_pretty_sorts_arms(self):
        a = pretty('(lambda (k) (cond ((equal? k "b") 2) ((equal? k "a") 1) (else 0)))')
        b = pretty('(lambda (k) (cond ((equal? k "a") 1) ((equal? k "b") 2) (else 0)))')
        self.assertEqual(a, b)

    def test_table_delta(self):
        self.assertEqual(table_delta({"r": {"a": 1, "b": 2}}, {"r": {"a": 1, "b": 3}}, "r"), {"b": [2, 3]})


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class RollbackTests(unittest.TestCase):
    def _ledger(self, d):
        from aura_harness.rsi.loop import run_rsi
        led = Ledger(Path(d, "l.jsonl"))
        run_rsi(0, n=240, ledger=led)
        self.assertGreaterEqual(len(led.changes()), 2)
        return led

    def _expected_without(self, led, rid):
        from aura_harness.rsi.ledger import replay
        from aura_harness.rsi.supervisor import SupervisedAura
        sub = Ledger(None)
        sub.records = [r for r in led.records if r["id"] != rid]
        h = SupervisedAura()
        try:
            return replay(sub, h)
        finally:
            h.close()

    def test_rollback_restores_exact_earlier_table(self):
        from aura_harness.rsi.ledger import rollback
        from aura_harness.rsi.supervisor import SupervisedAura
        with tempfile.TemporaryDirectory() as d:
            led = self._ledger(d)
            last = led.changes()[-1]["id"]
            want = self._expected_without(led, last)
            h = SupervisedAura()
            try:
                rec, tb = rollback(led, last, h)
            finally:
                h.close()
            self.assertEqual(j(tb), j(want))
            self.assertEqual(rec["why"]["rolls_back"], last)
            self.assertEqual(Ledger(Path(d, "l.jsonl")).records[-1]["op"], "rollback")   # persisted

    def test_rollback_across_supervisor_restart(self):
        from aura_harness.rsi.ledger import replay, rollback
        from aura_harness.rsi.supervisor import SupervisedAura
        with tempfile.TemporaryDirectory() as d:
            led = self._ledger(d)
            last = led.changes()[-1]["id"]
            want = self._expected_without(led, last)
            h = SupervisedAura()
            h.inject = {2, len(led.changes()) + 2}     # kill during the replay and right before the rollback APPLY
            try:
                _rec, tb = rollback(led, last, h)
                self.assertGreaterEqual(h.restarts, 2)
                self.assertEqual(j(tb), j(want))
                self.assertEqual(j(h.table()), j(want))
            finally:
                h.close()
            h2 = SupervisedAura()                        # a fresh process rebuilt from the ledger agrees too
            try:
                self.assertEqual(j(replay(Ledger(Path(d, "l.jsonl")), h2)), j(want))
            finally:
                h2.close()
