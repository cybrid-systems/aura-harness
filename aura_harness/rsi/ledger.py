"""M4: the persistent, user-facing audit ledger (JSONL). Every admitted change carries WHY (evidence signature,
candidates considered, blocked attempts, gate / retention / fresh scores), a DIFF (old/new body and table delta) and
enough to replay the live harness; `audit rollback <id>` is one command, guarded and audited itself."""
from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path

from ..harness import COMPONENT, Candidate

SEED_SRC = Path(__file__).resolve().parents[2] / "aura" / "harness_seed.aura"


def seed_body(define: str) -> str:
    text = SEED_SRC.read_text()
    m = re.search(r"^\(define " + re.escape(define) + r"\b(.*?)(?=^\(define |\n;; ----|\Z)", text, re.S | re.M)
    body = m.group(1).strip() if m else ""
    return body[:-1].strip() if body.endswith(")") else body


def pretty(body: str) -> str:
    """one cond arm per line, for readable diffs"""
    lines = re.sub(r" \(\(", "\n  ((", body).replace(" (else", "\n  (else").splitlines()
    if len(lines) > 2:                  # arm order is a compiler detail: sort the arms so diffs show real changes
        lines = lines[:1] + sorted(lines[1:-1]) + lines[-1:]
    return "\n".join(lines)


def table_delta(old: dict, new: dict, key: str) -> dict:
    a, b = old.get(key, {}), new.get(key, {})
    if not isinstance(a, dict):
        return {} if a == b else {key: [a, b]}
    return {k: [a.get(k), b.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


class Ledger:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.records: list[dict] = []
        self.torn: str | None = None   # a torn last line from a crash mid-append, dropped on load
        if self.path and self.path.exists():
            lines = [x for x in self.path.read_text().splitlines() if x.strip()]
            for i, x in enumerate(lines):
                try:
                    self.records.append(json.loads(x))
                except json.JSONDecodeError:
                    if i != len(lines) - 1:
                        raise              # corruption in the middle is not a torn write: refuse to guess
                    self.torn = x
        self.next_id = 1 + max((r["id"] for r in self.records), default=0)

    def _write(self, rec):
        rec = dict(rec, id=self.next_id, wall=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        self.next_id += 1
        self.records.append(rec)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
        return rec

    def current_body(self, define: str) -> str:
        for r in reversed(self.records):
            if r["op"] in ("keep", "prune", "rollback") and r["define"] == define:
                return r["new_body"]
        if define in COMPONENT:            # the seed in compiled form, so diffs compare like with like
            from ..harness import seed_table, to_lisp
            return to_lisp(define, seed_table()[COMPONENT[define]])
        return seed_body(define)

    def admit(self, op, ts, c: Candidate, old_tb, new_tb, actor, why: dict) -> dict:
        key = COMPONENT.get(c.name, c.name)
        return self._write({"op": op, "ts": ts, "actor": actor, "define": c.name, "desc": c.desc,
                            "target": c.meta.get("target", "state"), "old_body": self.current_body(c.name),
                            "new_body": c.aura_body(), "delta": table_delta(old_tb, new_tb, key), "why": why})

    def event(self, op, ts, **kw) -> dict:
        return self._write(dict(kw, op=op, ts=ts))

    def changes(self) -> list[dict]:
        return [r for r in self.records if r["op"] in ("keep", "prune", "rollback")]

    def get(self, rid: int) -> dict:
        return next(r for r in self.records if r["id"] == rid)

    # ------------------------------------------------------------ views
    def show(self, rid: int) -> str:
        r = self.get(rid)
        if r["op"] not in ("keep", "prune", "rollback"):
            return json.dumps(r, indent=1)
        w = r["why"]
        out = [f"#{r['id']} {r['op'].upper()} {r['define']}: {r['desc']}   (task {r['ts']}, actor {r['actor']}, "
               f"target {r['target']})", "", "WHY"]
        for k in ("evidence", "reason", "candidates", "blocked", "gate", "retention", "fresh", "rolls_back"):
            if w.get(k) not in (None, [], {}):
                out.append(f"  {k:10s} {json.dumps(w[k]) if not isinstance(w[k], str) else w[k]}")
        out += ["", "DIFF (body)"]
        out += ["  " + x for x in difflib.unified_diff(pretty(r["old_body"]).splitlines(),
                                                        pretty(r["new_body"]).splitlines(), "before", "after",
                                                        lineterm="")]
        out += ["", "DIFF (decision table)"]
        out += [f"  {k}: {json.dumps(a)} -> {json.dumps(b)}" for k, (a, b) in r["delta"].items()] or ["  (none)"]
        out += ["", f"ROLLBACK   python3 -m aura_harness audit rollback {r['id']} --ledger {self.path}"]
        return "\n".join(out)

    def listing(self) -> str:
        rows = ["  id  task  op        plugin        change                                   why"]
        for r in self.records:
            if r["op"] in ("keep", "prune", "rollback"):
                g = r["why"].get("gate") or {}
                d = ""
                if g.get("base") and g.get("chosen"):
                    d = f"held-out {g['base'][0]}->{g['chosen'][0]}/{g['base'][1]}"
                rows.append(f"{r['id']:4d} {r['ts']:5} {r['op']:9s} {r['define']:13s} {r['desc'][:40]:40s} "
                            f"{(r['why'].get('evidence') or r['why'].get('reason') or '')[:28]:28s} {d}")
            elif r["op"] in ("restart", "blocked"):
                rows.append(f"{r['id']:4d} {r['ts']!s:5} {r['op']:9s} {r.get('define', ''):13s} "
                            f"{(r.get('desc') or r.get('why') or '')[:70]}")
        return "\n".join(rows)


def replay(ledger: Ledger, h) -> dict:
    """rebuild the live harness from the ledger (fresh control plane): every keep / prune / rollback, in order"""
    tb = h.table()
    for r in ledger.changes():
        res = h.apply(r["ts"], Candidate(r["define"], None, "replay", "replay", r["desc"], raw_aura=r["new_body"]),
                      actor="ledger-replay")
        if not res.get("ok"):
            raise RuntimeError(f"ledger replay rejected #{r['id']}: {res}")
        tb = res["table"]
    return tb


def rollback(ledger: Ledger, rid: int, h) -> tuple[dict, dict]:
    """undo change #rid: rebind its plugin to the body it replaced (guarded APPLY, actor user-rollback)"""
    r = ledger.get(rid)
    if r["op"] not in ("keep", "prune", "rollback"):
        raise ValueError(f"#{rid} is a {r['op']}, not a change")
    tb0 = replay(ledger, h)
    later = [x["id"] for x in ledger.changes() if x["id"] > rid and x["define"] == r["define"]]
    c = Candidate(r["define"], None, f"rollback #{rid}", f"rollback|{rid}", f"rollback #{rid} ({r['desc']})",
                  raw_aura=r["old_body"])
    res = h.apply(-1, c, actor="user-rollback")
    if not res.get("ok"):
        raise RuntimeError(f"rollback rejected by the guard: {res}")
    rec = ledger.admit("rollback", -1, c, tb0, res["table"], "user-rollback",
                       {"reason": f"user rollback of #{rid}", "rolls_back": rid, "also_undoes": later})
    return rec, res["table"]
