"""M6 (HarnessPro mapping): tier selection, M6 typed mutations, dev world v2, planner, label-free admission. Offline;
the Aura guard tests need AURA_BIN."""
import copy
import json
import os
import unittest

from aura_harness.devenv import compress, make_stream, run_asserts, task_spec
from aura_harness.env import Memory, run_task
from aura_harness.harness import post_check, seed_table, to_lisp, to_python
from aura_harness.rsi.m6 import (ABLATION, Planner, TestSynth, analyze, apply_plan, build, coreset, parse_plans,
                                 recall_study, run_set, scripted_plans, select_tiers)


def good_v2():
    tb = seed_table()
    tb["route"].update(edit="apply-patch", test="pytest-q")
    tb["compress"]["test-log"] = ["fold", 800]
    return tb


def M(i, pr, cost, lat=1.0):
    return {"id": i, "pr": pr, "cost": cost, "latency": lat}


class Fake:
    def __init__(self, text):
        self.text, self.n, self.u = text, 0, {}

    def complete(self, messages):
        self.n += 1
        return self.text(messages) if callable(self.text) else self.text


class TierSelection(unittest.TestCase):
    def test_filter_and_weights(self):
        pool = [M("h0", .5, 100), M("a", .6, 80), M("b", .9, 200), M("c", .7, 120), M("d", .4, 10),
                M("e", .6, 90)]           # d below h0, e dominated by a
        t = select_tiers(pool, .5)
        # survivors a, b, c (h0 is dominated by a): pmax .9 pmin .6, cmax 200 cmin 80
        live = (("a", .6, 80), ("b", .9, 200), ("c", .7, 120))
        for tier, (wa, wb) in (("lite", (1, 2)), ("medium", (1, 1)), ("heavy", (2, 1))):
            J = {m: wa * ((.9 - p) / .3) ** 2 + wb * ((c - 80) / 120) ** 2 for m, p, c in live}
            self.assertEqual(t[tier]["id"], min(J, key=J.get), tier)
        self.assertEqual((t["lite"]["id"], t["medium"]["id"], t["heavy"]["id"]), ("c", "c", "b"))
        self.assertNotIn("d", [m["id"] for m in t["keep"]])
        self.assertNotIn("e", [m["id"] for m in t["keep"]])
        self.assertLessEqual(len(t["keep"]), 3)

    def test_single_member(self):
        t = select_tiers([M("h0", .5, 100)], .5)
        self.assertEqual({t[k]["id"] for k in ("lite", "medium", "heavy")}, {"h0"})


class Mutations(unittest.TestCase):
    def test_tier_hook_fold(self):
        tb = seed_table()
        c = build({"kind": "tier", "task": "refactor", "nsub": [3, 7], "tier": "deep"}, tb, "w", "s")
        self.assertEqual(c.name, "task-tier")
        self.assertEqual(c.value["refactor|5"], "deep")
        self.assertEqual(c.value["refactor|2"], "standard")
        self.assertIsNone(build({"kind": "tier", "task": "refactor", "nsub": [0, 9], "tier": "deep"}, tb, "w", "s"))
        self.assertIsNone(build({"kind": "tier", "task": "refactor", "tier": "max"}, tb, "w", "s"))
        h = build({"kind": "hook", "tier": "lean", "economy": 5, "strict": 9, "finalize": 20}, tb, "w", "s")
        self.assertEqual(h.value["lean"], [5, 9, 20])
        self.assertIsNone(build({"kind": "hook", "tier": "lean", "economy": 9, "strict": 5, "finalize": 20}, tb, "w", "s"))
        self.assertIsNone(build({"kind": "hook", "tier": "lean", "economy": 1, "strict": 2, "finalize": 99}, tb, "w", "s"))
        f = build({"kind": "compress", "output": "test-log", "strategy": "fold", "limit": 900}, tb, "w", "s")
        self.assertEqual(f.value["test-log"], ["fold", 900])
        # ablations: a kind that is not enabled is rejected
        self.assertIsNone(build({"kind": "hook", "tier": "lean", "economy": 5, "strict": 9, "finalize": 20}, tb, "w",
                                "s", ABLATION["router"]))
        self.assertIsNone(build({"kind": "tier", "task": "bugfix", "tier": "lean"}, tb, "w", "s", ABLATION["hook"]))

    def test_apply_plan_merges_per_component(self):
        tb = seed_table()
        new, cs, bad = apply_plan(tb, [{"kind": "tier", "task": "bugfix", "nsub": 1, "tier": "lean"},
                                       {"kind": "tier", "task": "refactor", "nsub": [3, 7], "tier": "deep"},
                                       {"kind": "route", "need": "edit", "tool": "apply-patch"},
                                       {"kind": "route", "need": "edit", "tool": "rm -rf"}], "w", ABLATION["full"])
        self.assertEqual(bad, 1)
        self.assertEqual(sorted(c.name for c in cs), ["route-tool", "task-tier"])
        self.assertIsNone(post_check(new, tb))

    def test_compilers_agree(self):
        tb = seed_table()
        tb["tier"]["refactor|3"] = "deep"
        tb["hook"]["lean"] = [4, 8, 16]
        for name, comp in (("task-tier", "tier"), ("tool-budget", "hook")):
            ns = {}
            exec(to_python(name, tb[comp]), ns)
            fn = ns[name.replace("-", "_")]
            for k, v in tb[comp].items():
                a = k.split("|")
                if name == "task-tier":
                    a[1] = int(a[1])
                self.assertEqual(json.dumps(fn(*a)), json.dumps(v))
            self.assertTrue(to_lisp(name, tb[comp]).startswith("(lambda ("))


