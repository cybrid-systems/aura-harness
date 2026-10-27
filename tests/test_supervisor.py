"""Supervisor (orchestrated) mode on the swarm toy task (Aura-backed tests skip without AURA_BIN)."""
import os
import unittest

from aura_harness.swarm import SUPERVISOR, run_expr, run_supervisor

NEED = unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")


class SupervisorTest(unittest.TestCase):
    def test_source_present(self):
        src = SUPERVISOR.read_text()
        for name in ("run-supervisor", "run-sv-fail", "run-sv-cancel", "run-sv-ping", "orch-probes", "orch-ask-probe"):
            self.assertIn(f"({name} ", src)

    @NEED
    def test_supervisor_no_lost_no_dup(self):
        for n in (1, 4):
            r = run_supervisor(n, 64, 8, 200000, timeout=300)
            self.assertEqual(r["accepted"], 1)
            self.assertEqual(r["lost"], 0)
            self.assertEqual(r["dup-merges"], 0)
            self.assertEqual(r["rtt-n"], r["jobs-sent"])

    @NEED
    def test_supervisor_worker_failure_redispatch(self):
        r = run_expr("(run-sv-fail 4 64 8 200000 3)", {}, supervisor=True)
        self.assertEqual(r["join-error"], 1)
        self.assertEqual(r["workers-dead"], 1)
        self.assertGreater(r["jobs-redispatched"], 0)
        self.assertEqual(r["accepted"], 1)
        self.assertEqual(r["lost"], 0)

    @NEED
    def test_supervisor_cancel_partial_sound(self):
        r = run_expr("(run-sv-cancel 4 1024 64 2000000 200)", {}, supervisor=True)
        self.assertEqual(r["done-valid"], 1)
        self.assertEqual(r["stopped-early"], 1)

    @NEED
    def test_ping_roundtrip(self):
        r = run_expr("(run-sv-ping 2 20)", {}, supervisor=True)
        self.assertEqual(r["ping-n"], 40)


if __name__ == "__main__":
    unittest.main()
