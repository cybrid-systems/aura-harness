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