class WorldV2(unittest.TestCase):
    def test_fold(self):
        t = "start\n" + "warn x\n" * 50 + "FAIL: test_a_0\n" + "x" * 9000 + "\nRan 3 tests\n"
        out = compress(t, "fold", 400)
        self.assertIn("[previous line repeated 49 more times]", out)
        self.assertIn("Ran 3 tests", out)
        self.assertLessEqual(len(out), 1600 + 40)

    def test_v1_unchanged_by_m6_defines(self):
        """world v1 never reads the tier / hook entries: exotic values do not change an episode"""
        ts = make_stream(3, 6, 3)
        a, b = seed_table(), seed_table()
        b["tier"] = {k: "compact" for k in b["tier"]}
        b["hook"] = {k: [1, 1, 1] for k in b["hook"]}
        b["route"].update(edit="apply-patch")
        a["route"].update(edit="apply-patch")
        ea = [run_task(t, a, Memory(3), 3).summary() for t in ts]
        eb = [run_task(t, b, Memory(3), 3).summary() for t in ts]
        self.assertEqual(ea, eb)

    def test_tiers_hook_and_hidden_grader(self):
        ts = make_stream(0, 40, 20, v2=True)
        tb = good_v2()
        deep, comp = copy.deepcopy(tb), copy.deepcopy(tb)
        deep["tier"] = {k: "deep" for k in tb["tier"]}
        comp["tier"] = {k: "compact" for k in tb["tier"]}
        ed, ec = run_set(deep, ts, 0), run_set(comp, ts, 0)
        self.assertGreater(sum(e.cost for e in ed), sum(e.cost for e in ec))
        wrong = [e for e in ec if e.mode == "wrong-fix"]
        self.assertTrue(wrong)
        for e in wrong:
            self.assertTrue(e.claimed)
            self.assertFalse(e.success)
            self.assertTrue(all(e.final_src.values()))
        self.assertGreaterEqual(sum(e.success for e in ed), sum(e.success for e in ec))
        tight = copy.deepcopy(tb)
        tight["hook"]["standard"] = [2, 3, 4]
        et = run_set(tight, ts[:10], 0)
        self.assertTrue(any(e.mode == "budget-block" for e in et))
        self.assertTrue(any(e.nudges for e in et))

    def test_run_asserts_isolated(self):
        self.assertEqual(run_asserts("def f(x):\n    return x + 1\n", ["f(1) == 2", "f(0) == 5", "g(1)"]),
                         [True, False, False])
        self.assertEqual(run_asserts("def f(x) syntax error", ["f(1) == 2"]), [False])


