"""M5: a real LLM proposer (DeepSeek, OpenAI-compatible) behind the same ProposalSource interface.

Isolation is unchanged: the source sees only evidence-task episodes and KEEP/ROLLBACK verdicts; held-out tasks and
gate scores never reach the prompt. The LLM may only answer with *typed* mutations (route / compress / retry / ttl /
delegate) that are validated against the tool docs and value ranges and then built into the very same Candidate
objects the scripted proposer emits, so they pass the same target policy, guard and gate. Anything else is counted
as malformed and dropped.

Secrets: the API key is read at request time from the file named by DEEPSEEK_KEY_FILE and is never stored on an
object, cached, logged or put in the ledger. The cache and ledger hold prompts, response text and usage only.

Modes (AURA_LLM_MODE): "live" (cache first, then network), "offline" (cache only; misses are counted and yield no
LLM candidates, so tests never touch the network).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..env import NEEDS_TOOLS
from ..harness import FACTS, KINDS, TKINDS, Candidate, delegate_map, delegate_thresholds
from ..proposer import ALT_STRATS, Proposer

BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-flash"            # /models: id "deepseek-flash", name "DeepSeek-V4.1-Flash"
# USD per 1M tokens (DeepSeek list price, off-peak; peak is 2x). Override with AURA_LLM_PRICE="in,cached,out".
PRICE = tuple(float(x) for x in os.environ.get("AURA_LLM_PRICE", "0.15,0.003,0.60").split(","))
STRATS = ["head", *ALT_STRATS]

# Proposer backends (AURA_LLM_PROVIDER = deepseek | minimax | mixed). Keys are only ever read from a key file at
# request time; they are never logged, cached or put in the usage tally.
MINIMAX_BASE_URL = "https://api.minimax.cn/v1"
MINIMAX_MODEL = "MiniMax-M3.1-Flash"          # id as listed by GET /v1/models
MINIMAX_ENV = "/home/box/.config/aura-build/minimax.env"
# MiniMax list price is not pinned in this repo: cost_usd stays 0 unless AURA_MINIMAX_PRICE="in,cached,out" is set.
MINIMAX_PRICE = tuple(float(x) for x in os.environ.get("AURA_MINIMAX_PRICE", "0,0,0").split(","))
THINK_RE = re.compile(r"<think>.*?</think>", re.S)
# GLM-5.3 Flash on the Zhipu coding-plan endpoint; key file $GLM_KEY_FILE (default ~/.glm-key)
GLM_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
GLM_MODEL = "glm-5.3-flash"
GLM_PRICE = tuple(float(x) for x in os.environ.get("AURA_GLM_PRICE", "0.15,0.03,0.50").split(","))


def _minimax_key_file() -> str:
    f = os.environ.get("MINIMAX_API_KEY_FILE")
    if f:
        return f
    for line in Path(os.environ.get("AURA_MINIMAX_ENV", MINIMAX_ENV)).read_text().splitlines():
        if line.startswith("MINIMAX_API_KEY_FILE="):
            return line.split("=", 1)[1].strip().strip('"')
    raise KeyError("MINIMAX_API_KEY_FILE")


def _minimax_env_value(name: str, default: str) -> str:
    """A non-secret setting (base URL, model) from the MiniMax env file, so the harness and aura-scm-agents agree."""
    try:
        for line in Path(os.environ.get("AURA_MINIMAX_ENV", MINIMAX_ENV)).read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"') or default
    except OSError:
        pass
    return default
ERR_RE = re.compile(r"^[a-z][a-z-]{1,20}$")


class LLMClient:
    def __init__(self, mode=None, cache_dir=None, model=MODEL, base_url=BASE_URL, max_calls=200,
                 max_tokens=400_000, timeout=90.0, retries=3, max_out=2000, effort=None, provider="deepseek"):
        self.provider = provider
        if provider == "minimax":
            model = model if model != MODEL else os.environ.get("AURA_MINIMAX_MODEL", MINIMAX_MODEL)
            base_url = base_url if base_url != BASE_URL else os.environ.get("AURA_MINIMAX_BASE_URL", _minimax_env_value("MINIMAX_BASE_URL", MINIMAX_BASE_URL))
            # M3.1 Flash always reasons first; at 2000 output tokens about half the replies ran out inside <think>
            max_out = max(max_out, int(os.environ.get("AURA_MINIMAX_MAX_OUT", "8000")))
        elif provider == "glm":
            model = model if model != MODEL else os.environ.get("AURA_GLM_MODEL", GLM_MODEL)
            base_url = base_url if base_url != BASE_URL else os.environ.get("AURA_GLM_BASE_URL", GLM_BASE_URL)
            max_out = max(max_out, int(os.environ.get("AURA_GLM_MAX_OUT", "8000")))     # reasons before answering
        self.price = {"minimax": MINIMAX_PRICE, "glm": GLM_PRICE}.get(provider, PRICE)
        self.mode = mode or os.environ.get("AURA_LLM_MODE", "offline")
        self.cache = Path(cache_dir or os.environ.get("AURA_LLM_CACHE", "results/llm-cache"))
        self.model, self.base_url = model, base_url
        self.effort = effort or os.environ.get("AURA_LLM_EFFORT", "low")       # model supports low|high|max
        self.max_calls, self.max_tokens, self.timeout, self.retries, self.max_out = \
            max_calls, max_tokens, timeout, retries, max_out
        self.u = {"calls": 0, "cache_hits": 0, "offline_miss": 0, "budget_skip": 0, "errors": 0, "retries": 0,
                  "prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "truncated": 0, "cost_usd": 0.0,
                  "latency_s": 0.0, "equiv_tokens": 0}   # equiv_tokens: prompt+completion incl. cache replays

    def _key(self, messages):
        return hashlib.sha256(json.dumps([self.model, messages, self.max_out, self.effort], sort_keys=True).encode()).hexdigest()

    def complete(self, messages) -> str | None:
        k = self._key(messages)
        f = self.cache / f"{k}.json"
        if f.exists():
            self.u["cache_hits"] += 1
            rec = json.loads(f.read_text())
            us = rec.get("usage") or {}
            self.u["equiv_tokens"] += us.get("prompt_tokens", 0) + us.get("completion_tokens", 0)
            return rec["content"]
        if self.mode != "live":
            self.u["offline_miss"] += 1
            return None
        used = self.u["prompt_tokens"] + self.u["completion_tokens"]
        if self.u["calls"] >= self.max_calls or used >= self.max_tokens:
            self.u["budget_skip"] += 1
            return None
        req_body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": self.max_out,
                    "response_format": {"type": "json_object"}}
        if self.provider == "deepseek":
            req_body["reasoning_effort"] = self.effort
        body = json.dumps(req_body).encode()
        key_file = _minimax_key_file() if self.provider == "minimax" else \
            os.path.expanduser(os.environ.get("GLM_KEY_FILE", "~/.glm-key")) if self.provider == "glm" else \
            os.environ["DEEPSEEK_KEY_FILE"]
        for i in range(self.retries):
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(self.base_url + "/chat/completions", data=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + Path(key_file).read_text().strip()})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    resp = json.load(r)
                del req                                   # the only object that ever held the header
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                code = getattr(e, "code", None)
                self.u["latency_s"] += time.perf_counter() - t0
                if i + 1 < self.retries and code not in (400, 401, 402, 403, 422):
                    self.u["retries"] += 1
                    time.sleep(2 ** i)
                    continue
                self.u["errors"] += 1
                return None
            self.u["latency_s"] += time.perf_counter() - t0
            self.u["calls"] += 1
            us = resp.get("usage") or {}
            pt, ct = us.get("prompt_tokens", 0), us.get("completion_tokens", 0)
            hit = us.get("prompt_cache_hit_tokens", (us.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
            self.u["prompt_tokens"] += pt
            self.u["cached_tokens"] += hit
            self.u["completion_tokens"] += ct
            self.u["equiv_tokens"] += pt + ct
            self.u["reasoning_tokens"] += (us.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            self.u["truncated"] += resp["choices"][0].get("finish_reason") == "length"
            pr = self.price
            self.u["cost_usd"] += ((pt - hit) * pr[0] + hit * pr[1] + ct * pr[2]) / 1e6
            content = THINK_RE.sub("", resp["choices"][0]["message"].get("content") or "").strip()
            if not content:                           # truncated inside reasoning: count it, never cache it
                return None
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"model": resp.get("model", self.model), "messages": messages,
                                       "content": content, "usage": us}, indent=1))
            tmp.replace(f)
            return content
        return None


SYSTEM = (
    "You improve a coding agent's harness. You are shown one recurring failure from the agent's own (training) "
    "trajectories and the relevant harness settings. Propose 1-3 small edits that would fix it. Reply with ONLY a "
    'JSON object {"mutations": [...]} where each mutation is one of:\n'
    '  {"kind":"route","need":NEED,"tool":TOOL}            pick the tool used for a need\n'
    '  {"kind":"compress","output":KIND,"strategy":STRAT,"limit":INT 100-2000}  how a tool output is shortened\n'
    '  {"kind":"retry","tool":TOOL,"err":ERR,"n":INT 0-5}  retries for a tool error (0 = fail fast)\n'
    '  {"kind":"ttl","fact":FACT,"n":INT 0-1000}            tasks a remembered fact stays valid (0 = never cache)\n'
    '  {"kind":"delegate","task":TASKKIND,"threshold":INT 2-7 or null}  delegate tasks with >= threshold subtasks\n'
    f"NEED->TOOLs: {json.dumps(NEEDS_TOOLS)}\nKIND: {KINDS}\nSTRAT: {STRATS}\nFACT: {FACTS}\nTASKKIND: {TKINDS}\n"
    "Context budget and step limits are fixed and cannot be changed. Prefer the edit most likely to fix the failure "
    "without hurting other tasks; edits are tested on hidden tasks and rolled back if they do not help.")


def build(m, tb, why, sig) -> Candidate | None:
    """validate one typed mutation and build the same Candidate the scripted proposer would; None = malformed"""
    if not isinstance(m, dict):
        return None
    k = m.get("kind")
    try:
        if k == "route":
            need, tool = m["need"], m["tool"]
            if tool not in NEEDS_TOOLS.get(need, []):
                return None
            v = dict(tb["route"], **{need: tool})
            return Candidate("route-tool", v, why, sig, f"route {need}->{tool}")
        if k == "compress":
            kind, s, lim = m["output"], m["strategy"], m["limit"]
            if kind not in KINDS or s not in STRATS or type(lim) is not int or not 100 <= lim <= 2000:
                return None
            v = copy.deepcopy(tb["compress"])
            v[kind] = [s, lim]
            return Candidate("compress", v, why, sig, f"compress {kind} {s}/{lim}")
        if k == "retry":
            tool, err, n = m["tool"], m["err"], m["n"]
            if not any(tool in ts for ts in NEEDS_TOOLS.values()) or not isinstance(err, str) \
                    or not ERR_RE.match(err) or type(n) is not int or not 0 <= n <= 5:
                return None
            v = dict(tb["retry"], **{f"{tool}|{err}": n})
            return Candidate("retry-limit", v, why, sig, f"retry {tool}|{err}={n}")
        if k == "ttl":
            fact, n = m["fact"], m["n"]
            if fact not in FACTS or type(n) is not int or not 0 <= n <= 1000:
                return None
            v = dict(tb["ttl"], **{fact: n})
            return Candidate("memory-ttl", v, why, sig, f"ttl {fact}={n}")
        if k == "delegate":
            kind, thr = m["task"], m.get("threshold")
            if kind not in TKINDS or not (thr is None or (type(thr) is int and 2 <= thr <= 7)):
                return None
            t = delegate_thresholds(tb["delegate"])
            if thr is None:
                t.pop(kind, None)
            else:
                t[kind] = thr
            return Candidate("delegate", delegate_map(t), why, sig,
                             f"delegate {kind}>={thr}" if thr else f"inline {kind}")
    except (KeyError, TypeError):
        return None
    return None


def parse(text):
    """-> list of raw mutation dicts, or None if the response is not the required JSON shape"""
    if not text:
        return None
    try:
        obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return None
    ms = obj.get("mutations") if isinstance(obj, dict) else None
    return ms[:3] if isinstance(ms, list) else None


def _plain(x):
    return json.loads(json.dumps(x, default=str))


class MixedClient:
    """alternates proposer calls between two backends (DeepSeek, MiniMax); usage is the sum, per-backend kept too"""

    def __init__(self, clients):
        self.clients, self.i = list(clients), 0
        self.model = "+".join(c.model for c in self.clients)
        self.mode = self.clients[0].mode

    def complete(self, messages):
        c = self.clients[self.i % len(self.clients)]
        self.i += 1
        return c.complete(messages)

    @property
    def u(self):
        out = {}
        for c in self.clients:
            for k, v in c.u.items():
                out[k] = out.get(k, 0) + v
        return out


PROVIDERS = ("deepseek", "minimax", "glm")


def make_client(provider=None, **kw):
    """AURA_LLM_PROVIDER: deepseek (default) | minimax | glm | mixed (= deepseek,minimax) | a comma list"""
    provider = provider or os.environ.get("AURA_LLM_PROVIDER", "deepseek")
    names = ["deepseek", "minimax"] if provider == "mixed" else provider.split(",")
    bad = [p for p in names if p not in PROVIDERS]
    if bad:
        raise ValueError(f"unknown LLM provider(s) {bad}; choose from {PROVIDERS}")
    if len(names) > 1:
        return MixedClient([LLMClient(provider=p, **kw) for p in names])
    return LLMClient(provider=names[0], **kw)


class LLMProposer(Proposer):
    """Scripted diagnosis/evidence accounting (so both proposers fire on the same evidence), LLM candidate
    generation. mode="llm": LLM candidates only; "hybrid": LLM first, then the scripted ones (deduplicated)."""

    def __init__(self, client: LLMClient | None = None, blend="llm", **kw):
        super().__init__(**kw)
        self.client, self.blend = client or make_client(), blend
        self.history: list[str] = []                 # "<desc>: KEEP|ROLLBACK" - verdicts only
        self.pending: dict[str, list[str]] = {}        # sig -> descs proposed for it, awaiting a verdict
        self._ep = None
        self.n = {"responses": 0, "malformed_responses": 0, "mutations": 0, "malformed_mutations": 0,
                  "noop": 0, "llm_candidates": 0}

    def observe(self, ep, tb):
        self._ep = ep
        return super().observe(ep, tb)

    def feedback(self, sig, verdict, blocked_descs):
        super().feedback(sig, verdict, blocked_descs)
        self.history += [f"{d}: {verdict}" for d in self.pending.pop(sig, [])][-3:]
        self.history = self.history[-12:]

    def _prompt(self, mode, key, info, tb):
        ep = self._ep
        trace = [list(c[:2]) + [c[3]] for c in (ep.calls if ep else [])][-12:]
        cur = {"route": tb["route"], "retry": tb["retry"], "ttl": tb["ttl"],
               "compress": tb["compress"], "delegate_thresholds": delegate_thresholds(tb["delegate"])}
        u = {"failure": {"mode": mode, "key": key, "info": _plain(info)},
             "task": {"kind": ep.task.kind, "project": ep.task.project} if ep else {},
             "recent_tool_calls[need,tool,attempt]": trace, "current_harness": cur,
             "your_earlier_edits_and_verdicts": self.history}
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(u, sort_keys=True)}]

    def candidates(self, mode, key, info, tb, sig):
        why = f"llm: {mode} {key}"
        out = []
        text = self.client.complete(self._prompt(mode, key, info, tb))
        if text is not None:
            self.n["responses"] += 1
            ms = parse(text)
            if ms is None:
                self.n["malformed_responses"] += 1
            else:
                for m in ms:
                    self.n["mutations"] += 1
                    c = build(m, tb, why, sig)
                    if c is None:
                        self.n["malformed_mutations"] += 1
                    elif self._noop(c, tb) or c.desc in {o.desc for o in out}:
                        self.n["noop"] += 1
                    else:
                        c.meta["proposer"] = "llm"
                        c.meta["mutation"] = dict(m)       # the typed mutation, for the swarm's local search
                        out.append(c)
        self.n["llm_candidates"] += len(out)
        if self.blend == "hybrid" or (self.blend == "llm-fallback" and not out):
            seen = {c.desc for c in out}
            out += [c for c in super().candidates(mode, key, info, tb, sig) if c.desc not in seen]
        if out:
            self.pending[sig] = [c.desc for c in out]
        return out

    def llm_usage(self):
        return dict(self.n, **{k: round(v, 6) if isinstance(v, float) else v for k, v in self.client.u.items()},
                    model=self.client.model, mode=self.client.mode)
