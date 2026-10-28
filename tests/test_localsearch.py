"""LLM proposes -> swarm fine-tunes (aura_harness/rsi/localsearch.py). Offline; the run-level test needs AURA_BIN."""
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from aura_harness.devenv import make_stream
from aura_harness.env import Memory
from aura_harness.harness import seed_table
from aura_harness.proposer import Proposer
from aura_harness.rsi import llm
from aura_harness.rsi.llm import build
from aura_harness.rsi.localsearch import SwarmRefiner, better, neighbours, train_score


def llm_cand(m, tb):
    c = build(m, tb, "llm: test", "sig-1")
    c.meta.update(proposer="llm", mutation=dict(m))
    return c


class Neighbours(unittest.TestCase):
    def test_every_neighbour_is_a_valid_typed_mutation(self):
        tb = seed_table()
        ms = [{"kind": "compress", "output": "test-log", "strategy": "tail", "limit": 400},
              {"kind": "retry", "tool": "pytest", "err": "timeout", "n": 0},
              {"kind": "ttl", "fact": "test-cmd", "n": 20},
              {"kind": "delegate", "task": "bugfix", "threshold": 2},
              {"kind": "delegate", "task": "feature", "threshold": None},
              {"kind": "route", "need": "search", "tool": "grep"}]
        for m in ms:
            ns = neighbours(m)
            self.assertTrue(ns, m)
            self.assertNotIn(m, ns)
            for x in ns:
                self.assertIsNotNone(build(x, tb, "w", "s"), x)       # range-checked like an LLM mutation
        self.assertEqual({x["tool"] for x in neighbours(ms[5])}, {"rg-json", "lsp-find"})
        self.assertEqual(sorted(x["n"] for x in neighbours(ms[1])), [1, 2])
        self.assertTrue(all(2 <= (x["threshold"] or 2) <= 7 for x in neighbours(ms[3])))

    def test_better(self):
        self.assertTrue(better((3, 10, 900), (2, 10, 100)))
        self.assertTrue(better((3, 10, 800), (3, 10, 900)))
        self.assertFalse(better((3, 10, 900), (3, 10, 900)))


class Refine(unittest.TestCase):
    def setUp(self):
        self.tb = seed_table()
        self.tasks = make_stream(0, 60, 30)
        self.mem = Memory(0)
        self.m = {"kind": "compress", "output": "test-log", "strategy": "head", "limit": 300}

    def run_once(self):
        r = SwarmRefiner(rounds=2, width=4, noop=Proposer._noop)
        p = llm_cand(self.m, self.tb)
        out, info = r.refine(42, [p], self.tb, self.tasks, self.mem, 0, 30)
        return r, p, out, info

    def test_coordinator_log_ids_and_lineage(self):
        r, p, out, info = self.run_once()
        ids = [a["id"] for a in info["attempts"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("sw42.") for i in ids))
        self.assertEqual(ids, [f"sw42.{k}" for k in range(1, len(ids) + 1)])          # single writer, in order
        self.assertIs(r.attempts[0], info["attempts"][0])                              # one record, no copies
        self.assertIn(p, out)                                                          # the LLM parent is kept
        par = info["parents"][0]
        self.assertEqual(par["parent_id"], "sw42.1")
        self.assertEqual(par["lineage"][0], "sw42.1")
        # the parent's own score is the replay of the evidence tasks
        from aura_harness.rsi.localsearch import apply_to
        self.assertEqual(tuple(par["parent_score"]), train_score((apply_to(self.tb, p), self.tasks, self.mem, 0, 30)))
        if par["result_id"] != par["parent_id"]:
            ref = out[0]
            self.assertEqual(ref.meta["proposer"], "llm+swarm")
            self.assertEqual(ref.meta["swarm"]["attempt_id"], par["result_id"])
            self.assertTrue(better(tuple(par["result_score"]), tuple(par["parent_score"])))
            self.assertTrue(any(a["accepted"] and a["id"] == par["result_id"] for a in info["attempts"]))

    def test_deterministic_and_memory_untouched(self):
        k0 = dict(self.mem.known)
        a = self.run_once()[3]
        b = self.run_once()[3]
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(self.mem.known, k0)

    def test_rule_candidates_are_not_refined(self):
        c = build(self.m, self.tb, "rule", "s")
        out, info = SwarmRefiner().refine(1, [c], self.tb, self.tasks, self.mem, 0, 30)
        self.assertEqual(out, [c])
        self.assertIsNone(info)


