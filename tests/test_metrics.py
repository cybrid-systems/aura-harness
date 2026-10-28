"""ServeLearnBench-style measurements (rsi/metrics.py) and the extra proposer backends: pure parts, no Aura, no key."""
import os
import tempfile
from pathlib import Path
from unittest import mock
import unittest
from types import SimpleNamespace as NS

from aura_harness.env import make_stream, task_label
from aura_harness.rsi import metrics as M
from aura_harness.rsi.llm import THINK_RE, LLMClient, MixedClient, make_client


class Labels(unittest.TestCase):
    def test_sim_labels(self):
        s = make_stream(0, 400, 200)
        labs = [task_label(t, 0, 200) for t in s]
        self.assertTrue(all(l == "HD" for t, l in zip(s, labs) if t.phase == 1))
        self.assertIn("FS", labs[:200])

    def test_dev_labels(self):
        t = NS(dev=True, phase=0, project="p", kind="bugfix")
        self.assertEqual(task_label(t, 0), "FS")
        self.assertEqual(task_label(NS(dev=True, phase=1, project="p", kind="bugfix"), 0), "HD")


class Metrics(unittest.TestCase):
    def test_split_regressions(self):
        s = [NS(id=i, phase=0, dev=True, project="p", kind="bugfix") for i in range(4)]
        r = M.split(s, [True, False, True, False], [True, True, False, False], 0, 200)
        self.assertEqual((r["FS"]["regressions"], r["FS"]["recoveries"], r["FS"]["n"]), (1, 1, 4))

    def test_aulc(self):
        s = [NS(id=i, phase=int(i >= 2), dev=True, project="p", kind="bugfix") for i in range(5)]
        r = M.aulc(s, [True, True, False, True, True], 0, 2, K=3)
        self.assertEqual(r["onsets"], 1)
        self.assertEqual(r["curve"], [0.0, 1.0, 1.0])

    def test_auc_e_and_repeat(self):
        vs = [{"sig": "a", "candidates": ["x"], "verdict": "ROLLBACK", "ts": 1},
              {"sig": "a", "candidates": ["x"], "verdict": "ROLLBACK", "ts": 5},
              {"sig": "b", "candidates": ["y", "z"], "verdict": "KEEP", "ts": 7}]
        r = M.auc_e(vs, K=2)
        self.assertEqual(r["auc_e"], 0.5)          # a: (0+0)/2, b: (1+1)/2
        self.assertAlmostEqual(r["repeat_rate"], 1 / 3, places=3)

    def test_auc_ka_and_acceptance(self):
        s = [NS(id=i) for i in range(6)]
        vs = [{"sig": "a", "candidates": ["x"], "verdict": "ROLLBACK", "ts": 1},
              {"sig": "a", "candidates": ["y"], "verdict": "KEEP", "ts": 2}]
        r = M.auc_ka(s, vs, [False, False, False, True, False, True], [None, "a", None, "a", "a", "b"], K=5)
        self.assertEqual(r["auc_ka"], 0.5)
        a = M.acceptance(vs)
        self.assertEqual((a["accept_rate"], a["first_keep_latency_tasks"]), (0.5, 1))

    def test_cost_split(self):
        c = M.cost_split([{"cost": 100}] * 4, {"replay_tasks": 8}, {"calls": 2, "prompt_tokens": 10, "completion_tokens": 5})
        self.assertEqual((c["replay_execs_per_served"], c["replay_tokens_est"], c["llm_tokens"]), (2.0, 800, 15))


class Backends(unittest.TestCase):
    def test_minimax_client_defaults(self):
        with mock.patch.dict(os.environ, {"AURA_MINIMAX_ENV": "/nonexistent-minimax.env"}):
            os.environ.pop("AURA_MINIMAX_BASE_URL", None)
            c = LLMClient(provider="minimax", mode="offline")
        self.assertEqual(c.model, "MiniMax-M3.1-Flash")
        self.assertTrue(c.base_url.startswith("https://api.minimax.cn"))

    def test_minimax_base_url_from_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "minimax.env"
            f.write_text('MINIMAX_BASE_URL="https://api.example.test/v1"\nMINIMAX_MODEL=MiniMax-M3\n')
            with mock.patch.dict(os.environ, {"AURA_MINIMAX_ENV": str(f)}):
                os.environ.pop("AURA_MINIMAX_BASE_URL", None)
                c = LLMClient(provider="minimax", mode="offline")
        self.assertEqual(c.base_url, "https://api.example.test/v1")
        self.assertEqual(c.model, "MiniMax-M3.1-Flash")      # the model is not taken from the env file

    def test_mixed_alternates_and_sums(self):
        m = make_client("mixed", mode="offline", cache_dir="/nonexistent-cache")
        self.assertIsInstance(m, MixedClient)
        for _ in range(4):
            self.assertIsNone(m.complete([{"role": "user", "content": "x"}]))
        self.assertEqual([c.u["offline_miss"] for c in m.clients], [2, 2])
        self.assertEqual(m.u["offline_miss"], 4)

    def test_think_stripped(self):
        self.assertEqual(THINK_RE.sub("", "<think>a\nb</think>{}").strip(), "{}")


if __name__ == "__main__":
    unittest.main()
