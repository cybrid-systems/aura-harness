"""M6: HarnessPro (arXiv 2610.26770) mapped onto aura-harness, with Aura as the control plane.

  HarnessPro                              here
  ----------                              ----
  candidate set A_t (<= 3)                pool of harness tables; every member is reachable from the Aura root by
                                          guarded component rebinds (trial = guard + post-check per component)
  G = 3 rollouts on a 10-task coreset     G fault/model seeds on a greedy max-diversity coreset of train tasks
  analyzer (problems, perf/cost impact)   `analyze`: failure modes (scripted diagnosis) + token-waste flags
  planner: 3 plans I1/I2/I3 per parent    `Planner`: cost-first / balanced / perf-first, each a list of TYPED mutations
  from pool diffs + diagnoses             (route/compress/retry/ttl/delegate + task-tier router + tool-budget hook),
                                          DeepSeek deepseek-flash through the M5 LLMClient (cache, budget, offline);
                                          a scripted planner is the offline fallback and the "-scripted" config
  editor in a separate git workspace      no code editing: mutations compile to Lisp bodies, guarded by server.aura
  synthesized unittests (label-free)      `TestSynth`: 10 fixed assertions per task function, written once from the
                                          task description; `Judge` is the LLM-judge baseline
  filter PR < PR(h0) or dominated         `select_tiers`: same filter, then J = a*d_perf^2 + b*d_cost^2 with
  then J_m per tier, keep <= 3            (1,2) lite, (1,1) medium, (2,1) heavy; latency breaks ties
  task-tier router / staged hook / fold   `task-tier`, `tool-budget` workspace defines, `fold` compress strategy

Admission is unchanged in kind: a plan only reaches the pool through the guard (blocked attempts are audited in
server.aura), the pool is ranked on the selection split, and the tier that is deployed at runtime is applied to the
Aura root with guarded APPLYs after a one-sided sign test on fresh admission tasks says it is not worse than h0
(lite must also be cheaper). Every pool entry, rejection and deployment goes to the audit ledger.
"""
from __future__ import annotations

import copy
import hashlib
import json
import statistics as st
import time
from collections import Counter

from ..env import NEEDS_TOOLS, Memory, run_task
from ..harness import (COMPONENT, FACTS, KINDS, STRATEGIES, TIERS, TKINDS, Candidate, delegate_map,
                       delegate_thresholds, hook_ok)
from ..proposer import Proposer
from .llm import LLMClient, build as build5, parse
from .m2 import fresh_of
from .stat import sign_p

TIER_W = {"lite": (1, 2), "medium": (1, 1), "heavy": (2, 1)}
BASE_KINDS = ("route", "compress", "retry", "ttl", "delegate")
ABLATION = {"full": BASE_KINDS + ("tier", "hook"), "router": BASE_KINDS + ("tier",), "hook": BASE_KINDS + ("hook",),
            "none": BASE_KINDS}
STRATS6 = [s for s in STRATEGIES if s != "none"]


# ---------------------------------------------------------------- typed mutations (M5 kinds + M6 plugins)
def build(m, tb, why, sig, kinds=ABLATION["full"]) -> Candidate | None:
    """validate one typed mutation against `tb` -> Candidate, or None (malformed / kind not enabled)"""
    if not isinstance(m, dict) or m.get("kind") not in kinds:
        return None
    k = m["kind"]
    try:
        if k == "compress":            # M6 adds the fold strategy
            kind, s, lim = m["output"], m["strategy"], m["limit"]
            if kind not in KINDS or s not in STRATS6 or type(lim) is not int or not 100 <= lim <= 2000:
                return None
            v = copy.deepcopy(tb["compress"])
            v[kind] = [s, lim]
            return Candidate("compress", v, why, sig, f"compress {kind} {s}/{lim}")
        if k == "tier":
            kind, t, ns = m["task"], m["tier"], m.get("nsub")
            lo, hi = (ns, ns) if type(ns) is int else (ns or [1, 7])
            if kind not in TKINDS or t not in TIERS or not (type(lo) is int and type(hi) is int and 1 <= lo <= hi <= 7):
                return None
            v = dict(tb["tier"], **{f"{kind}|{n}": t for n in range(lo, hi + 1)})
            return Candidate("task-tier", v, why, sig, f"tier {kind}[{lo}-{hi}]->{t}")
        if k == "hook":
            t, th = m["tier"], [m.get("economy"), m.get("strict"), m.get("finalize")]
            if t not in TIERS or not hook_ok(th, tb["max_steps"]):
                return None
            v = {x: list(y) for x, y in tb["hook"].items()}
            v[t] = th
            return Candidate("tool-budget", v, why, sig, f"hook {t} {th[0]}/{th[1]}/{th[2]}")
    except (KeyError, TypeError, ValueError):
        return None
    return build5(m, tb, why, sig)


