"""Crash-restart supervisor for the Aura control plane (aura#4670: SIGSEGV after a few rebinds of fuzzed bodies on
a6c63aa19). Keeps a host ledger of every admitted rebind; on a dead process it respawns server.aura, replays the
ledger, checks the replayed TABLE equals the last known one, and retries the failed call once."""
from __future__ import annotations

import json
import time

from ..control import AuraHarness
from ..harness import Candidate

CRASH = "harness process exited"


def _crashed(e: Exception) -> bool:
    return isinstance(e, (BrokenPipeError, ConnectionResetError)) or CRASH in str(e) or \
        (isinstance(e, ValueError) and "closed file" in str(e))


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


class SupervisedAura:
    kind = "aura"

    def __init__(self, worldlines: str = "ws", server: str | None = None, max_restarts: int = 50):
        self.worldlines, self.server, self.max_restarts = worldlines, server, max_restarts
        self.ledger: list[tuple[str, str, str]] = []     # (name, body, desc) admitted, in order
        self.events: list[dict] = []                      # host audit of restarts
        self.restarts = 0
        self.inject: set[int] = set()                     # tests: kill the process before these call numbers
        self.calls = 0
        self.h = AuraHarness(worldlines, server)
        self._tb = self.h.table()
        self.lat = self.h.lat
        self.startup_s = self.h.startup_s

    # ------------------------------------------------------------ restart machinery
    def _restart(self, why: str, ts=None):
        if self.restarts >= self.max_restarts:
            raise RuntimeError(f"supervisor: too many restarts ({self.restarts})")
        self.restarts += 1
        try:
            self.h.close()
        except Exception:
            pass
        t0 = time.perf_counter()
        lat = self.lat
        for attempt in range(3):                          # the fresh process can die during the replay as well
            self.h = AuraHarness(self.worldlines, self.server)
            for k, v in lat.items():                      # keep latency history across processes
                self.h.lat.setdefault(k, []).extend(v)
            self.lat = self.h.lat
            try:
                for name, body, desc in self.ledger:
                    r = self.h.pipe.call("APPLY", -1, name, body, desc, "supervisor-replay", tag="REPLAY")
                    if not r.get("ok"):
                        raise RuntimeError(f"supervisor: ledger replay rejected {desc}: {r}")
                tb = self.h.table()
                break
            except (RuntimeError, OSError, ValueError) as e:
                if not (_crashed(e) or self._dead()) or attempt == 2:
                    raise
                self.restarts += 1
                self.events.append({"op": "restart", "ts": ts, "why": "crash during ledger replay: " + str(e)[:160],
                                    "replayed": 0, "ms": round(1000 * (time.perf_counter() - t0), 1)})
                try:
                    self.h.close()
                except Exception:
                    pass
        if not _same(tb, self._tb):
            raise RuntimeError("supervisor: replayed table differs from the last known table")
        self.events.append({"op": "restart", "ts": ts, "why": why[:200], "replayed": len(self.ledger),
                            "ms": round(1000 * (time.perf_counter() - t0), 1)})

    def _maybe_inject(self):
        self.calls += 1
        if self.calls in self.inject:
            self.h.pipe.p.kill()
            self.h.pipe.p.wait()

    def _dead(self) -> bool:
        try:
            return self.h.pipe.p.poll() is not None
        except Exception:
            return True

    def _call(self, fn, ts, tries: int = 3):
        self._maybe_inject()
        for attempt in range(tries):
            try:
                return fn()
            except (RuntimeError, OSError, ValueError) as e:
                # a kill mid-reply can surface as a torn JSON line (JSONDecodeError) rather than a broken pipe
                if not (_crashed(e) or self._dead()):
                    raise
                self._restart(("retry: " if attempt else "") + str(e), ts)
        return None                                        # caller decides what repeated crashes mean

    # ------------------------------------------------------------ backend API
    def table(self) -> dict:
        return self._call(lambda: self.h.table(), None)

    def decide(self, comp, a="", b=""):
        return self._call(lambda: self.h.decide(comp, a, b), None)

    def apply(self, ts, c: Candidate, actor="proposer") -> dict:
        r = self._call(lambda: self.h.apply(ts, c, actor), ts)
        if r is None:
            return {"ok": False, "reason": "control plane crashed (aura#4670)"}
        if r.get("ok"):
            self.ledger.append((c.name, c.aura_body(), c.desc))
            self._tb = r["table"]
        return r

    def trial(self, ts, cands: list[Candidate], actor="proposer") -> list[dict]:
        self._cands = cands
        r = self._call(lambda: self.h.trial(ts, cands, actor), ts)
        if r is None:
            self.events.append({"op": "blocked-crash", "ts": ts, "n": len(cands)})
            return [{"i": i, "ok": False, "reason": "control plane crashed (aura#4670)"} for i in range(len(cands))]
        return r

    def verdict(self, ts, chosen: int, scores, why, actor="gate") -> dict:
        def run():
            return self.h.verdict(ts, chosen, scores, why, actor)
        self._maybe_inject()
        try:
            r = run()
        except (RuntimeError, OSError, ValueError) as e:
            if not (_crashed(e) or self._dead()):
                raise
            self._restart(str(e), ts)                     # trial worldlines are gone: re-apply the chosen one
            if chosen < 0:
                return {"verdict": "ROLLBACK", "table": self._tb}
            c = self._cands[chosen]
            r = self.apply(ts, c, actor="gate-replay")
            return {"verdict": "KEEP", "table": r["table"]} if r.get("ok") else {"verdict": "ROLLBACK",
                                                                                "table": self._tb}
        if r.get("verdict") == "KEEP":
            c = self._cands[chosen]
            self.ledger.append((c.name, c.aura_body(), c.desc))
            self._tb = r["table"]
        return r

    def source(self) -> str:
        return self._call(lambda: self.h.source(), None)

    def log(self) -> list[dict]:
        return (self._call(lambda: self.h.log(), None) or []) + self.events

    def prov(self, n: int = 0) -> dict:
        return dict(self._call(lambda: self.h.prov(n), None) or {}, restarts=self.restarts)

    def close(self):
        self.h.close()
