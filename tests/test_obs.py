"""Run tracing (aura_harness/obs.py, docs/observability.md). Aura-backed tests skip without AURA_BIN."""
import json
import os
import tempfile
import unittest

from aura_harness.obs import Tracer, swarm_trace, validate_rsi

HAVE = bool(os.environ.get("AURA_BIN"))


class TracerTests(unittest.TestCase):
    def test_spans_and_otlp_shape(self):
        t = Tracer("t", run_id="r1", extra="x")
        with t.span("a", k=1) as a:
            b = t.start("b", a, flag=True, f=1.5, lst=[1, 2])
            b.event("e", n=3)
            b.end()
        self.assertEqual([s.name for s in t.spans], ["b", "a"])
        self.assertEqual(t.find("b")[0].parent_id, a.span_id)
        d = t.otlp()
        rs = d["resourceSpans"][0]
        self.assertIn({"key": "run.id", "value": {"stringValue": "r1"}}, rs["resource"]["attributes"])
        sp = {s["name"]: s for s in rs["scopeSpans"][0]["spans"]}
        self.assertEqual(sp["b"]["parentSpanId"], sp["a"]["spanId"])
        self.assertEqual(len(sp["b"]["traceId"]), 32)
        self.assertEqual(len(sp["b"]["spanId"]), 16)
        attrs = {x["key"]: x["value"] for x in sp["b"]["attributes"]}
        self.assertEqual(attrs["flag"], {"boolValue": True})
        self.assertEqual(attrs["f"], {"doubleValue": 1.5})
        self.assertEqual(attrs["lst"]["arrayValue"]["values"][0], {"intValue": "1"})
        self.assertEqual(sp["b"]["events"][0]["name"], "e")
        self.assertLessEqual(int(sp["a"]["startTimeUnixNano"]), int(sp["b"]["startTimeUnixNano"]))
        with tempfile.TemporaryDirectory() as tmp:
            p = t.write_otlp(os.path.join(tmp, "x.json"))
            with open(p) as fh:
                self.assertEqual(json.load(fh), t.otlp())
            q = t.write_jsonl(os.path.join(tmp, "x.jsonl"))
            with open(q) as fh:
                self.assertEqual(len(fh.read().splitlines()), 2)

    def test_error_status(self):
        t = Tracer()
        with self.assertRaises(ValueError):
            with t.span("boom"):
                raise ValueError("x")
        self.assertEqual(t.spans[0].status[0], "error")
        self.assertEqual(t.otlp()["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["status"]["code"], 2)

    def _rsi_trace(self, keep_prov="ws3/m4"):
        t = Tracer()
        r = t.start("rsi.candidate_round")
        t.start("rsi.trial", r, **{"cand.i": 0, "cand.desc": "a", "trial.ok": True, "aura.prov": "ws3/m4"}).end()
        t.start("rsi.trial", r, **{"cand.i": 1, "cand.desc": "b", "trial.ok": False, "aura.prov": ""}).end()
        t.start("rsi.verdict", r, **{"verdict": "KEEP", "verdict.where": "aura", "chosen": "a",
                                     "aura.prov": keep_prov}).end()
        t.start("rsi.verdict", r, **{"verdict": "ROLLBACK", "verdict.where": "aura", "chosen": "",
                                     "aura.prov": ""}).end()
        t.start("rsi.verdict", r, **{"verdict": "ROLLBACK", "verdict.where": "host", "chosen": ""}).end()
        return t

    def test_validate_rsi_ok(self):
        audit = [{"op": "trial-ws"}, {"op": "blocked"}, {"op": "keep", "prov": "ws3/m4"}, {"op": "rollback"}]
        v = validate_rsi(self._rsi_trace(), audit, {"version": 1, "mutation_log": []})
        self.assertTrue(v["ok"], v)

    def test_validate_rsi_catches_mismatch(self):
        audit = [{"op": "trial-ws"}, {"op": "keep", "prov": "ws3/m4"}]           # a lost rollback + a lost trial
        v = validate_rsi(self._rsi_trace(), audit, {"version": 1})
        self.assertFalse(v["ok"])
        self.assertFalse(v["checks"]["rollback"]["ok"])
        self.assertFalse(v["checks"]["trials"]["ok"])
        v = validate_rsi(self._rsi_trace(keep_prov="ws3/m0"), [{"op": "trial-ws"}, {"op": "blocked"},
                                                                 {"op": "keep", "prov": "ws3/m0"}, {"op": "rollback"}])
        self.assertEqual(v["checks"]["keep_prov_missing"], 1)

    def test_swarm_trace_rows(self):
        t = Tracer()
        rows = [["0", "1", "5", "9", "64", "0", "merged"], ["1", "0", "2", "12", "128", "1", "merged"],
                ["1", "2", "3", "13", "64", "0", "rollback"]]
        res = {"merged": 2, "done": 2, "rolled-back": 1, "evals": 300, "rebinds": 1, "wall-ms": 20,
               "process-wall-ms": 50}
        v = swarm_trace(t, "swarm", res, rows, 0)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["evals_attributed"], 192)
        self.assertEqual(len(t.find("swarm.task")), 3)
        self.assertEqual(t.find("swarm.task")[0].attrs["cost.wall_ms"], 4)
        v = swarm_trace(Tracer(), "swarm", dict(res, merged=3), rows, 0)
        self.assertFalse(v["ok"])
        # shared counter smaller than the exact per-task attribution: an Aura lost-update finding, not a trace error
        v = swarm_trace(Tracer(), "swarm", dict(res, evals=150), rows, 0)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["shared_counter_lost"], 42)
        self.assertEqual(len(v["warnings"]), 1)


