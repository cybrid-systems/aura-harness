"""Run tracing for the harness: spans + events per run, per candidate and per task, with an optional OTLP/JSON export.

Off by default. Every instrumented entry point takes `tracer=None`; with None nothing is recorded and the hot path
only pays an `if tracer` check. A Tracer keeps plain dicts in memory; `write_jsonl` dumps one span per line and
`write_otlp` writes the OTLP/JSON `ExportTraceServiceRequest` shape (resourceSpans/scopeSpans/spans), which an
OpenTelemetry collector accepts with its `otlpjsonfile` receiver or `POST /v1/traces`.

Span names (see docs/observability.md):
  rsi.run > rsi.task (per stream task: solver tokens, wall time, mutations attributed)
          > rsi.candidate_round > rsi.proposal (one per candidate: proposer, model/provider, tokens, latency)
                                > rsi.trial (guard + worldline per candidate: ok / reason, Aura mutation id)
                                > rsi.gate (paired replay scores)
                                > rsi.verdict (KEEP / ROLLBACK + reason, Aura provenance)
  swarm.run / supervisor.run > swarm.task / supervisor.family (per task: worker, latency, evals, rebinds)
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager


def _hex(n: int, width: int) -> str:
    return os.urandom(width // 2).hex() if n is None else f"{n:0{width}x}"


def _attr(k, v) -> dict:
    if isinstance(v, bool):
        val = {"boolValue": v}
    elif isinstance(v, int):
        val = {"intValue": str(v)}
    elif isinstance(v, float):
        val = {"doubleValue": v}
    elif isinstance(v, (list, tuple)):
        val = {"arrayValue": {"values": [_attr("", x)["value"] for x in v]}}
    elif v is None:
        val = {"stringValue": ""}
    else:
        val = {"stringValue": v if isinstance(v, str) else json.dumps(v, default=str)}
    return {"key": k, "value": val}


class Span:
    __slots__ = ("tracer", "name", "span_id", "parent_id", "start_ns", "end_ns", "attrs", "events", "status")

    def __init__(self, tracer, name, parent_id, attrs, start_ns=None):
        self.tracer, self.name, self.parent_id = tracer, name, parent_id
        tracer._n += 1
        self.span_id = f"{tracer._n:016x}"
        self.start_ns = start_ns if start_ns is not None else time.time_ns()
        self.end_ns = None
        self.attrs = dict(attrs)
        self.events: list[dict] = []
        self.status = None              # None = unset, else ("ok"|"error", message)

    def set(self, **kw):
        self.attrs.update(kw)
        return self

    def event(self, name, **attrs):
        self.events.append({"name": name, "t_ns": time.time_ns(), "attrs": attrs})

    def error(self, msg):
        self.status = ("error", str(msg))

    def end(self, end_ns=None):
        if self.end_ns is None:
            self.end_ns = end_ns if end_ns is not None else time.time_ns()
            self.tracer.spans.append(self)
        return self

    @property
    def ms(self) -> float:
        return ((self.end_ns or time.time_ns()) - self.start_ns) / 1e6

    def as_dict(self) -> dict:
        return {"trace_id": self.tracer.trace_id, "span_id": self.span_id, "parent_id": self.parent_id,
                "name": self.name, "start_ns": self.start_ns, "end_ns": self.end_ns, "ms": round(self.ms, 3),
                "attrs": self.attrs, "events": self.events,
                "status": self.status[0] if self.status else "unset"}


class Tracer:
    def __init__(self, service: str = "aura-harness", run_id: str | None = None, **resource):
        self.trace_id = os.urandom(16).hex()
        self.run_id = run_id or self.trace_id[:12]
        self.resource = dict({"service.name": service, "run.id": self.run_id}, **resource)
        self.spans: list[Span] = []
        self._n = 0

    def start(self, name, parent: Span | None = None, start_ns=None, **attrs) -> Span:
        return Span(self, name, parent.span_id if parent else None, attrs, start_ns)

    @contextmanager
    def span(self, name, parent: Span | None = None, **attrs):
        s = self.start(name, parent, **attrs)
        try:
            yield s
        except BaseException as e:
            s.error(repr(e))
            raise
        finally:
            s.end()

    # ---------------------------------------------------------------- queries
    def find(self, name) -> list[Span]:
        return [s for s in self.spans if s.name == name]

    def summary(self) -> dict:
        out: dict = {}
        for s in self.spans:
            d = out.setdefault(s.name, {"n": 0, "ms": 0.0})
            d["n"] += 1
            d["ms"] = round(d["ms"] + s.ms, 3)
        return out

    # ---------------------------------------------------------------- export
    def write_jsonl(self, path):
        with open(path, "w") as fh:
            for s in self.spans:
                fh.write(json.dumps(s.as_dict(), default=str) + "\n")
        return path

    def otlp(self) -> dict:
        spans = []
        for s in self.spans:
            sp = {"traceId": self.trace_id, "spanId": s.span_id, "name": s.name, "kind": 1,
                  "startTimeUnixNano": str(s.start_ns), "endTimeUnixNano": str(s.end_ns),
                  "attributes": [_attr(k, v) for k, v in s.attrs.items()],
                  "events": [{"timeUnixNano": str(e["t_ns"]), "name": e["name"],
                              "attributes": [_attr(k, v) for k, v in e["attrs"].items()]} for e in s.events]}
            if s.parent_id:
                sp["parentSpanId"] = s.parent_id
            if s.status:
                sp["status"] = {"code": 2 if s.status[0] == "error" else 1, "message": s.status[1]}
            spans.append(sp)
        return {"resourceSpans": [{"resource": {"attributes": [_attr(k, v) for k, v in self.resource.items()]},
                                   "scopeSpans": [{"scope": {"name": "aura_harness.obs", "version": "1"},
                                                   "spans": spans}]}]}

    def write_otlp(self, path):
        with open(path, "w") as fh:
            json.dump(self.otlp(), fh)
        return path


def from_env(service: str, **resource) -> Tracer | None:
    """AURA_HARNESS_OBS=1 turns tracing on for CLI runs; AURA_HARNESS_OTLP=<file> also writes the OTLP/JSON file."""
    if os.environ.get("AURA_HARNESS_OBS") or os.environ.get("AURA_HARNESS_OTLP"):
        return Tracer(service, **resource)
    return None


def finish(tracer: Tracer | None, jsonl: str | None = None, otlp: str | None = None):
    if tracer is None:
        return
    otlp = otlp or os.environ.get("AURA_HARNESS_OTLP")
    jsonl = jsonl or os.environ.get("AURA_HARNESS_TRACE_JSONL")
    if otlp:
        tracer.write_otlp(otlp)
    if jsonl:
        tracer.write_jsonl(jsonl)


# -------------------------------------------------------------------- RSI loop instrumentation
def _usage(src) -> dict:
    """token tally of the proposer's LLM client so far ({} for the scripted proposer)"""
    c = getattr(getattr(src, "p", None), "client", None)
    u = getattr(c, "u", None)
    return dict(u) if isinstance(u, dict) else {}


