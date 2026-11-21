"""The harness bus face (aura-harness#4, aura#5128): the RSI loop's trials,
held-out regression evidence and release/reject verdicts go on the target
workspace's Aura bus, next to perf's CCT/hypotheses and the shared audit.

Opt-in: AURA_HARNESS_BUS_WORKSPACE=N (the server attaches as role harness,
caps read|publish). Without it every method is a no-op and a run is
byte-identical to the bus-off path. The harness never opens trials and
never KEEPs: KEEP stays with the proposer under the coordinator's
constraint gate — there is no local path around it.

Read semantics (PROV parity): a failed read is {"status": "error", code,
message}; "no metrics" is {"status": "none"}. They are never merged.
"""
from __future__ import annotations

import os


def workspace_from_env() -> int:
    v = os.environ.get("AURA_HARNESS_BUS_WORKSPACE", "")
    try:
        n = int(v)
    except ValueError:
        return 0
    return n if n > 0 else 0


class BusFace:
    """Thin, crash-tolerant wrapper over the backend's bus_* calls.

    wl_of maps the loop's trial index to the bus worldline id: the target
    workspace's trials are opened by the proposer (perf), the harness
    subscribes to them. With no mapping the verdict is published under
    key 910000 + ts (the round's task id) so the evidence is still on the
    bus, keyed by the round instead of a worldline.
    """

    def __init__(self, backend, workspace: int | None = None):
        self.h = backend
        self.ws = workspace if workspace is not None else workspace_from_env()
        self.enabled = self.ws > 0 and hasattr(backend, "bus_attach")
        self.attached = False
        self.lines: list[str] = []
        self.verdicts = 0
        self.read_errors = 0
        self.wl_of: dict[int, int] = {}
        self._cursor = (0, 0)             # metrics (generation, count)
        if self.enabled:
            r = self._call("bus_attach")
            self.attached = bool(r and r.get("ok") and r.get("attached"))
            if not self.attached:
                self.lines.append(f"bus attach-failed ws={self.ws}: {r}")

    def _call(self, name, *args):
        try:
            return getattr(self.h, name)(*args)
        except Exception as e:            # a dead bus must never kill the loop
            self.read_errors += 1
            return {"ok": False, "status": "error", "code": "transport-failed", "message": str(e)}

    def metrics(self) -> dict:
        """Incremental metrics read; status ok/none/error stays distinct.
        The cursor is the channel's total count, not the delta's length."""
        if not self.enabled:
            return {"status": "error", "code": "no-bus", "message": "bus disabled"}
        r = self._call("bus_metrics", *self._cursor)
        if r and r.get("status") in ("ok", "none"):
            self._cursor = (r.get("generation", self._cursor[0]), r.get("count", self._cursor[1]))
        elif r and r.get("status") == "error":
            self.read_errors += 1
        return r or {"status": "error", "code": "transport-failed", "message": "no reply"}

    def worldlines(self) -> dict:
        if not self.enabled:
            return {"status": "error", "code": "no-bus", "message": "bus disabled"}
        return self._call("bus_worldlines") or {"status": "error", "code": "transport-failed"}

    def verdict(self, ts: int, trial_i: int, keep: bool, ok_count: int, n: int) -> dict | None:
        """Publish the gate's release/reject + held-out evidence for a round."""
        if not self.attached:
            return None
        wl = self.wl_of.get(trial_i, ts)
        r = self._call("bus_verdict", wl, keep, ok_count, n)
        if r and r.get("ok"):
            self.verdicts += 1
        return r

    def audit(self, worldline: int = 0) -> dict | None:
        if not self.attached:
            return None
        return self._call("bus_audit", worldline)

    def finish(self) -> dict:
        """Detach; the coordinator reclaims this session's loans and the
        host keeps serving. Committed evidence stays for the next tool."""
        if not self.attached:
            return {"attached": False, "ws": self.ws, "verdicts": self.verdicts,
                    "read_errors": self.read_errors, "lines": self.lines}
        r = self._call("bus_finish") or {}
        self.attached = False
        self.lines.extend(r.get("lines") or [])
        return {"attached": True, "ws": self.ws, "verdicts": self.verdicts,
                "read_errors": self.read_errors, "audit_events": r.get("audit", -1),
                "lines": self.lines}