class Providers(unittest.TestCase):
    def test_selectable_providers(self):
        with mock.patch.dict(os.environ, {"AURA_LLM_MODE": "offline"}):
            self.assertEqual(llm.make_client("glm").model, "glm-5.3-flash")
            self.assertEqual(llm.make_client("glm").provider, "glm")
            self.assertEqual(llm.make_client("deepseek").model, "deepseek-flash")
            self.assertEqual(llm.make_client("minimax").provider, "minimax")
            mx = llm.make_client("deepseek,minimax,glm")
            self.assertEqual([c.provider for c in mx.clients], ["deepseek", "minimax", "glm"])
            self.assertEqual(len(llm.make_client("mixed").clients), 2)
            with self.assertRaises(ValueError):
                llm.make_client("gpt")

    def test_glm_request_shape_and_key_never_logged(self):
        import io, tempfile
        d = tempfile.TemporaryDirectory()
        kf = Path(d.name) / "k"
        kf.write_text("glm-NOT-A-REAL-KEY-42")
        seen = []

        def fake(req, timeout=None):
            seen.append((req.full_url, json.loads(req.data), req.get_header("Authorization")))
            b = io.BytesIO(json.dumps({"model": "glm-5.3-flash", "choices": [{"message": {"content": '{"mutations": []}'}}],
                                       "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode())
            return mock.MagicMock(__enter__=lambda s: b, __exit__=lambda *a: False)
        with mock.patch.dict(os.environ, {"GLM_KEY_FILE": str(kf)}), mock.patch("urllib.request.urlopen", fake):
            c = llm.LLMClient(mode="live", cache_dir=d.name + "/cache", provider="glm")
            self.assertEqual(c.complete([{"role": "user", "content": "x"}]), '{"mutations": []}')
        url, body, auth = seen[0]
        self.assertTrue(url.startswith("https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"))
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(auth, "Bearer glm-NOT-A-REAL-KEY-42")
        for f in Path(d.name, "cache").glob("*.json"):
            self.assertNotIn("NOT-A-REAL-KEY", f.read_text())
        self.assertGreater(c.u["cost_usd"], 0)
        d.cleanup()


@unittest.skipUnless(os.environ.get("AURA_BIN") and Path("results/swarm-rsi/deepseek/results.json").is_file(),
                     "needs AURA_BIN + the recorded swarm-rsi bench")
class RecordedSwarmRun(unittest.TestCase):
    def test_replay_offline_with_trace_attempt_ids(self):
        """the recorded LLM+swarm run replays offline bit for bit; every swarm attempt id is in the trace"""
        from aura_harness.devbench import _llm_factory
        from aura_harness.obs import Tracer
        from aura_harness.rsi.loop import run_rsi
        from aura_harness.rsi.m2 import M2Config
        want = json.loads(Path("results/swarm-rsi/deepseek/results.json").read_text())
        w = next(r for r in want if r["config"] == "LLM + swarm + stat admission" and r["seed"] == 0)
        t = Tracer()
        with mock.patch.dict(os.environ, {"AURA_LLM_MODE": "offline", "AURA_LLM_CACHE": "results/llm-cache",
                                          "AURA_LLM_PROVIDER": "deepseek"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            r = run_rsi(0, n=160, shift=80, window=40, min_heldout=10, world="dev", proposer=_llm_factory("llm"),
                        cfg=M2Config(admission="stat", swarm=True), tracer=t, measure=True)
        self.assertEqual(r["llm"]["offline_miss"], 0)
        self.assertEqual(r["kept"], w["kept"])
        self.assertEqual(r["swarm"]["attempts"], w["swarm"]["attempts"])
        spans = t.find("rsi.swarm_attempt")
        self.assertEqual(len(spans), r["swarm"]["attempts"])
        self.assertEqual(len({s.attrs["swarm.attempt_id"] for s in spans}), len(spans))
        for a in r["swarm"]["kept_attempts"]:
            self.assertIn(a, {s.attrs["swarm.attempt_id"] for s in spans})
        self.assertTrue(r["trace"]["validation"]["ok"], r["trace"]["validation"])


if __name__ == "__main__":
    unittest.main()