def _delta(a: dict, b: dict) -> dict:
    return {k: round(b[k] - a.get(k, 0), 6) for k in b if isinstance(b[k], (int, float)) and b[k] != a.get(k, 0)}


class RsiTrace:
    """Per-run trace of run_rsi. One rsi.task span per stream task (cost attribution), one rsi.candidate_round per
    gated step with rsi.proposal / rsi.trial / rsi.gate / rsi.verdict children."""

    def __init__(self, tracer: Tracer, label, seed, n, worldlines, world):
        self.t = tracer
        self.root = tracer.start("rsi.run", label=label, seed=seed, n=n, worldlines=worldlines, world=world)
        self.task = None
        self.round = None
        self.u0 = {}
        self.counts = {"tasks": 0, "rounds": 0, "proposals": 0, "trials": 0, "blocked": 0, "keep": 0, "rollback": 0,
                       "pending": 0, "apply": 0}

    # one stream task --------------------------------------------------------------
    def task_start(self, t, src):
        self.task_end()
        self.counts["tasks"] += 1
        self.task = self.t.start("rsi.task", self.root, **{"task.id": t.id, "task.kind": t.kind,
                                                              "task.phase": t.phase, "task.heldout": bool(t.heldout)})
        self.task_u0 = _usage(src)
        self.task_mut = 0

    def task_ep(self, ep_summary, solve_ms):
        if self.task:
            self.task.set(**{"task.success": bool(ep_summary.get("success")), "task.tokens": ep_summary.get("cost", 0),
                             "task.steps": ep_summary.get("steps", 0), "task.solve_ms": round(solve_ms, 3)})

    def task_end(self, src=None):
        if self.task is None:
            return
        self.task.set(**{"cost.mutations": self.task_mut, "cost.wall_ms": round(self.task.ms, 3)})
        if src is not None:
            d = _delta(self.task_u0, _usage(src))
            self.task.set(**{"cost.llm_tokens": int(d.get("prompt_tokens", 0) + d.get("completion_tokens", 0)),
                             "cost.llm_usd": d.get("cost_usd", 0.0)})
        self.task.end()
        self.task = None

    # proposal ---------------------------------------------------------------------
    def propose_start(self, src):
        self.u0 = _usage(src)
        self.p0 = time.time_ns()

    def propose_end(self, src, cands):
        if not cands:
            return
        d = _delta(self.u0, _usage(src))
        c = getattr(getattr(src, "p", None), "client", None)
        self.round_end()
        self.counts["rounds"] += 1
        self.round = self.t.start("rsi.candidate_round", self.task or self.root, start_ns=self.p0,
                                  sig=cands[0].sig, why=cands[0].why, n_candidates=len(cands))
        tok = int(d.get("prompt_tokens", 0) + d.get("completion_tokens", 0))
        for i, x in enumerate(cands):
            self.counts["proposals"] += 1
            s = self.t.start("rsi.proposal", self.round, start_ns=self.p0, **{
                "cand.i": i, "cand.desc": x.desc, "cand.name": x.name, "cand.target": x.meta.get("target", ""),
                "proposer": x.meta.get("proposer", "rule"),
                "llm.model": getattr(c, "model", "") if x.meta.get("proposer") == "llm" else "",
                "llm.provider": getattr(c, "provider", "") if x.meta.get("proposer") == "llm" else "",
                "llm.tokens_round": tok, "llm.calls_round": int(d.get("calls", 0)),
                "llm.usd_round": d.get("cost_usd", 0.0)})
            s.end()
        self.round.set(**{"llm.tokens": tok, "llm.calls": int(d.get("calls", 0)),
                          "propose_ms": round((time.time_ns() - self.p0) / 1e6, 3)})

    def round_veto(self, why):
        """host-side ROLLBACK before the control plane saw the candidates (critic veto): no Aura verdict"""
        if self.round:
            self.counts["rollback"] += 1
            self.t.start("rsi.verdict", self.round, **{"verdict": "ROLLBACK", "verdict.where": "host", "chosen": "",
                                                        "reason": why, "aura.prov": ""}).end()
            self.round.set(verdict="ROLLBACK")
            self.round_end()

    # guard + worldline trial --------------------------------------------------------
    def trials(self, cands, trials, pre, ms):
        if not self.round:
            return
        for r in trials:
            self.counts["trials"] += 1
            ok = bool(r["ok"]) and not pre.get(r["i"])
            if not ok:
                self.counts["blocked"] += 1
            self.t.start("rsi.trial", self.round, **{
                "cand.i": r["i"], "cand.desc": cands[r["i"]].desc, "trial.ok": ok,
                "trial.reason": r.get("reason") or (pre.get(r["i"]) or ""), "trial.aura_ms": r.get("ms", 0),
                "aura.prov": r.get("prov", "")}).end()
        self.round.set(trial_ms=round(ms, 3))

    def gate(self, sc, ms):
        if self.round:
            cs = sc.get("candidates", {})
            self.t.start("rsi.gate", self.round, **{"gate.base": list(sc.get("base", ())),
                                                     "gate.window": list(sc.get("window", ())),
                                                     "gate.scores": json.dumps(cs, default=str),
                                                     "gate.ms": round(ms, 3)}).end()

    def verdict(self, vr, chosen_desc, reason, extra=None, ms=0.0):
        if not self.round:
            return
        v = (extra or {}).pop("as", None) or vr.get("verdict", "ROLLBACK")
        self.counts[{"KEEP": "keep", "PENDING": "pending"}.get(v, "rollback")] += 1
        if v == "KEEP" and self.task is not None:
            self.task_mut += 1
        self.t.start("rsi.verdict", self.round, **dict({
            "verdict": v, "verdict.where": "aura", "chosen": chosen_desc or "", "reason": reason or vr.get("reason", ""),
            "aura.version": vr.get("version", 0), "aura.prov": vr.get("prov", ""),
            "aura.root_mid": vr.get("root_mid", 0), "aura.root_mlog": vr.get("root_mlog", 0),
            "verdict.ms": round(ms, 3)}, **(extra or {}))).end()
        self.round.set(verdict=v)
        if v != "PENDING":
            self.round_end()

    def apply(self, res, c, actor):
        """ungated / stat-gate APPLY on the root"""
        self.counts["apply"] += 1
        if res.get("ok") and self.task is not None:
            self.task_mut += 1
        self.t.start("rsi.apply", self.task or self.root, **{
            "actor": actor, "cand.desc": c.desc, "ok": bool(res.get("ok")), "reason": res.get("reason", ""),
            "aura.prov": res.get("prov", ""), "aura.version": res.get("version", 0)}).end()

    def round_end(self):
        if self.round is not None:
            self.round.end()
            self.round = None

    def close(self, src, audit, prov=None):
        self.round_end()
        self.task_end(src)
        self.root.set(**{f"count.{k}": v for k, v in self.counts.items()})
        u = _usage(src)
        if u:
            self.root.set(**{"llm.prompt_tokens": u.get("prompt_tokens", 0),
                             "llm.completion_tokens": u.get("completion_tokens", 0),
                             "llm.calls": u.get("calls", 0), "llm.usd": u.get("cost_usd", 0.0)})
        if prov is not None:
            self.root.set(**{"aura.root_mlog": len(prov.get("mutation_log") or []),
                             "aura.version": prov.get("version", 0)})
        self.root.end()
        self.audit, self.prov = audit, prov


