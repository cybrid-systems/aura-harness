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


# ── scoped-grant judge (aura#5377/#5382) ─────────────────────────────
# Host: owns a live workspace define (score), hosts the bus, self-attaches
# as maintainer (role 3, full caps), opens the trial itself and publishes
# the source-carrier patch + evidence five-tuple. Commands on stdin:
#   grant <wl>   derive scoped keep+rollback (bits 24) -> token=<n>|
#   metric <v>   publish metric key 9 value v (canary ticks)
#   score        report (score 5), the live workload result
JHOST = """(require "std/bus" all:)
(set-code "(define (score x) (+ x 1))")
(eval-current)
(define h (bus:host {ws}))
(define ms (bus:attach "" {ws} 3 127 255))
(define msid (car (cdr ms)))
(bus:project-nodes msid)
(define tr (bus:trial msid 3))
(define wl (car (cdr tr)))
(define src (bus:publish-source msid "(lambda (x) (+ x 10))"))
(bus:publish-patch msid {node} bus:source-field (car (cdr src)) wl 0)
(define d (car (cdr (bus:candidate-digest msid wl))))
(bus:bind-evidence msid wl 0 d 7 42 1)
(display "wl=") (display wl) (display "|") (newline)
(display "JHOST-READY") (newline)
(let loop ()
  (let ((l (read-line)))
    (cond
      ((eof-object? l) #f)
      ((and (>= (string-length l) 6) (string=? (substring l 0 6) "grant "))
       (define gwl (string->number (substring l 6 (string-length l))))
       (define g (bus:grant msid 24 255 0 0 gwl))
       (display "token=") (display (car (cdr g))) (display "|") (newline)
       (loop))
      ((and (>= (string-length l) 7) (string=? (substring l 0 7) "metric "))
       (define v (string->number (substring l 7 (string-length l))))
       (bus:publish msid 9 v)
       (display "metric-ok|") (newline)
       (loop))
      ((string=? l "score")
       (display "score=") (display (score 5)) (display "|") (newline)
       (loop))
      (else (loop)))))
(bus:detach msid)
(bus:unhost {ws})
"""


