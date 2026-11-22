"""The judge's held-out probe (aura#5397).

The judge owns a hidden key set on the real RESP data plane: it writes
the keys, floods the server so the eviction path runs, and reads the keys
back. A key that survived is a hit. The same traffic runs under the
candidate's eviction kernel and under the baseline's, so the difference
between the two is the candidate's own effect.

The hidden prefix carries a per-run token the proposer cannot guess, so a
candidate tuned to the visible traffic gains nothing here.
"""
from __future__ import annotations

import socket
import time


def _command(*args: str) -> bytes:
    """One RESP command as an array."""
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        raw = str(arg).encode()
        out.append(f"${len(raw)}\r\n".encode() + raw + b"\r\n")
    return b"".join(out)


class Probe:
    """A RESP connection to the real data plane."""

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b""

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_reply(self) -> bytes:
        """One reply: the bulk payload, or a marker for an error."""
        while True:
            reply, self._buf = self._parse(self._buf)
            if reply is not None:
                return reply
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("the server closed the connection")
            self._buf += chunk

    @staticmethod
    def _parse(buf: bytes) -> tuple[bytes | None, bytes]:
        """Split one reply off the buffer: (reply, rest)."""
        if not buf:
            return None, buf
        kind = buf[:1]
        if kind in (b"+", b"-", b":"):
            end = buf.find(b"\r\n")
            if end < 0:
                return None, buf
            return buf[:end], buf[end + 2:]
        if kind == b"$":
            end = buf.find(b"\r\n")
            if end < 0:
                return None, buf
            length = int(buf[1:end])
            if length < 0:
                return b"", buf[end + 2:]
            start = end + 2
            if len(buf) < start + length + 2:
                return None, buf
            return buf[start:start + length], buf[start + length + 2:]
        if kind == b"*":
            end = buf.find(b"\r\n")
            if end < 0:
                return None, buf
            count = int(buf[1:end])
            rest = buf[end + 2:]
            items = []
            for _ in range(count):
                item, rest = Probe._parse(rest)
                if item is None:
                    return None, buf
                items.append(item)
            return b" ".join(items), rest
        raise ValueError(f"unexpected RESP reply: {buf[:16]!r}")

    def call(self, *args: str) -> bytes:
        """One command, one reply."""
        self.sock.sendall(_command(*args))
        return self._read_reply()

    def batch(self, commands: list[list[str]]) -> list[bytes]:
        """Many commands in one write, then the replies in order."""
        payload = b"".join(_command(*cmd) for cmd in commands)
        self.sock.sendall(payload)
        return [self._read_reply() for _ in commands]

    def live_policy(self) -> str:
        """The eviction kernel the server runs now."""
        return self.call("EVICT").decode("utf-8", "replace").strip()

    def measure(self, prefix: str, policy: str, hidden: int = 64,
                churn: int = 3000, rounds: int = 16) -> list[int]:
        """The hits per round the hidden key set scores under one policy.

        Each round is an independent fold: the hidden set is written
        fresh, a churn storm runs, and the set is read back — a key
        that survived the storm is a hit. A fold that started from the
        previous fold's wreckage would measure nothing.
        """
        per_round: list[int] = []
        drifted = False

        def batch(cmds: list[list[str]]) -> list[bytes]:
            # The policy is re-asserted before every batch: the host
            # re-applies its own choice every tick, and a fold that
            # ran under the host's policy would measure the host, not
            # the candidate.
            nonlocal drifted
            self.call("EVICT", policy)
            replies = self.batch(cmds)
            # The host may have re-applied its own choice in between:
            # such a fold measured the wrong policy, so it is not
            # evidence and the fold is dropped.
            if self.live_policy() != policy:
                drifted = True
            return replies

        for rnd in range(rounds):
            drifted = False
            batch([["SET", f"{prefix}{i}", "hidden-value"] for i in range(hidden)])
            # The hidden set is used before the storm: a policy that
            # keeps what is actually used (a frequency kernel) protects
            # it, a policy that evicts by age does not. The fold's
            # score is what survives the storm.
            batch([["GET", f"{prefix}{i}"] for i in range(hidden)])
            batch([["SET", f"{prefix}churn-{rnd}-{i}", "churn-value"]
                   for i in range(churn)])
            replies = batch([["GET", f"{prefix}{i}"] for i in range(hidden)])
            if not drifted:
                per_round.append(sum(1 for reply in replies if reply))
            # The fold's churn is removed: the next fold has to see the
            # same keyspace the first one did, or the hidden set stops
            # being a share of it and every policy scores the same.
            batch([["DEL", f"{prefix}churn-{rnd}-{i}"] for i in range(churn)])
        return per_round


def heldout_delta(host: str, port: int, candidate_kernel: str,
                  prefix: str, hidden: int = 512, churn: int = 3000,
                  rounds: int = 16) -> dict:
    """The candidate's held-out effect against the live policy.

    The baseline is the kernel the server runs now: the candidate is
    measured against the policy that is really in force, not a guess.
    """
    probe = Probe(host, port)
    try:
        baseline = probe.live_policy() or "lru"
        cand_rounds = probe.measure(prefix, candidate_kernel, hidden, churn, rounds)
        base_rounds = probe.measure(prefix, baseline, hidden, churn, rounds)
    finally:
        probe.close()
    # The per-fold delta in parts per million of the hidden set:
    # positive when the candidate's kernel kept more of it. The folds are
    # the statistic's independent samples.
    windows: list[int] = []
    for cand, base in zip(cand_rounds, base_rounds):
        windows.append((cand - base) * 1_000_000 // hidden if hidden else 0)
    observed = sum(windows) // len(windows) if windows else 0
    return {"window": observed, "windows": windows, "baseline": baseline,
            "candidate": candidate_kernel, "cand_rounds": cand_rounds,
            "base_rounds": base_rounds}


def metrics(host: str, port: int) -> list[int]:
    """The live metric vector: the choose-fn inputs.

    The judge reads it from the data plane itself, so the candidate is
    evaluated under the workload's real state (not a stale tick).
    """
    probe = Probe(host, port)
    try:
        info = probe.call("INFO").decode("utf-8", "replace")
    finally:
        probe.close()

    def num(key: str) -> int:
        marker = key + ":"
        at = info.find(marker)
        if at < 0:
            return 0
        start = at + len(marker)
        end = info.find("\n", start)
        text = info[start:end if end >= 0 else len(info)]
        try:
            return int(text.strip())
        except ValueError:
            return 0

    gets, sets = num("gets"), num("sets")
    hits, misses = num("hits"), num("misses")
    evicted, expired = num("evicted"), num("expired")
    keys = num("keys")
    keys_ttl = num("keys_with_ttl")
    avg_ttl = num("avg_ttl_ms")
    return [gets, sets, hits, misses, evicted, keys, expired, avg_ttl, keys_ttl]


def hidden_prefix(run_token: str) -> str:
    """The hidden key set's prefix: a per-run token the proposer cannot guess."""
    return f"heldout-{run_token}-"
