"""Bus-face tests (aura-harness#4, aura#5128).

Need a bus-capable Aura (std/bus + bus:host, aura >= 5f567b94a) via
AURA_BIN; skipped otherwise (the pin a6c63aa19 has no std/bus). The host
is a separate aura process owning the workspace bus — the same shape as
a perf round hosting for the harness.
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from aura_harness.bus import BusFace

HAVE = bool(os.environ.get("AURA_BIN"))
ROOT = Path(__file__).resolve().parents[1]

HOST = """(require "std/bus" all:)
(define h (bus:host {ws}))
(display (if (bus:ok? h) "HOST-READY" "HOST-FAIL")) (newline)
(let loop () (let ((l (read-line))) (if (eof-object? l) #f (loop))))
(bus:unhost {ws})
"""

# a perf-shaped proposer peer: hypothesis metric, two trial worldlines
PERF = """(require "std/bus" all:)
(define s (bus:attach "" {ws} 1 31 255))
(define sid (car (cdr s)))
(bus:publish sid 1 100)
(define t1 (bus:trial sid 1))
(bus:keep sid (car (cdr t1)) 0 50)
(define t2 (bus:trial sid 1))
(bus:rollback sid (car (cdr t2)))
(bus:detach sid)
(display "PERF-DONE") (newline)
"""


def _aura():
    return os.environ["AURA_BIN"]


def _env(ws, xdg):
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = xdg
    env.setdefault("AURA_SANDBOX", "off")
    lib = Path(_aura()).resolve().parent.parent / "lib"
    if (lib / "std" / "bus.aura").is_file():
        env["AURA_PATH"] = str(lib) + (":" + env["AURA_PATH"] if env.get("AURA_PATH") else "")
    return env


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class BusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="hbus-")
        cls.xdg = cls.tmp.name
        cls.ws = 991
        cls.host = subprocess.Popen(
            [_aura(), "-e", HOST.format(ws=cls.ws)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=_env(cls.ws, cls.xdg))
        line = cls.host.stdout.readline()
        if "HOST-READY" not in line:
            raise unittest.SkipTest(f"aura has no bus:host ({line.strip()})")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.host.stdin.close()
            cls.host.wait(timeout=10)
        except Exception:
            cls.host.kill()
        cls.tmp.cleanup()

    def _server(self, ws=None):
        from aura_harness.control import AuraHarness
        # the env stays set for the server's lifetime: a supervisor restart
        # respawns it and must re-attach to the same workspace
        os.environ["AURA_HARNESS_BUS_WORKSPACE"] = str(ws if ws is not None else self.ws)
        os.environ["XDG_RUNTIME_DIR"] = self.xdg
        return AuraHarness("ws")

    def test_attach_read_verdict_audit_detach(self):
        # perf publishes first; the harness then reads the SAME image
        subprocess.run([_aura(), "-e", PERF.format(ws=self.ws)],
                       env=_env(self.ws, self.xdg), capture_output=True, text=True, timeout=60)
        h = self._server()
        try:
            r = h.bus_attach()
            self.assertTrue(r["ok"] and r["attached"], r)
            m = h.bus_metrics()
            self.assertEqual(m["status"], "ok")
            self.assertIn([1, 100], m["rows"] or [])
            w = h.bus_worldlines()
            self.assertEqual(w["status"], "ok")
            wrows = w["rows"] or []
            # append-only channel: pending record, then the verdict record
            self.assertEqual([r[2] for r in wrows], [0, 1, 0, 2])
            self.assertEqual([r[0] for r in wrows], [1, 1, 2, 2])
            v = h.bus_verdict(1, True, 7, 10)
            self.assertTrue(v["ok"], v)
            a = h.bus_audit()
            self.assertTrue(a["ok"] and a["count"] > 0, a)
            f = h.bus_finish()
            self.assertTrue(f["ok"])
            self.assertGreater(f["audit"], 0)
        finally:
            h.close()
        # the verdict is committed evidence: a fresh peer reads it back
        h2 = self._server()
        try:
            self.assertTrue(h2.bus_attach()["attached"])
            m = h2.bus_metrics()
            keys = {row[0]: row[1] for row in (m["rows"] or [])}
            self.assertEqual(keys.get(910001), 1)
            self.assertEqual(keys.get(920001), 7)
            self.assertEqual(keys.get(930001), 10)
        finally:
            h2.close()

    def test_no_metrics_vs_read_failure(self):
        # a fresh workspace: ok read with zero records is "none", not error
        ws = self.ws + 1
        host = subprocess.Popen(
            [_aura(), "-e", HOST.format(ws=ws)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=_env(ws, self.xdg))
        try:
            self.assertIn("HOST-READY", host.stdout.readline())
            h = self._server(ws)
            try:
                self.assertTrue(h.bus_attach()["attached"])
                m = h.bus_metrics()
                self.assertEqual(m["status"], "none")
                self.assertEqual(m["rows"] or [], [])
                # after detach the read fails (no session): an error,
                # never "no metrics"
                h.bus_finish()
                face = BusFace(h)
                m2 = face.metrics()
                self.assertEqual(m2["status"], "error")
                self.assertTrue(m2["code"])
            finally:
                h.close()
        finally:
            host.stdin.close()
            host.wait(timeout=10)

    def test_off_is_identical(self):
        env_ws = os.environ.pop("AURA_HARNESS_BUS_WORKSPACE", None)
        try:
            from aura_harness.control import AuraHarness
            h = AuraHarness("ws")
            try:
                self.assertFalse(h.bus_attach()["ok"])
                self.assertEqual(h.bus_metrics()["status"], "error")
                face = BusFace(h)
                self.assertFalse(face.enabled)
                self.assertIsNone(face.verdict(1, 0, True, 1, 1))
                self.assertEqual(face.finish()["attached"], False)
            finally:
                h.close()
        finally:
            if env_ws is not None:
                os.environ["AURA_HARNESS_BUS_WORKSPACE"] = env_ws

    def test_candidate_body_cannot_reach_bus(self):
        from aura_harness.control import AuraHarness
        from aura_harness.harness import Candidate
        h = AuraHarness("ws")
        try:
            body = '(lambda (tool err) (bus:publish 1 2 3) "grep")'
            r = h.pipe.call("ADMIT", "route-tool", body)
            self.assertTrue(r["reason"], "bus verb in a candidate body must be blocked")
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