def apply_plan(tb, muts, why, kinds) -> tuple[dict, list[Candidate], int]:
    """apply typed mutations in order -> (new table, one merged Candidate per touched component, malformed count)"""
    cur, bad, touched = copy.deepcopy(tb), 0, []
    for m in muts:
        c = build(m, cur, why, "m6", kinds)
        if c is None:
            bad += 1
            continue
        cur[COMPONENT[c.name]] = c.value
        touched = [x for x in touched if x.name != c.name] + [c]
    cands = [Candidate(c.name, cur[COMPONENT[c.name]], why, "m6",
                       "; ".join(x.desc for x in touched if x.name == c.name)) for c in touched]
    return cur, [c for c in cands if tb[COMPONENT[c.name]] != c.value], bad


def diff(a, b) -> dict:
    out = {}
    for comp in ("route", "compress", "retry", "ttl", "delegate", "tier", "hook"):
        d = {k: b[comp][k] for k in b[comp] if a[comp].get(k) != b[comp][k]}
        if d:
            out[comp] = d
    return out


def compact(tb) -> dict:
    """the harness as the planner sees it (defaults folded away)"""
    def fold(m):
        c = Counter(json.dumps(v) for v in m.values())
        d = c.most_common(1)[0][0]
        return {"default": json.loads(d), **{k: v for k, v in m.items() if json.dumps(v) != d}}
    return {"route": tb["route"], "compress": fold(tb["compress"]), "retry": fold(tb["retry"]), "ttl": tb["ttl"],
            "delegate_thresholds": delegate_thresholds(tb["delegate"]), "tier": fold(tb["tier"]), "hook": tb["hook"]}


# ---------------------------------------------------------------- evaluation
def run_set(tb, tasks, seed, rollout=0) -> list:
    """tasks in order under one table (memory carried) -> list of episodes"""
    s = seed + 7919 * rollout
    mem = Memory(s)
    return [run_task(t, tb, mem, s) for t in tasks]


def metrics(eps, signal=None) -> dict:
    """signal(ep) -> bool overrides labels (label-free admission)"""
    ok = [bool(signal(e)) if signal else e.success for e in eps]
    n = max(1, len(eps))
    return {"pr": sum(ok) / n, "cost": sum(e.cost for e in eps) / n, "latency": sum(e.latency for e in eps) / n,
            "true_pr": sum(e.success for e in eps) / n, "ok": ok}


def coreset(tasks, k=10) -> list:
    """greedy max-diversity subset (stand-in for HarnessPro's DPP coreset) over kind/nsub/project/phase"""
    feats = lambda t: {("kind", t.kind), ("nsub", min(t.nsub, 3)), ("proj", t.project), ("phase", t.phase)}
    out, seen = [], Counter()
    pool = list(tasks)
    while pool and len(out) < k:
        best = max(pool, key=lambda t: (sum(1 / (1 + seen[f]) for f in feats(t)), -t.id))
        out.append(best)
        pool.remove(best)
        seen.update(feats(best))
    return sorted(out, key=lambda t: t.id)


