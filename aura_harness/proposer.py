"""Proposer: reads failed (and costly) trajectories of EVIDENCE tasks plus the current harness, and proposes
mutations of one harness component. Held-out tasks are never shown to it; the gate scores candidates on them.

It is deliberately naive about scope: on context overflow it first asks for a bigger context budget, on a step-limit
failure for more steps. Those touch protected defines and must be blocked by the scope guard; a blocked proposal is
remembered and not repeated.

`LLMProposer` (optional, AURA_HARNESS_LLM_URL) may add free-form Lisp bodies for a mutable define; every one still goes
through the guard and the gate. No number in the README uses it.
"""
from __future__ import annotations

import copy
import json
import os
import random
import urllib.request

from .env import NEEDS_TOOLS, TRANSIENT
from .harness import FACTS, KINDS, Candidate, delegate_map, delegate_thresholds

ALT_STRATS = ["tail", "head-tail", "grep-errors", "summarize"]


class Proposer:
    def __init__(self, min_evidence: int = 3, noise: float = 0.0, seed: int = 0):
        self.min_evidence, self.noise, self.seed = min_evidence, noise, seed
        self.evidence: dict[str, int] = {}
        self.blacklist: dict[str, int] = {}
        self.blocked: set[str] = set()
        self.stats: dict[tuple, list] = {}       # (need, tool) -> [calls, failures]
        self.n_proposals = 0

    # -------------------------------------------------------------- observation
    def _stat(self, need, tool, ok):
        s = self.stats.setdefault((need, tool), [0, 0])
        s[0] += 1
        s[1] += 0 if ok else 1

    def _rate(self, need, tool):
        c, f = self.stats.get((need, tool), [0, 0])
        return (c - f + 1) / (c + 2)          # Laplace prior: untried tools look like 0.5

    def diagnose(self, ep) -> tuple[str, str, dict] | None:
        """-> (mode, key, info) or None"""
        if ep.success:
            if ep.rediscovered:
                return "rediscover", ep.rediscovered[0], {}
            return None
        f, m = ep.fail, ep.mode
        if m == "tool-error":
            return m, f"{f['tool']}|{f['err']}", f
        if m == "info-lost":
            return m, f["kind"], f
        if m == "context-overflow":
            return m, ep.task.kind, dict(f, nsub=ep.task.nsub, biggest=ep.biggest_kind or f.get("kind"))
        if m == "step-limit":
            return m, ep.task.kind, dict(f, nsub=ep.task.nsub, retries=dict(ep.retry_tools))
        if m == "stale-memory":
            return m, f["fact"], f
        if m == "handoff-loss":
            return m, ep.task.kind, dict(f, nsub=ep.task.nsub)
        return None                         # model-error: nothing the harness can do

    def _noisy(self, ep, d):
        """noise ablation: mis-attribute the diagnosis (deterministically) to another component"""
        r = random.Random(f"noise:{self.seed}:{ep.task.id}")
        if self.noise <= 0 or r.random() >= self.noise:
            return d
        choice = r.randrange(4)
        if choice == 0:
            return "info-lost", r.choice(KINDS), {"kind": "", "strategy": "head", "limit": 800}
        if choice == 1:
            need = r.choice(list(NEEDS_TOOLS))
            tool = r.choice(NEEDS_TOOLS[need])
            err = r.choice(["timeout", "bad-args"])
            return "tool-error", f"{tool}|{err}", {"tool": tool, "err": err, "need": need, "transient": err in TRANSIENT}
        if choice == 2:
            return "stale-memory", r.choice(FACTS), {"fact": ""}
        return "rediscover", r.choice(FACTS), {}

    def observe(self, ep, tb: dict) -> list[Candidate] | None:
        for need, tool, _kind, att in ep.calls:
            self._stat(need, tool, att == 0)
        if not ep.success and ep.mode == "tool-error":
            self._stat(ep.fail["need"], ep.fail["tool"], False)
        d = self.diagnose(ep)
        if d is None:
            return None
        d = self._noisy(ep, d)
        mode, key, info = d
        sig = f"{mode}|{key}"
        n = self.evidence.get(sig, 0) + 1
        self.evidence[sig] = n
        at = self.blacklist.get(sig, 0)
        if n < self.min_evidence or (at and n < 2 * at):
            return None
        cands = [c for c in self.candidates(mode, key, info, tb, sig) if c.desc not in self.blocked]
        cands = [c for c in cands if not self._noop(c, tb)]
        if not cands:
            return None
        self.n_proposals += 1
        return cands

    def feedback(self, sig: str, verdict: str, blocked_descs: list[str]):
        self.blocked.update(blocked_descs)
        if verdict == "ROLLBACK":
            self.blacklist[sig] = self.evidence.get(sig, 0)
        else:
            self.evidence[sig] = 0

    @staticmethod
    def _noop(c: Candidate, tb) -> bool:
        if c.raw_aura is not None:
            return False
        from .harness import COMPONENT
        cur = tb[COMPONENT[c.name]]
        return json.dumps(cur, sort_keys=True) == json.dumps(c.value, sort_keys=True)

    # -------------------------------------------------------------- candidate generation
    def candidates(self, mode, key, info, tb, sig) -> list[Candidate]:
        out: list[Candidate] = []
        why = f"{mode} {key}"

        def route(need, tool):
            m = dict(tb["route"])
            m[need] = tool
            out.append(Candidate("route-tool", m, why, sig, f"route {need}->{tool}"))

        def comp(kind, strat, limit):
            m = copy.deepcopy(tb["compress"])
            m[kind] = [strat, int(limit)]
            out.append(Candidate("compress", m, why, sig, f"compress {kind} {strat}/{int(limit)}"))

        def retry(tool, err, n):
            m = dict(tb["retry"])
            m[f"{tool}|{err}"] = n
            out.append(Candidate("retry-limit", m, why, sig, f"retry {tool}|{err}={n}"))

        def ttl(fact, n):
            m = dict(tb["ttl"])
            m[fact] = n
            out.append(Candidate("memory-ttl", m, why, sig, f"ttl {fact}={n}"))

        def deleg(kind, thr):
            t = delegate_thresholds(tb["delegate"])
            if thr is None:
                t.pop(kind, None)
            else:
                t[kind] = thr
            out.append(Candidate("delegate", delegate_map(t), why, sig,
                                 f"delegate {kind}>={thr}" if thr else f"inline {kind}"))

        def protected(name, body, desc):
            out.append(Candidate(name, None, why, sig, desc, raw_aura=body))

        if mode == "tool-error":
            tool, err = key.split("|")
            need = info.get("need") or next(n for n, ts in NEEDS_TOOLS.items() if tool in ts)
            need = "read" if need == "read-config" else need
            alts = sorted((t for t in NEEDS_TOOLS.get(need, []) if t != tool), key=lambda t: -self._rate(need, t))
            cur = tb["retry"].get(key, 1)
            if info.get("transient", err in TRANSIENT):
                if cur < 5:
                    retry(tool, err, min(cur + 2, 5))
                for a in alts[:2]:
                    route(need, a)
            else:
                for a in alts[:2]:
                    route(need, a)
                if cur > 0:
                    retry(tool, err, 0)
        elif mode == "info-lost":
            s, lim = tb["compress"][key]
            if lim * 2 <= 2000:
                comp(key, s, lim * 2)
            for s2 in ALT_STRATS:
                if s2 != s:
                    comp(key, s2, lim)
        elif mode == "context-overflow":
            protected("context-budget", f"(lambda () {2 * tb['budget']})", f"raise context-budget to {2 * tb['budget']}")
            if info.get("nsub", 1) >= 2:
                deleg(key, max(2, info["nsub"]))
            big = info.get("biggest") or "code-file"
            s, lim = tb["compress"][big]
            if lim // 2 >= 200:
                comp(big, s, lim // 2)
            if s != "summarize":
                comp(big, "summarize", lim)
        elif mode == "step-limit":
            protected("max-steps", f"(lambda () {2 * tb['max_steps']})", f"raise max-steps to {2 * tb['max_steps']}")
            if info.get("nsub", 1) >= 2:
                deleg(key, max(2, info["nsub"]))
            rt = info.get("retries") or {}
            if rt:
                (tool, err), _ = max(rt.items(), key=lambda kv: kv[1])
                retry(tool, err, 0)
        elif mode == "stale-memory":
            cur = tb["ttl"].get(key, 0)
            if cur // 4 >= 5:
                ttl(key, cur // 4)
            ttl(key, 0)
        elif mode == "handoff-loss":
            t = delegate_thresholds(tb["delegate"]).get(key)
            if t is not None and t + 2 <= 7:
                deleg(key, t + 2)
            deleg(key, None)
        elif mode == "rediscover":
            cur = tb["ttl"].get(key, 0)
            if cur == 0:
                ttl(key, 40)
                ttl(key, 160)
            elif cur * 2 <= 1000:
                ttl(key, cur * 2)
        return out


class LLMProposer(Proposer):
    """Adds up to 2 free-form Lisp bodies from an OpenAI-compatible endpoint (AURA_HARNESS_LLM_URL / _KEY / _MODEL)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.url = os.environ["AURA_HARNESS_LLM_URL"]
        self.key = os.environ.get("AURA_HARNESS_LLM_KEY", "")
        self.model = os.environ.get("AURA_HARNESS_LLM_MODEL", "default")
        self.source = ""                       # set by the agent loop from SOURCE before each proposal

    def candidates(self, mode, key, info, tb, sig):
        out = super().candidates(mode, key, info, tb, sig)
        prompt = ("You tune an agent harness written as Aura (Lisp) workspace defines. Mutable: route-tool, compress, "
                  "retry-limit, memory-ttl, delegate. Reply with a JSON list of at most 2 [name, lambda-body] pairs.\n"
                  f"Failure: {mode} {key} {info}\nCurrent harness source:\n{self.source}")
        try:
            req = urllib.request.Request(self.url, data=json.dumps({
                "model": self.model, "messages": [{"role": "user", "content": prompt}]}).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                text = json.load(r)["choices"][0]["message"]["content"]
            pairs = json.loads(text[text.index("["):text.rindex("]") + 1])
        except Exception:
            return out
        for name, body in pairs[:2]:
            out.append(Candidate(str(name), None, f"llm: {mode} {key}", sig, f"llm {name}", raw_aura=str(body)))
        return out


def get_proposer(**kw) -> Proposer:
    return LLMProposer(**kw) if os.environ.get("AURA_HARNESS_LLM_URL") else Proposer(**kw)