@unittest.skipUnless(HAVE, "needs AURA_BIN")
class AuraTraceTests(unittest.TestCase):
    def test_rsi_trace_validates_against_audit_and_provenance(self):
        from aura_harness.rsi.loop import run_rsi
        t = Tracer()
        out = run_rsi(seed=1, n=200, tracer=t)
        v = out["trace"]["validation"]
        self.assertTrue(v["ok"], v)
        self.assertGreater(v["checks"]["keep"]["trace"], 0)
        self.assertGreater(v["checks"]["rollback"]["trace"], 0)
        self.assertEqual(v["checks"]["trial_prov_missing"], 0)
        keeps = [s for s in t.find("rsi.verdict") if s.attrs["verdict"] == "KEEP"]
        self.assertEqual(len(keeps), sum(1 for x in out["verdicts"] if x["verdict"] == "KEEP"))
        self.assertTrue(all(s.attrs["reason"] for s in t.find("rsi.verdict")))
        tasks = t.find("rsi.task")
        self.assertEqual(len(tasks), 200)
        self.assertEqual(sum(s.attrs["cost.mutations"] for s in tasks), v["checks"]["keep"]["trace"])
        self.assertTrue(all("task.tokens" in s.attrs for s in tasks))

    def test_rsi_trace_off_is_identical(self):
        from aura_harness.rsi.loop import run_rsi
        a = run_rsi(seed=2, n=160)
        b = run_rsi(seed=2, n=160, tracer=Tracer())
        k = lambda r: [(v["ts"], v["verdict"], v["chosen"]) for v in r["verdicts"]]
        self.assertEqual(k(a), k(b))
        self.assertNotIn("trace", a)

    def test_swarm_free_trace(self):
        # N=1: one worker, so the shared counters are race-free and validation must be exact.
        # At N>1 on parallel-body Aura (#4717) shared hash updates race (aura#4730); the trace reports
        # that as shared_counter_lost / problems instead of hiding it (see docs/observability.md).
        from aura_harness.swarm import run
        t = Tracer()
        r = run("free", 1, 64, 8, 2000, timeout=300, tracer=t)
        self.assertEqual(r["accepted"], 1)
        self.assertTrue(r["trace"]["ok"], r["trace"])
        self.assertEqual(r["trace"]["evals_attributed"], r["trace"]["evals"])
        self.assertEqual(len({s.attrs["task.id"] for s in t.find("swarm.task") if s.attrs["outcome"] == "merged"}), 64)

    def test_swarm_parallel_trace_reports_races(self):
        from aura_harness.swarm import run
        t = Tracer()
        r = run("free", 4, 64, 8, 2000, timeout=300, tracer=t)
        tr = r["trace"]
        self.assertEqual(tr["rows"], len(t.find("swarm.task")))
        self.assertEqual(tr.get("shared_counter_lost", 0), max(0, tr["evals_attributed"] - tr["evals"]))
        self.assertEqual(tr["ok"], not tr["problems"])

    def test_supervisor_trace(self):
        from aura_harness.swarm import run_supervisor
        t = Tracer()
        r = run_supervisor(1, 64, 8, tracer=t)
        if r.get("accepted") != 1:
            self.skipTest(f"supervisor run not accepted on this Aura (workers-dead={r.get('workers-dead')}; aura#4730)")
        self.assertTrue(r["trace"]["ok"], r["trace"])

if __name__ == "__main__":
    unittest.main()