def validate_rsi(tracer: Tracer, audit: list[dict], prov: dict | None = None) -> dict:
    """Join the host trace with the control plane's audit log (server.aura LOG) and Aura's provenance (PROV).
    Returns {"ok": bool, "checks": {...}, "problems": [...]}: counts match, every admitted trial / KEEP carries an
    Aura provenance id, rollbacks are recorded on both sides."""
    probs = []
    trials = tracer.find("rsi.trial")
    verdicts = [s for s in tracer.find("rsi.verdict") if s.attrs.get("verdict.where") == "aura"]
    applies = tracer.find("rsi.apply")
    ops = {}
    for e in audit:
        ops[e["op"]] = ops.get(e["op"], 0) + 1
    n_trial_ok = sum(1 for s in trials if s.attrs["trial.ok"])
    n_keep = sum(1 for s in verdicts if s.attrs["verdict"] == "KEEP")
    n_rb = sum(1 for s in verdicts if s.attrs["verdict"] in ("ROLLBACK", "PENDING"))   # PENDING = stat selection
    srv_trials = ops.get("trial-ws", 0) + ops.get("trial-snap", 0)
    srv_blocked = ops.get("blocked", 0)
    n_apply_ok = sum(1 for s in applies if s.attrs["ok"])
    checks = {
        "trials": {"trace": len(trials), "audit": srv_trials + srv_blocked - sum(1 for s in applies if not s.attrs["ok"])},
        "keep": {"trace": n_keep, "audit": ops.get("keep", 0)},
        "keep_ungated": {"trace": n_apply_ok, "audit": ops.get("keep-ungated", 0)},
        "rollback": {"trace": n_rb, "audit": ops.get("rollback", 0)},
    }
    for k, v in checks.items():
        v["ok"] = v["trace"] == v["audit"]
        if not v["ok"]:
            probs.append(f"{k}: trace {v['trace']} != audit {v['audit']}")
    # every admitted trial was a real Aura rebind: it has a provenance id with mutation_id > 0
    no_prov = [s.attrs["cand.desc"] for s in trials
               if s.attrs["trial.ok"] and not str(s.attrs.get("aura.prov", "")).split("/m")[-1].strip("0")]
    checks["trial_prov_missing"] = len(no_prov)
    if no_prov:
        probs.append(f"{len(no_prov)} admitted trials without an Aura mutation id: {no_prov[:3]}")
    keep_no_prov = [s.attrs["chosen"] for s in verdicts if s.attrs["verdict"] == "KEEP"
                    and not str(s.attrs.get("aura.prov", "")).split("/m")[-1].strip("0")]
    checks["keep_prov_missing"] = len(keep_no_prov)
    if keep_no_prov:
        probs.append(f"{len(keep_no_prov)} KEEPs without an Aura mutation id")
    # the audit log carries the same provenance id as the trace for each keep
    a_keep = [e.get("prov", "") for e in audit if e["op"] == "keep"]
    t_keep = [s.attrs.get("aura.prov", "") for s in verdicts if s.attrs["verdict"] == "KEEP"]
    checks["keep_prov_join"] = a_keep == t_keep
    if a_keep != t_keep:
        probs.append("KEEP provenance ids differ between trace and audit log")
    if prov and prov.get("restarts"):
        # a control-plane restart loses the server's audit log before it (the host keeps its own restart events)
        checks["restarts"] = prov["restarts"]
        for k in ("trials", "keep", "keep_ungated", "rollback", "keep_prov_join"):
            if isinstance(checks.get(k), dict) and not checks[k]["ok"]:
                checks[k]["ok"] = "n/a (restart)"
        probs = [p for p in probs if not p.split(":")[0] in ("trials", "keep", "keep_ungated", "rollback")
                 and "differ" not in p]
    if prov is not None:
        checks["aura_root_mutation_log"] = len(prov.get("mutation_log") or [])
        checks["aura_version"] = prov.get("version")
        checks["version_matches_keeps"] = prov.get("version") == ops.get("keep", 0) + ops.get("keep-ungated", 0)
        if not checks["version_matches_keeps"] and not prov.get("restarts"):
            probs.append(f"control-plane version {prov.get('version')} != keeps {ops.get('keep', 0) + ops.get('keep-ungated', 0)}")
    return {"ok": not probs, "checks": checks, "problems": probs}