# ---------------------------------------------------------------- analyzer
def analyze(rollouts: list[list], tb) -> dict:
    """G rollouts of the coreset -> diagnosis: failure modes with perf impact, token-waste flags with cost impact"""
    p = Proposer()
    eps = [e for r in rollouts for e in r]
    n = len(eps)
    fails = Counter()
    for e in eps:
        if e.success:
            continue
        d = p.diagnose(e) if e.mode not in ("wrong-fix", "budget-block") else (e.mode, e.fail.get("tier", ""), {})
        key = f"{d[0]}|{d[1]}" if d else f"{e.mode}|?"
        if d and d[0] in ("context-overflow", "step-limit"):
            key += f"|nsub={e.task.nsub}|biggest={e.biggest_kind}"
        fails[key] += 1
    flags = []
    costs = [e.cost for e in eps if e.success]
    med = st.median(costs) if costs else 0
    ok_by = {}
    for e in eps:
        ok_by.setdefault((e.task.kind, min(e.task.nsub, 3)), []).append(e)
    for (kind, d), es in sorted(ok_by.items()):
        tier = es[0].tier or "standard"
        sr = sum(e.success for e in es) / len(es)
        rc = sum(e.cost for e in es) / len(es)
        if sr == 1 and tier in ("standard", "deep"):
            flags.append({"flag": "over-provisioned-tier", "task": kind, "difficulty": d, "tier": tier,
                          "success": sr, "tokens_per_task": round(rc)})
        if sr < .67 and tier in ("compact", "lean", "standard"):
            flags.append({"flag": "under-provisioned-tier", "task": kind, "difficulty": d, "tier": tier,
                          "success": round(sr, 2), "wrong_fixes": sum(e.mode == "wrong-fix" for e in es)})
    big = Counter(e.biggest_kind for e in eps if e.success and e.cost > 1.5 * med)
    for kind, c in big.most_common(2):
        flags.append({"flag": "bloated-observation", "output": kind, "tasks": c,
                      "compress": tb["compress"].get(kind)})
    retr = sum(sum(e.retry_tools.values()) for e in eps)
    if retr:
        flags.append({"flag": "retries", "per_task": round(retr / n, 2)})
    steps = [e.steps for e in eps if e.success]
    if steps:
        flags.append({"flag": "steps", "median_success_steps": st.median(steps), "max": max(steps),
                      "nudges_per_task": round(sum(e.nudges for e in eps) / n, 2)})
    m = metrics(eps)
    return {"success": round(m["pr"], 3), "tokens_per_task": round(m["cost"]), "latency_s": round(m["latency"], 1),
            "failures": [{"problem": k, "share": round(v / n, 3)} for k, v in fails.most_common(6)],
            "token_waste": flags}


# ---------------------------------------------------------------- planner
PLAN_SYSTEM = (
    "You evolve a coding agent's harness (its tool routing, output compression, retries, memory, sub-agent "
    "delegation, a task-tier router and a staged tool-budget hook). You get one parent harness, an analysis of "
    "its trajectories (failures with their share, token-waste flags), and the other harnesses in the candidate pool "
    "as diffs against the parent with their metrics. Write exactly 3 plans for the parent:\n"
    "  cost-first: cut tokens/latency while keeping success; balanced: fix the top problem cheaply; "
    "perf-first: maximise success even at a higher cost.\n"
    'Reply with ONLY a JSON object {"plans":[{"intent":"cost-first","mutations":[...]},'
    '{"intent":"balanced","mutations":[...]},{"intent":"perf-first","mutations":[...]}]}, 1-4 mutations each, from:\n'
    '  {"kind":"route","need":NEED,"tool":TOOL}\n'
    '  {"kind":"compress","output":KIND,"strategy":STRAT,"limit":INT 100-2000}\n'
    '  {"kind":"retry","tool":TOOL,"err":ERR,"n":INT 0-5}\n'
    '  {"kind":"ttl","fact":FACT,"n":INT 0-1000}\n'
    '  {"kind":"delegate","task":TASKKIND,"threshold":INT 2-7 or null}\n'
    '{EXTRA}'
    f"NEED->TOOLs: {json.dumps(NEEDS_TOOLS)}\nKIND: {KINDS}\nSTRAT: {STRATS6} (fold = collapse repeated lines, "
    f"then keep head+tail)\nFACT: {FACTS}\nTASKKIND: {TKINDS}\n"
    "Context budget and step limits are fixed. Plans are guarded and scored on hidden tasks; dominated plans are "
    "dropped.")
