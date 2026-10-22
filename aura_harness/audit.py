"""`python3 -m aura_harness audit ...`: the user-facing audit (M4).

  audit run      --ledger L [--seed S] [--world sim|dev] [--n N]   evolve, writing every change to the ledger
  audit list     --ledger L                                        one line per change / block / restart
  audit show ID  --ledger L                                        why + body diff + decision-table diff
  audit rollback ID --ledger L                                     undo change ID (guarded, audited); prints the delta
  audit table    --ledger L                                        rebuild the live harness from the ledger, print it
"""
from __future__ import annotations

import json


def main(a) -> int:
    from .rsi.ledger import Ledger, replay, rollback
    led = Ledger(a.ledger)
    if a.action == "run":
        from .rsi.loop import run_rsi
        kw = dict(window=40, min_heldout=10) if a.world == "dev" else {}
        r = run_rsi(a.seed, n=a.n, world=a.world, ledger=led, **kw)
        print(f"{r['keep']} KEEP / {r['rollback']} ROLLBACK, success {100 * r['success']:.1f}%, "
              f"{len(led.records)} ledger records -> {a.ledger}")
        print(led.listing())
        return 0
    if a.action == "list":
        print(led.listing())
        return 0
    if a.action == "show":
        print(led.show(a.id))
        return 0
    from .rsi.supervisor import SupervisedAura
    h = SupervisedAura()
    try:
        if a.action == "table":
            print(json.dumps(replay(led, h), indent=1, sort_keys=True))
        elif a.action == "rollback":
            rec, _tb = rollback(led, a.id, h)
            print(f"#{rec['id']} ROLLBACK of #{a.id} ({led.get(a.id)['desc']}) admitted by the guard")
            for k, (x, y) in rec["delta"].items():
                print(f"  {k}: {json.dumps(x)} -> {json.dumps(y)}")
            if rec["why"]["also_undoes"]:
                print(f"  note: later changes to {rec['define']} are undone too: {rec['why']['also_undoes']}")
    finally:
        h.close()
    return 0