# -------------------------------------------------------------------- swarm / supervisor instrumentation
def swarm_trace(tracer: Tracer, kind: str, res: dict, rows: list[list[str]], t_ns: int) -> dict:
    """Build a <kind>.run span with one <kind>.task span per trace row (aura/swarm.aura trace-row!) and validate the
    rows against the run's own counters. Row times are ms since the run's reset!, anchored at the process start
    (t_ns), so absolute times are approximate (process start-up is folded in) but durations are exact."""
    tasks = []
    for r in rows:
        try:
            i, w, tc, te, ev, rb, o = int(r[0]), int(r[1]), int(r[2]), int(r[3]), int(r[4]), int(r[5]), r[6]
        except (ValueError, IndexError):
            continue
        tasks.append((i, w, tc, te, ev, rb, o))
    wall = res.get("wall-ms", 0) or 0
    pw = res.get("process-wall-ms", 0) or 0
    base = t_ns + int(max(0.0, pw - wall) * 1e6)     # run start ~ process end - run wall
    root = tracer.start(f"{kind}.run", start_ns=base, **{k: v for k, v in res.items()
                                                         if isinstance(v, (int, float, str)) and k != "trace"})
    for i, w, tc, te, ev, rb, o in sorted(tasks, key=lambda x: x[3]):
        s = tracer.start(f"{kind}.task", root, start_ns=base + tc * 1_000_000, **{
            "task.id": i, "worker" if kind == "swarm" else "workers": w, "outcome": o,
            "cost.wall_ms": te - tc, "cost.evals": ev, "cost.mutations": rb})
        s.end(base + te * 1_000_000)
    root.end(base + int(wall * 1e6))
    merged = [t for t in tasks if t[6] == "merged"]
    ids = [t[0] for t in merged]
    v = {"rows": len(tasks), "merged_rows": len(merged), "merged": res.get("merged"), "done": res.get("done"),
         "rolled_back_rows": len(tasks) - len(merged), "rolled_back": res.get("rolled-back", 0),
         "duplicate_merges": len(ids) - len(set(ids)),
         "evals_attributed": sum(t[4] for t in merged), "evals": res.get("evals"),
         "rebinds_attributed": sum(t[5] for t in tasks), "rebinds": res.get("rebinds", 0)}
    probs = []
    if res.get("merged") is not None and len(merged) != res.get("merged"):
        probs.append(f"merged rows {len(merged)} != merged counter {res.get('merged')}")
    if res.get("done") is not None and len(set(ids)) != res.get("done"):
        probs.append(f"distinct merged tasks {len(set(ids))} != done {res.get('done')}")
    if v["duplicate_merges"]:
        probs.append(f"{v['duplicate_merges']} tasks merged twice")
    if (len(tasks) - len(merged)) != (res.get("rolled-back", 0) or 0):
        probs.append(f"rollback rows {len(tasks) - len(merged)} != rolled-back counter {res.get('rolled-back', 0)}")
    warns = []
    if kind == "swarm" and res.get("evals") is not None and v["evals_attributed"] > res["evals"]:
        # per-worker (fiber-private) attribution is larger than the shared "evals" counter: the shared counter lost
        # increments. With parallel fiber bodies (aura >= #4717 P4/P5) a read-modify-write on a shared hash
        # ((hash-set! m k (+ n (hash-ref m k 0)))) is not atomic (aura#4715 / #4730), so this is reported as an Aura
        # concurrency finding, not a trace error: the per-task numbers are the accurate ones.
        v["shared_counter_lost"] = v["evals_attributed"] - res["evals"]
        warns.append(f"shared evals counter lost {v['shared_counter_lost']} increments (per-task attribution is exact)")
    v["ok"], v["problems"], v["warnings"] = not probs, probs, warns
    root.set(**{"validation.ok": v["ok"]})
    lat = sorted(t[3] - t[2] for t in merged)
    if lat:
        v["task_ms_p50"], v["task_ms_p95"] = lat[len(lat) // 2], lat[min(len(lat) - 1, int(0.95 * len(lat)))]
    return v