EXTRA = {
    "tier": '  {"kind":"tier","task":TASKKIND,"nsub":[LO,HI] 1-7,"tier":TIER}  tier for tasks of that kind with LO..HI '
            'subtasks. TIER: compact (cheapest, often wrong on multi-bug tasks) < lean < standard < deep (4x the '
            'reasoning tokens of lean, most reliable)\n',
    "hook": '  {"kind":"hook","tier":TIER,"economy":E,"strict":S,"finalize":F}  staged tool-call budget for tasks of '
            'that tier: a nudge at call E (terser reasoning) and S (converge), calls past F refused; 1<=E<=S<=F<=30, '
            'or 0,0,0 = off\n'}


class Planner:
    """3 plans per parent (cost-first / balanced / perf-first). LLM via the M5 client; scripted fallback."""

    def __init__(self, client: LLMClient | None, kinds=ABLATION["full"]):
        self.client, self.kinds = client, kinds
        self.n = {"plans": 0, "llm_plans": 0, "scripted_plans": 0, "malformed_responses": 0, "mutations": 0,
                  "malformed_mutations": 0}

    def system(self):
        return PLAN_SYSTEM.replace("{EXTRA}", "".join(EXTRA[k] for k in ("tier", "hook") if k in self.kinds))

    def prompt(self, parent, diag, pool):
        others = [{"diff_vs_parent": diff(parent["table"], o["table"]), "success": round(o["pr"], 3),
                   "tokens_per_task": round(o["cost"]), "latency_s": round(o["latency"], 1)}
                  for o in pool if o["id"] != parent["id"]]
        u = {"parent": {"harness": compact(parent["table"]), "success": round(parent["pr"], 3),
                        "tokens_per_task": round(parent["cost"]), "latency_s": round(parent["latency"], 1)},
             "analysis": diag, "pool": others}
        return [{"role": "system", "content": self.system()}, {"role": "user", "content": json.dumps(u, sort_keys=True)}]

    def plans(self, parent, diag, pool) -> list[tuple[str, list]]:
        out = None
        if self.client is not None:
            text = self.client.complete(self.prompt(parent, diag, pool))
            if text is not None:
                out = parse_plans(text)
                if out is None:
                    self.n["malformed_responses"] += 1
        if out:
            self.n["llm_plans"] += len(out)
            src = "llm"
        else:
            out = scripted_plans(parent["table"], diag, self.kinds)
            self.n["scripted_plans"] += len(out)
            src = "scripted"
        self.n["plans"] += len(out)
        return [(i, ms, src) for i, ms in out]


def parse_plans(text):
    if not text:
        return None
    try:
        obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return None
    ps = obj.get("plans") if isinstance(obj, dict) else None
    if not isinstance(ps, list):
        return None
    out = []
    for p in ps[:3]:
        if isinstance(p, dict) and isinstance(p.get("mutations"), list):
            out.append((str(p.get("intent", "?"))[:20], p["mutations"][:4]))
    return out or None


