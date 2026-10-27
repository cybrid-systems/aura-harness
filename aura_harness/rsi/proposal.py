"""Proposal sources. A source turns an episode + the live table into candidate proposals. It only ever receives
verdicts back (content-free feedback, 2610.19424): never held-out ids, scores or retention results."""
from __future__ import annotations

from typing import Protocol

from ..harness import Candidate
from ..proposer import get_proposer
from .targets import target_of


class ProposalSource(Protocol):
    def observe(self, ep, tb: dict) -> list[Candidate] | None: ...
    def feedback(self, sig: str, verdict: str, blocked: list[str]) -> None: ...


class RuleSource:
    """the existing rule proposer behind the ProposalSource interface; tags each candidate with its target"""

    def __init__(self, proposer=None, **kw):
        self.p = proposer if proposer is not None else get_proposer(**kw)

    @property
    def n_proposals(self):
        return self.p.n_proposals

    def observe(self, ep, tb):
        cs = self.p.observe(ep, tb)
        for c in cs or []:
            c.meta.setdefault("target", target_of(c).value)
        return cs

    def feedback(self, sig, verdict, blocked):
        if verdict not in ("KEEP", "ROLLBACK"):
            raise ValueError("proposal sources get verdicts only")
        self.p.feedback(sig, verdict, blocked)

    def __getattr__(self, k):          # source attribute for the LLM hook, etc.
        return getattr(self.p, k)


class CandidateQueue:
    """M5b: candidates proposed while another one is pending stat admission. Bounded, one entry per evidence
    signature (later proposals for a queued signature only add new candidate descs), deduplicated by desc against
    the queue and the pending candidates. Entries are re-checked against the live table when they are dequeued (a
    KEEP in between can make them no-ops). Holds proposer output only: no held-out ids or scores ever enter it."""

    def __init__(self, cap: int = 4):
        self.cap = cap
        self.q: list[tuple[str, list]] = []
        self.n = {"queued": 0, "merged": 0, "dropped_full": 0, "dropped_dup": 0, "dropped_noop": 0, "dequeued": 0}

    def __len__(self):
        return len(self.q)

    def push(self, cands, pending_descs=(), pending_sigs=()) -> None:
        if not cands:
            return
        sig = cands[0].sig
        if sig in set(pending_sigs):
            self.n["dropped_dup"] += len(cands)
            return
        taken = set(pending_descs) | {c.desc for _, cs in self.q for c in cs}
        new = []
        for c in cands:
            if c.desc in taken:
                self.n["dropped_dup"] += 1
            else:
                taken.add(c.desc)
                new.append(c)
        if not new:
            return
        for s_, cs in self.q:
            if s_ == sig:
                cs.extend(new)
                self.n["merged"] += len(new)
                return
        if len(self.q) >= self.cap:
            self.n["dropped_full"] += len(new)
            return
        self.q.append((sig, new))
        self.n["queued"] += len(new)

    def pop(self, tb, noop) -> list | None:
        while self.q:
            _, cs = self.q.pop(0)
            live = [c for c in cs if not noop(c, tb)]
            self.n["dropped_noop"] += len(cs) - len(live)
            if live:
                self.n["dequeued"] += 1
                return live
        return None

    def requeue(self, cands) -> None:
        """a pending candidate displaced by a conflicting KEEP goes back to the front (it is re-selected later)"""
        if cands and len(self.q) < self.cap:
            self.q.insert(0, (cands[0].sig, list(cands)))
            self.n["requeued"] = self.n.get("requeued", 0) + 1