class JudgeHost:
    """The workspace-owner host process with one pending, evidence-bound trial."""

    def __init__(self, test, ws, node=5, canary=False):
        env = _env(ws, test.xdg)
        env["AURA_BUS_EVIDENCE"] = "1"
        if canary:
            env["AURA_BUS_CANARY_WINDOW"] = "3"
            env["AURA_BUS_CANARY_FLOOR"] = "50"
            env["AURA_BUS_CANARY_KEY"] = "9"
        self.p = subprocess.Popen(
            [_aura(), "-e", JHOST.format(ws=ws, node=node)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self.out = ""
        out = self._until("wl=")
        self.wl = int(out[out.rfind("wl=") + 3:].split("|")[0])
        if "JHOST-READY" not in self._until("JHOST-READY"):
            raise unittest.SkipTest("aura has no v0.3.1 closed-loop bus")

    def _until(self, marker):
        deadline = time.time() + 30
        while marker not in self.out:
            if time.time() > deadline:
                raise AssertionError(f"host never said {marker!r}: {self.out!r}")
            line = self.p.stdout.readline()
            if not line:
                raise AssertionError(f"host exited (rc={self.p.poll()}): {self.out!r}")
            self.out += line
        return self.out

    def cmd(self, line, marker):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        return self._until(marker)

    def grant(self):
        out = self.cmd(f"grant {self.wl}", "token=")
        return int(out[out.rfind("token=") + 6:].split("|")[0])

    def score(self):
        out = self.cmd("score", "score=")
        return int(out[out.rfind("score=") + 6:].split("|")[0])

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class JudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="hjudge-")
        cls.xdg = cls.tmp.name

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _server(self, ws):
        from aura_harness.control import AuraHarness
        os.environ["AURA_HARNESS_BUS_WORKSPACE"] = str(ws)
        os.environ["XDG_RUNTIME_DIR"] = self.xdg
        return AuraHarness("ws")

    @staticmethod
    def _state(rows, wl):
        """last ledger record for wl (append-only channel) -> state"""
        return [r for r in rows if r[0] == wl][-1][2]

    def test_judge_without_grant_refused(self):
        host = JudgeHost(self, 993)
        h = self._server(993)
        try:
            self.assertTrue(h.bus_attach()["attached"])
            r = h.bus_judge(host.wl)
            self.assertFalse(r["ok"], r)
            self.assertEqual(r["reason"], "no-grant")
            # the coordinator refuses the bare keep bit too: permission
            rows = h.bus_worldlines()["rows"]
            self.assertEqual(self._state(rows, host.wl), 0)   # still pending
            # a raw keep attempt (same session, no grant): the coordinator
            # itself refuses — permission, and the trial stays pending
            probe = subprocess.run(
                [_aura(), "-e",
                 f'(require "std/bus" all:)\n'
                 f'(define s (bus:attach "" 993 2 3 255))\n'
                 f'(define k (bus:keep (car (cdr s)) {host.wl} 0 0))\n'
                 f'(display "keep=") (display (bus:code k)) (newline)\n'
                 f'(bus:detach (car (cdr s)))\n'],
                env=_env(993, self.xdg), capture_output=True, text=True, timeout=60)
            self.assertIn("keep=permission", probe.stdout, probe.stdout + probe.stderr)
            rows = h.bus_worldlines()["rows"]
            self.assertEqual(self._state(rows, host.wl), 0)
        finally:
            h.close()
            host.close()

    def test_grant_activate_keep(self):
        host = JudgeHost(self, 994)
        token = host.grant()
        h = self._server(994)
        try:
            self.assertTrue(h.bus_attach()["attached"])
            g = h.bus_grant(token, host.wl)
            self.assertTrue(g["ok"], g)
            self.assertEqual(g["worldline"], host.wl)
            self.assertEqual(g["bits"] & 24, 24)              # keep+rollback gained
            self.assertEqual(g["bits"] & 3, 3)                # read|publish kept
            r = h.bus_judge(host.wl)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["verdict"], "KEEP")
            self.assertEqual(r["state"], 1)                   # kept
            self.assertEqual(r["state_name"], "kept")
            self.assertEqual(len(r["evidence"]), 5)           # five-tuple read back
            self.assertEqual(r["evidence"][0], 0)             # baseline gen
            self.assertNotEqual(r["evidence"][1], 0)          # candidate digest
            self.assertEqual(r["evidence"][2:], [7, 42, 1])   # workload seed verifier
            self.assertEqual(len(r["patches"]), 1)            # the source-carrier patch
            self.assertEqual(r["patches"][0][1], 4294967280)  # bus:source-field
            rows = h.bus_worldlines()["rows"]
            self.assertEqual(self._state(rows, host.wl), 1)
            # KEEP applied the candidate to the host's live AST (#5378)
            self.assertEqual(host.score(), 15)
        finally:
            h.close()
            host.close()

    def test_grant_keep_canary_seal(self):
        host = JudgeHost(self, 995, canary=True)
        token = host.grant()
        h = self._server(995)
        try:
            self.assertTrue(h.bus_attach()["attached"])
            self.assertTrue(h.bus_grant(token, host.wl)["ok"])
            r = h.bus_judge(host.wl)
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["state"], 4)                   # canary observation
            self.assertEqual(r["state_name"], "canary")
            # drive the window: 3 above-floor metric ticks seal the canary
            for _ in range(3):
                host.cmd("metric 100", "metric-ok|")
            rows = h.bus_worldlines()["rows"]
            self.assertEqual(self._state(rows, host.wl), 1)   # sealed -> kept
            self.assertEqual(host.score(), 15)
        finally:
            h.close()
            host.close()

    def test_grant_fail_rollback(self):
        host = JudgeHost(self, 996)
        token = host.grant()
        h = self._server(996)
        try:
            self.assertTrue(h.bus_attach()["attached"])
            self.assertTrue(h.bus_grant(token, host.wl)["ok"])
            r = h.bus_judge(host.wl, "fail")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["verdict"], "ROLLBACK")
            self.assertEqual(r["state"], 2)                   # rolled
            rows = h.bus_worldlines()["rows"]
            self.assertEqual(self._state(rows, host.wl), 2)
            self.assertEqual(host.score(), 6)                 # live AST untouched
        finally:
            h.close()
            host.close()

if __name__ == "__main__":
    unittest.main()