def scripted_plans(tb, diag, kinds) -> list[tuple[str, list]]:
    """deterministic I1/I2/I3 from the analysis (offline fallback, and the scripted-planner config)"""
    top = diag["failures"][0]["problem"] if diag["failures"] else ""
    fix = []
    if top.startswith("info-lost|test-log") or top.startswith("context-overflow"):
        fix = [{"kind": "compress", "output": "test-log", "strategy": "fold", "limit": 800},
               {"kind": "route", "need": "test", "tool": "pytest-q"}]
    elif top.startswith("info-lost|"):
        fix = [{"kind": "compress", "output": top.split("|")[1], "strategy": "fold", "limit": 1200}]
    elif top.startswith("tool-error|"):
        tool, err = top.split("|")[1:3]
        fix = [{"kind": "route", "need": "edit", "tool": "apply-patch"}] if err == "bad-args" else \
            [{"kind": "retry", "tool": tool, "err": err, "n": 3}]
    elif top.startswith("handoff-loss") or "nsub=" in top and "nsub=1" not in top:
        fix = [{"kind": "delegate", "task": "refactor", "threshold": 2}]
    elif top.startswith("budget-block|"):
        fix = [{"kind": "hook", "tier": top.split("|")[1] or "standard", "economy": 0, "strict": 0, "finalize": 0}]
    elif top.startswith("stale-memory") or top.startswith("rediscover"):
        fix = [{"kind": "ttl", "fact": "test-cmd", "n": 40}]
    under = [f for f in diag["token_waste"] if f["flag"] == "under-provisioned-tier"]
    over = [f for f in diag["token_waste"] if f["flag"] == "over-provisioned-tier"]
    up = {"compact": "lean", "lean": "standard", "standard": "deep", "deep": "deep"}
    down = {"deep": "standard", "standard": "lean", "lean": "lean", "compact": "compact"}
    cost, perf = list(fix[:1]), list(fix)
    if "tier" in kinds:
        cost += [{"kind": "tier", "task": f["task"], "nsub": [f["difficulty"], f["difficulty"]],
                  "tier": down[f["tier"]]} for f in over[:2]]
        perf += [{"kind": "tier", "task": f["task"], "nsub": [f["difficulty"], 7 if f["difficulty"] == 3 else
                                                            f["difficulty"]], "tier": up[f["tier"]]} for f in under[:2]]
    if "hook" in kinds:
        stp = next((f for f in diag["token_waste"] if f["flag"] == "steps"), None)
        if stp:
            e = max(2, int(stp["median_success_steps"]) - 2)
            cost.append({"kind": "hook", "tier": "standard", "economy": e, "strict": e + 4,
                         "finalize": min(30, max(e + 8, int(stp["max"]) + 4))})
    return [("cost-first", cost or fix), ("balanced", fix), ("perf-first", perf or fix)]


# ---------------------------------------------------------------- tier selection (a)
def dominated(a, b) -> bool:
    """b dominates a on (success up, cost down)"""
    return b["pr"] >= a["pr"] and b["cost"] <= a["cost"] and (b["pr"] > a["pr"] or b["cost"] < a["cost"])


def select_tiers(pool: list[dict], h0_pr: float, k: int = 3) -> dict:
    """HarnessPro selection: drop pr < pr(h0) and dominated members, normalise, J = a*d_perf^2 + b*d_cost^2 per tier
    (latency breaks ties) -> {"lite"|"medium"|"heavy": member, "keep": [<= k members]}"""
    live = [m for m in pool if m["pr"] >= h0_pr - 1e-9]
    live = [m for m in live if not any(dominated(m, o) for o in live if o is not m)] or \
        sorted(pool, key=lambda m: (-m["pr"], m["cost"]))[:1]
    pmax, pmin = max(m["pr"] for m in live), min(m["pr"] for m in live)
    cmax, cmin = max(m["cost"] for m in live), min(m["cost"] for m in live)
    out = {}
    for tier, (a, b) in TIER_W.items():
        def J(m):
            dp = (pmax - m["pr"]) / (pmax - pmin) if pmax > pmin else 0.0
            dc = (m["cost"] - cmin) / (cmax - cmin) if cmax > cmin else 0.0
            return a * dp * dp + b * dc * dc
        out[tier] = min(live, key=lambda m: (round(J(m), 9), m["latency"], m["id"]))
        out[tier] = dict(out[tier], J=round(J(out[tier]), 4))
    keep = []
    for m in [out["lite"], out["medium"], out["heavy"]] + sorted(live, key=lambda m: (-m["pr"], m["cost"])):
        if m["id"] not in {x["id"] for x in keep} and len(keep) < k:
            keep.append(m)
    out["keep"] = keep
    return out


# ---------------------------------------------------------------- label-free admission (d)
SYNTH_SYSTEM = (
    "You write unit tests from a task description only (you do not see any implementation). For the Python "
    "function described, write exactly 10 independent test assertions as Python boolean expressions that call the "
    "function and must evaluate to True for a correct implementation. Cover typical inputs, edge cases and "
    "boundaries; use only the function and builtins; no imports, no prints. Reply with ONLY a JSON object "
    '{"asserts": ["<expr>", ...]}.')
