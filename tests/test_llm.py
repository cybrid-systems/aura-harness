"""M5 LLM proposer: everything offline (mocked transport / recorded cache); no test touches the network."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from aura_harness.harness import seed_table
from aura_harness.rsi import llm
from aura_harness.rsi.llm import LLMClient, LLMProposer, build, parse
from aura_harness.rsi.proposal import RuleSource

SECRET = "sk-test-NOT-A-REAL-KEY-0123456789"


def resp(content, pt=100, ct=20, hit=40):
    return io.BytesIO(json.dumps({"model": "deepseek-flash", "choices": [{"message": {"content": content}}],
                                  "usage": {"prompt_tokens": pt, "completion_tokens": ct,
                                            "prompt_cache_hit_tokens": hit}}).encode())


class Fake:
    """records requests; returns canned bodies"""
    def __init__(self, *bodies):
        self.bodies, self.reqs = list(bodies), []

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        b = self.bodies.pop(0)
        if isinstance(b, Exception):
            raise b
        return mock.MagicMock(__enter__=lambda s: b, __exit__=lambda *a: False)


class Env(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        kf = Path(self.d.name, "key")
        kf.write_text(SECRET + "\n")
        self.env = mock.patch.dict(os.environ, {"DEEPSEEK_KEY_FILE": str(kf)})
        self.env.start()
        self.cache = Path(self.d.name, "cache")
        mock.patch("time.sleep").start()

    def tearDown(self):
        mock.patch.stopall()
        self.env.stop()
        self.d.cleanup()

    def no_secret_on_disk(self):
        for p in Path(self.d.name).rglob("*"):
            if p.is_file() and p.name != "key":
                self.assertNotIn(SECRET, p.read_text())
                self.assertNotIn("Authorization", p.read_text())


class BuildParse(unittest.TestCase):
    def test_typed_mutations_validate(self):
        tb = seed_table()
        ok = [{"kind": "route", "need": "edit", "tool": "apply-patch"},
              {"kind": "compress", "output": "test-log", "strategy": "grep-errors", "limit": 800},
              {"kind": "retry", "tool": "grep", "err": "timeout", "n": 3},
              {"kind": "ttl", "fact": "test-cmd", "n": 40},
              {"kind": "delegate", "task": "feature", "threshold": 3}]
        descs = [build(m, tb, "w", "s").desc for m in ok]
        self.assertEqual(descs, ["route edit->apply-patch", "compress test-log grep-errors/800",
                                 "retry grep|timeout=3", "ttl test-cmd=40", "delegate feature>=3"])
        bad = [{"kind": "route", "need": "edit", "tool": "rm"}, {"kind": "compress", "output": "test-log",
               "strategy": "tail", "limit": 5000}, {"kind": "compress", "output": "test-log", "strategy": "tail",
               "limit": True}, {"kind": "retry", "tool": "grep", "err": "x; (exit)", "n": 1},
               {"kind": "ttl", "fact": "secrets", "n": 1}, {"kind": "budget", "n": 99999}, {"kind": "route"}, "str",
               {"kind": "delegate", "task": "feature", "threshold": 99}]
        self.assertEqual([build(m, tb, "w", "s") for m in bad], [None] * len(bad))

    def test_parse(self):
        self.assertEqual(parse('x {"mutations":[1,2,3,4]} y'), [1, 2, 3])
        for t in (None, "", "no json", '{"mutations": 3}', "[1]", "{bad"):
            self.assertIsNone(parse(t))


class Client(Env):
    def test_offline_never_touches_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            c = LLMClient(mode="offline", cache_dir=self.cache)
            self.assertIsNone(c.complete([{"role": "user", "content": "x"}]))
            self.assertEqual(c.u["offline_miss"], 1)

    def test_live_records_then_replays_offline_without_secret(self):
        f = Fake(resp('{"mutations":[]}'))
        with mock.patch("urllib.request.urlopen", f):
            c = LLMClient(mode="live", cache_dir=self.cache)
            self.assertEqual(c.complete([{"role": "user", "content": "x"}]), '{"mutations":[]}')
        self.assertEqual(f.reqs[0].get_header("Authorization"), "Bearer " + SECRET)   # read from the file
        self.assertEqual(json.loads(f.reqs[0].data)["model"], "deepseek-flash")
        self.assertAlmostEqual(c.u["cost_usd"], (60 * 0.15 + 40 * 0.003 + 20 * 0.60) / 1e6)
        self.assertFalse(any(SECRET in repr(v) for v in vars(c).values()))
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            c2 = LLMClient(mode="offline", cache_dir=self.cache)
            self.assertEqual(c2.complete([{"role": "user", "content": "x"}]), '{"mutations":[]}')
            self.assertEqual(c2.u["cache_hits"], 1)
        self.no_secret_on_disk()

    def test_retry_then_success_and_give_up(self):
        f = Fake(TimeoutError(), urllib.error.URLError("x"), resp('{"mutations":[]}'))
        with mock.patch("urllib.request.urlopen", f):
            c = LLMClient(mode="live", cache_dir=self.cache, retries=3)
            self.assertIsNotNone(c.complete([{"role": "user", "content": "a"}]))
            self.assertEqual((c.u["retries"], c.u["errors"]), (2, 0))
        f = Fake(urllib.error.HTTPError("u", 401, "no", {}, None))
        with mock.patch("urllib.request.urlopen", f):
            self.assertIsNone(c.complete([{"role": "user", "content": "b"}]))
            self.assertEqual((len(f.reqs), c.u["errors"]), (1, 1))              # auth errors are not retried

    def test_call_and_token_caps(self):
        f = Fake(resp('{"mutations":[]}', pt=900, ct=200), resp('{"mutations":[]}'))
        with mock.patch("urllib.request.urlopen", f):
            c = LLMClient(mode="live", cache_dir=self.cache, max_tokens=1000)
            c.complete([{"role": "user", "content": "a"}])
            self.assertIsNone(c.complete([{"role": "user", "content": "b"}]))
            self.assertEqual((c.u["calls"], c.u["budget_skip"]), (1, 1))
            c = LLMClient(mode="live", cache_dir=Path(self.d.name, "c2"), max_calls=0)
            self.assertIsNone(c.complete([{"role": "user", "content": "a"}]))


class Scripted:
    def __init__(self, *texts):
        self.texts, self.model, self.mode, self.u, self.prompts = list(texts), "fake", "fake", {}, []

    def complete(self, messages):
        self.prompts.append(messages)
        return self.texts.pop(0)


class Ep:  # minimal evidence episode
    class task:
        kind, project, id = "bugfix", "api", 7
    success, mode, rediscovered, calls = False, "tool-error", [], [("edit", "sed", "code-file", 0)]
    fail = {"tool": "sed", "err": "bad-args", "need": "edit", "transient": False}
    retry_tools, nsub = {}, 1


class Proposer(unittest.TestCase):
    def test_malformed_counted_and_only_typed_candidates(self):
        cl = Scripted("not json", '{"mutations":[{"kind":"route","need":"edit","tool":"apply-patch"},'
                                  '{"kind":"route","need":"edit","tool":"rm -rf"},{"kind":"budget"}]}')
        p = LLMProposer(client=cl, min_evidence=1)
        tb = seed_table()
        self.assertIsNone(p.observe(Ep, tb))                      # malformed response -> no candidates
        cs = p.observe(Ep, tb)
        self.assertEqual([c.desc for c in cs], ["route edit->apply-patch"])
        self.assertIsNone(cs[0].raw_aura)                         # a typed table edit, never free-form Lisp
        self.assertEqual((p.n["malformed_responses"], p.n["malformed_mutations"], p.n["mutations"]), (1, 2, 3))

    def test_paused_makes_no_call(self):
        cl = Scripted()
        p = LLMProposer(client=cl, min_evidence=1)
        p.paused = True
        self.assertIsNone(p.observe(Ep, seed_table()))
        self.assertEqual(cl.prompts, [])

    def test_sees_only_verdicts(self):
        cl = Scripted('{"mutations":[{"kind":"retry","tool":"sed","err":"bad-args","n":0}]}',
                      '{"mutations":[]}')
        src = RuleSource(LLMProposer(client=cl, min_evidence=1, blend="hybrid"))
        tb = seed_table()
        cs = src.observe(Ep, tb)
        self.assertEqual(cs[0].desc, "retry sed|bad-args=0")
        self.assertGreater(len(cs), 1)                             # hybrid adds the scripted ones
        with self.assertRaises(ValueError):
            src.feedback(cs[0].sig, {"score": 16, "heldout": [1, 2]}, [])
        src.feedback(cs[0].sig, "ROLLBACK", [])
        src.p.evidence[cs[0].sig] = 10
        src.observe(Ep, tb)
        u = json.loads(cl.prompts[-1][1]["content"])
        self.assertTrue(u["your_earlier_edits_and_verdicts"][0].endswith(": ROLLBACK"))
        blob = json.dumps(cl.prompts)
        for leak in ("heldout", "held-out", "score", "billing", "search-svc"):
            self.assertNotIn(leak, blob.replace("hidden tasks", ""))


@unittest.skipUnless(os.environ.get("AURA_BIN") and Path("results/llm-cache").is_dir(), "needs AURA_BIN + cache")
class RecordedReplay(unittest.TestCase):
    def test_dev_run_replays_from_recorded_responses(self):
        """the committed live responses reproduce the bench run offline, bit for bit, with no network"""
        from aura_harness.devbench import _llm_factory
        from aura_harness.rsi.loop import run_rsi
        want = json.loads(Path("results/m5/results.json").read_text())
        w = next(r for r in want if r["config"] == "RSI + LLM proposer (M5)" and r["seed"] == 0)
        with mock.patch.dict(os.environ, {"AURA_LLM_MODE": "offline", "AURA_LLM_CACHE": "results/llm-cache"}), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            r = run_rsi(0, n=160, shift=80, window=40, min_heldout=10, world="dev", proposer=_llm_factory("llm"))
        self.assertEqual(r["llm"]["offline_miss"], 0)
        self.assertEqual(r["kept"], w["kept"])
        self.assertAlmostEqual(r["success"], w["stream_success"])
