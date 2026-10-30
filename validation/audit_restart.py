"""审计日志在 supervisor 重启后是否完整：KEEP verdict 数 vs LOG 里的 keep 条目；重启前的 trial/blocked/rollback 条目还剩多少"""
import sys, json
sys.path.insert(0, "validation")
import rsi_validate as V
from aura_harness.rsi.supervisor import SupervisedAura
base = V.run_rsi(2, n=240)
h = SupervisedAura(); h.inject = {5, 15}
r = V.run_rsi(2, n=240, backend=h)
cnt = lambda a, op: sum(1 for x in a if x.get("op") == op)
d = {"restarts": r["restarts"], "same_verdicts": V.key(r) == V.key(base),
     "no_fault": {op: cnt(base["audit"], op) for op in ("keep", "rollback", "trial-ws", "blocked")},
     "with_restarts": {op: cnt(r["audit"], op) for op in ("keep", "rollback", "trial-ws", "blocked", "keep-ungated", "restart")},
     "keep_verdicts": r["keep"]}
print(json.dumps(d)); V.save("audit-restart", d)
