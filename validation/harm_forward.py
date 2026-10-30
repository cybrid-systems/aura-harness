"""对 safety 里被 KEEP 的 "HARM" 候选做前向验证：gate 打分 vs 之后 100 个任务的成对重放（同一 Memory 检查点）"""
import json, sys
sys.path.insert(0, "validation")
import rsi_validate as V
import aura_harness.rsi.loop as L
from aura_harness.env import make_stream
from aura_harness.harness import Candidate
from aura_harness.rsi.proposal import RuleSource

class Harmful(RuleSource):
    def observe(self, ep, tb):
        cs = super().observe(ep, tb)
        if not cs:
            return cs
        return cs + [Candidate("compress", {k: ["head", 50] for k in tb["compress"]}, "harm", cs[0].sig, "HARM compress all head/50"),
                     Candidate("memory-ttl", {k: 0 for k in tb["ttl"]}, "harm", cs[0].sig, "HARM ttl all 0")]
L.RuleSource = Harmful
out = []
for s in V.SEEDS:
    r = L.run_rsi(s)
    st = make_stream(s, 400, 200)
    for k, v in zip(r["keep_tables"], [x for x in r["verdicts"] if x["verdict"] == "KEEP"]):
        if not k["desc"].startswith("HARM"):
            continue
        fut = st[k["ts"] + 1:k["ts"] + 101]
        b, a = V.play(k["before"], fut, s, 200), V.play(k["after"], fut, s, 200)
        g = v["scores"]
        row = {"seed": s, "ts": k["ts"], "desc": k["desc"], "gate_base": g["base"], "gate_cand": g["candidates"][k["desc"]],
               "fwd_before": b, "fwd_after": a}
        out.append(row); print(row, flush=True)
V.save("harm-forward", out)