JUDGE_SYSTEM = (
    "You judge whether a coding agent solved its task. You see the task description, the agent's trajectory "
    "summary and the final source of the function it fixed. Reply with ONLY a JSON object "
    '{"verdict": "pass" | "fail", "reason": "<one sentence>"}.')


class TestSynth:
    """HarnessPro test synthesizer: 10 fixed assertions per task function, generated ONCE from the description"""

    def __init__(self, client: LLMClient):
        self.client = client
        self.cache: dict = {}
        self.n = {"functions": 0, "asserts": 0, "malformed": 0, "missing": 0}

    def asserts(self, spec: dict) -> list[str] | None:
        key = json.dumps(spec, sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        u = {"function": spec["signature"], "description": spec["spec"]}
        text = self.client.complete([{"role": "system", "content": SYNTH_SYSTEM},
                                     {"role": "user", "content": json.dumps(u, sort_keys=True)}])
        out = None
        if text is None:
            self.n["missing"] += 1
        else:
            try:
                obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
                xs = [a for a in obj.get("asserts", []) if isinstance(a, str) and spec["function"] in a
                      and "import" not in a and "__" not in a and len(a) < 300][:10]
                out = xs or None
            except ValueError:
                pass
            if out is None:
                self.n["malformed"] += 1
            else:
                self.n["functions"] += 1
                self.n["asserts"] += len(out)
        self.cache[key] = out
        return out

    def verdict(self, ep) -> bool | None:
        """label-free success: the agent claims success AND every synthesized test passes; None = no tests"""
        from ..devenv import run_asserts, task_spec
        if not ep.claimed:
            return False
        for spec in task_spec(ep.task):
            xs = self.asserts(spec)
            if xs is None:
                return None
            if not all(run_asserts(ep.final_src.get(spec["function"], ""), xs)):
                return False
        return True


class Judge:
    """LLM-judge baseline: reads description + trajectory summary + final source, says pass/fail"""

    def __init__(self, client: LLMClient):
        self.client = client
        self.n = {"calls": 0, "malformed": 0}

    def verdict(self, ep) -> bool | None:
        from ..devenv import task_spec
        if not ep.claimed:
            return False
        traj = {"tool_calls[need,tool]": [list(c[:2]) for c in ep.calls][-16:], "steps": ep.steps,
                "final_visible_test_run": "all visible tests pass", "agent_reports": "done"}
        u = {"task": task_spec(ep.task), "trajectory": traj, "final_source": ep.final_src}
        text = self.client.complete([{"role": "system", "content": JUDGE_SYSTEM},
                                     {"role": "user", "content": json.dumps(u, sort_keys=True)}])
        self.n["calls"] += 1
        try:
            v = json.loads(text[text.index("{"):text.rindex("}") + 1])["verdict"]
            return v == "pass"
        except (ValueError, TypeError, KeyError, AttributeError):
            self.n["malformed"] += 1
            return None


def recall_study(eps, synth: TestSynth, judge: Judge | None) -> dict:
    """failure recall of each label-free signal vs the hidden grader, on claimed-success episodes"""
    claimed = [e for e in eps if e.claimed]
    wrong = [e for e in claimed if not e.success]
    right = [e for e in claimed if e.success]
    out = {"claimed": len(claimed), "claimed_but_wrong": len(wrong), "claimed_and_right": len(right)}
    for name, sig in (("synth", synth.verdict), ("judge", judge.verdict if judge else None)):
        if sig is None:
            continue
        vw = [sig(e) for e in wrong]
        vr = [sig(e) for e in right]
        caught = sum(v is False for v in vw)
        out[name] = {"failure_recall": round(caught / max(1, len(wrong)), 3), "caught": caught,
                     "false_alarm": round(sum(v is False for v in vr) / max(1, len(vr)), 3),
                     "no_signal": sum(v is None for v in vw + vr)}
    return out


# ---------------------------------------------------------------- the loop
def run_m6(seed: int, n: int = 160, shift: int = 80, epochs: int = 4, G: int = 3, core_k: int = 10,
           ablation: str = "full", planner: str = "llm", label_free: bool = False, alpha: float = 0.05,
           start_table: dict | None = None, ledger=None, client: LLMClient | None = None, h=None,
           max_cands: int = 9) -> dict:
    from ..control import AuraHarness
    from ..devenv import make_stream
    t0 = time.perf_counter()
    kinds = ABLATION[ablation]
    stream = make_stream(seed, n, shift, v2=True)
    train = [t for t in stream if not t.heldout]
    sel = [t for t in stream if t.heldout and not fresh_of(t.id)]
    adm = [t for t in stream if t.heldout and fresh_of(t.id)]
    core = coreset(train, core_k)
    own = h is None
    h = h or AuraHarness("ws")
    client = client or (LLMClient(max_calls=400) if planner == "llm" else None)
    pl = Planner(client if planner == "llm" else None, kinds)
    synth = TestSynth(client or LLMClient()) if label_free else None
    signal = synth.verdict if synth else None
    try:
        root = h.table()
        h0 = copy.deepcopy(start_table or root)
        stats = {"guard_blocked": 0, "malformed_plans": 0, "evaluated": 0, "filtered": 0, "epochs": []}

        def score(tb):
            stats["evaluated"] += 1
            m = metrics(run_set(tb, sel, seed), signal)
            return m

        def member(tb, i, parent=None, plan=None, src=None):
            m = score(tb)
            return {"id": i, "table": tb, "pr": m["pr"], "true_pr": m["true_pr"], "cost": m["cost"],
                    "latency": m["latency"], "parent": parent, "plan": plan, "src": src}

        base = member(h0, "h0")
        pool, archive, nid = [base], [base], 1
        for ep_i in range(epochs):
            cands = []
            for par in pool:
                rolls = [run_set(par["table"], core, seed, g) for g in range(G)]
                diag = analyze(rolls, par["table"])
                for intent, muts, src in pl.plans(par, diag, pool):
                    tb, cs, bad = apply_plan(par["table"], muts, f"m6 {intent} on {par['id']}", kinds)
                    pl.n["mutations"] += len(muts)
                    pl.n["malformed_mutations"] += bad
                    if not cs:
                        continue
                    # guard: every touched component goes through server.aura (static check + rebind + post-check)
                    trials = h.trial(1000 * (ep_i + 1) + nid, cs, actor=f"m6-planner:{intent}")
                    blocked = [cs[r["i"]].desc for r in trials if not r["ok"]]
                    if blocked:
                        stats["guard_blocked"] += 1
                        if ledger is not None:
                            for d in blocked:
                                ledger.event("blocked", ep_i, desc=d, why=f"m6 {intent}")
                        continue
                    for r in trials:                       # use the Aura-materialised component values
                        comp = COMPONENT[cs[r["i"]].name]
                        tb[comp] = r["table"][comp]
                    if any(json.dumps(tb, sort_keys=True) == json.dumps(x.get("table", x.get("tb")), sort_keys=True) for x in archive + cands):
                        continue
                    cands.append({"tb": tb, "parent": par["id"], "plan": intent, "src": src,
                                  "desc": "; ".join(c.desc for c in cs), "cs": cs})
            cands = cands[:max_cands]
            new = [dict(member(c["tb"], f"e{ep_i}c{k}", c["parent"], c["plan"], c["src"]), desc=c["desc"])
                   for k, c in enumerate(cands)]
            for m in new:
                nid += 1
            archive += new
            sel_t = select_tiers(pool + new, base["pr"])
            stats["filtered"] += len(pool + new) - len([m for m in pool + new if m["pr"] >= base["pr"] - 1e-9])
            pool = sel_t["keep"]
            stats["epochs"].append({"epoch": ep_i, "candidates": len(new),
                                    "pool": [(m["id"], round(m["pr"], 3), round(m["cost"])) for m in pool],
                                    "tiers": {k: sel_t[k]["id"] for k in TIER_W}})
            if ledger is not None:
                for m in new:
                    ledger.event("m6-candidate", ep_i, id=m["id"], parent=m["parent"], plan=m["plan"], src=m["src"],
                                 desc=m.get("desc"), pr=round(m["pr"], 4), cost=round(m["cost"]),
                                 kept=m["id"] in {x["id"] for x in pool})
        tiers = select_tiers(archive, base["pr"])
        # admission of each tier on fresh tasks (one-sided sign test vs h0; lite must also be cheaper)
        a_base = metrics(run_set(h0, adm, seed), signal)
        admitted = {}
        for name in TIER_W:
            m = tiers[name]
            if m["id"] == "h0":
                admitted[name] = {"id": "h0", "admitted": True, "why": "h0"}
                continue
            a = metrics(run_set(m["table"], adm, seed), signal)
            worse = sum(x and not y for x, y in zip(a_base["ok"], a["ok"]))
            better_ = sum(y and not x for x, y in zip(a_base["ok"], a["ok"]))
            p = sign_p(worse, better_)          # small p = significantly worse than h0
            ok = p >= alpha and (name != "lite" or a["cost"] < a_base["cost"])
            admitted[name] = {"id": m["id"], "admitted": ok, "p_worse": round(p, 4), "worse": worse,
                              "better": better_, "adm_pr": round(a["pr"], 3), "adm_cost": round(a["cost"])}
        out_tiers = {k: (tiers[k] if admitted[k]["admitted"] else base) for k in TIER_W}
        # runtime: deploy the medium tier on the Aura root (guarded APPLY per component, audited)
        dep = out_tiers["medium"]
        applied = []
        for comp_name, comp in COMPONENT.items():
            if json.dumps(root[comp]) != json.dumps(dep["table"][comp]):
                r = h.apply(99999, Candidate(comp_name, dep["table"][comp], "m6 tier deploy: medium", "m6",
                                             f"deploy medium {comp_name}"), actor="m6-tier")
                applied.append((comp_name, bool(r.get("ok")), r.get("reason")))
        if ledger is not None:
            ledger.event("m6-tiers", n, **{k: {"id": out_tiers[k]["id"], "pr": round(out_tiers[k]["pr"], 4),
                                                "cost": round(out_tiers[k]["cost"]),
                                                "admission": admitted[k]} for k in TIER_W},
                         deployed="medium", applied=applied)
        final_root = h.table()
        audit = h.log()
    finally:
        if own:
            h.close()
    strip = lambda m: {k: v for k, v in m.items() if k != "table"}
    return {"seed": seed, "ablation": ablation, "planner": planner, "label_free": label_free,
            "tiers": {k: dict(strip(out_tiers[k]), table=out_tiers[k]["table"]) for k in TIER_W},
            "admission": admitted, "archive": [strip(m) for m in archive], "stats": stats,
            "planner_stats": pl.n, "llm": dict(client.u) if client else None,
            "synth": synth.n if synth else None, "deployed": applied,
            "root_matches_medium": json.dumps(final_root) == json.dumps(out_tiers["medium"]["table"]),
            "audit_n": len(audit), "wall_s": round(time.perf_counter() - t0, 1)}


def deploy_tier(table: dict, tier: str, h=None) -> dict:
    """runtime tier switch: rebind every component that differs from the live root, each through the guard"""
    from ..control import AuraHarness
    own = h is None
    h = h or AuraHarness("ws")
    try:
        root, out = h.table(), []
        for name, comp in COMPONENT.items():
            if json.dumps(root[comp], sort_keys=True) != json.dumps(table[comp], sort_keys=True):
                r = h.apply(0, Candidate(name, table[comp], f"tier switch: {tier}", "m6", f"{tier} {name}"),
                            actor="m6-tier")
                out.append({"define": name, "ok": bool(r.get("ok")), "reason": r.get("reason")})
        return {"tier": tier, "applied": out, "version": len(h.log()),
                "matches": json.dumps(h.table(), sort_keys=True) == json.dumps(table, sort_keys=True)}
    finally:
        if own:
            h.close()