class PlannerAnalyzer(unittest.TestCase):
    def test_analyze_and_scripted_plans(self):
        ts = coreset([t for t in make_stream(0, 40, 20, v2=True) if not t.heldout], 6)
        self.assertEqual(len(ts), 6)
        tb = seed_table()
        d = analyze([run_set(tb, ts, 0, g) for g in range(2)], tb)
        self.assertTrue(d["failures"])
        ps = scripted_plans(tb, d, ABLATION["full"])
        self.assertEqual([p[0] for p in ps], ["cost-first", "balanced", "perf-first"])
        self.assertTrue(all(p[1] for p in ps))

    def test_llm_plans_and_malformed(self):
        txt = json.dumps({"plans": [{"intent": "cost-first", "mutations": [{"kind": "tier", "task": "bugfix",
                                                                            "nsub": 1, "tier": "lean"}]},
                                    {"intent": "balanced", "mutations": []}, {"intent": "perf-first", "mutations": [
                                        {"kind": "hook", "tier": "deep", "economy": 3, "strict": 2, "finalize": 1}]}]})
        self.assertEqual(len(parse_plans(txt)), 3)
        self.assertIsNone(parse_plans("no json"))
        p = Planner(Fake(txt))
        par = {"id": "h0", "table": seed_table(), "pr": .5, "cost": 10, "latency": 1}
        diag = {"failures": [], "token_waste": []}
        out = p.plans(par, diag, [par])
        self.assertEqual([o[2] for o in out], ["llm"] * 3)
        _, cs, bad = apply_plan(par["table"], out[2][1], "w", ABLATION["full"])
        self.assertEqual((cs, bad), ([], 1))
        self.assertIn("tier", p.system())
        self.assertNotIn('"kind":"hook"', Planner(None, ABLATION["router"]).system())
        q = Planner(Fake("garbage"))
        self.assertEqual(q.plans(par, diag, [par])[0][2], "scripted")
        self.assertEqual(q.n["malformed_responses"], 1)


class LabelFree(unittest.TestCase):
    def test_synth_catches_wrong_fix(self):
        ts = make_stream(0, 40, 20, v2=True)
        tb = good_v2()
        tb["tier"] = {k: "compact" for k in tb["tier"]}
        eps = run_set(tb, ts, 0)
        from aura_harness.devenv import HIDDEN, make_repo

        def oracle(messages):       # a "synthesizer" that writes the hidden assertion + one visible one
            u = json.loads(messages[1]["content"])
            f = u["function"].split("(")[0]
            for t in make_stream(0, 40, 20, v2=True):
                for sp in task_spec(t):
                    if sp["function"] == f:
                        tpl = dict(t.bugs)[f]
                        k = {g: kk for _, fs in make_repo(t.project).mods for g, _, kk in fs}[f]
                        return json.dumps({"asserts": [HIDDEN[tpl].format(f=f, k=k)]})
            return "{}"
        s = TestSynth(Fake(oracle))
        r = recall_study(eps, s, None)
        self.assertGreater(r["claimed_but_wrong"], 0)
        self.assertEqual(r["synth"]["failure_recall"], 1.0)
        self.assertEqual(r["synth"]["false_alarm"], 0.0)
        bad = TestSynth(Fake("not json"))
        self.assertIsNone(bad.asserts(task_spec(ts[0])[0]))
        self.assertEqual(bad.n["malformed"], 1)


@unittest.skipUnless(os.environ.get("AURA_BIN"), "needs AURA_BIN")
class AuraGuard(unittest.TestCase):
    def test_tier_and_hook_through_guard(self):
        from aura_harness.control import AuraHarness
        from aura_harness.harness import Candidate
        from aura_harness.rsi.m6 import deploy_tier
        h = AuraHarness("ws")
        try:
            tb = h.table()
            self.assertEqual(tb["tier"]["refactor|3"], "standard")
            bad = [Candidate("task-tier", None, "w", "s", "bad tier", raw_aura='(lambda (kind nsub) "turbo")'),
                   Candidate("tool-budget", None, "w", "s", "bad hook", raw_aura="(lambda (tier) (list 9 2 1))"),
                   Candidate("tool-budget", None, "w", "s", "huge", raw_aura="(lambda (tier) (list 1 2 99))")]
            self.assertEqual([r["ok"] for r in h.trial(1, bad)], [False, False, False])
            want = good_v2()
            want["tier"]["refactor|3"] = "deep"
            want["hook"]["lean"] = [4, 8, 16]
            r = deploy_tier(want, "heavy", h)
            self.assertTrue(r["matches"], r)
            self.assertEqual(h.decide("tier", "refactor", "3"), "deep")
            self.assertEqual(h.decide("hook", "lean"), [4, 8, 16])
        finally:
            h.close()


if __name__ == "__main__":
    unittest.main()
