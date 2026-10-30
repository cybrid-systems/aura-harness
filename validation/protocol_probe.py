"""协议级：TRIAL 与 VERDICT 之间 root 被另一个 actor 改过（APPLY / 用户回滚 / 第二个 loop），KEEP 后那次改动还在吗？
ws 模式 KEEP 走 workspace :merge，snap 模式 KEEP 在 root 上重新 rebind。"""
import json, sys
sys.path.insert(0, ".")
from aura_harness.control import AuraHarness
from aura_harness.harness import Candidate, seed_table

st = seed_table()
cx = Candidate("compress", dict(st["compress"], **{"test-log": ["tail", 800]}), "t", "t", "compress test-log tail/800")
ry = Candidate("route-tool", dict(st["route"], search="rg-json"), "u", "u", "route search->rg-json")
out = {}
for wl in ("ws", "snap"):
    h = AuraHarness(wl)
    tr = h.trial(1, [cx])
    ap = h.apply(2, ry, actor="other-actor")
    mid = h.table()
    vr = h.verdict(3, 0, {"probe": 1}, "probe")
    tb = h.table()
    src = h.source()
    log = [(e["op"], e["name"]) for e in h.log()]
    ver = h.pipe.call("VERSION")["version"]
    h.close()
    out[wl] = {"trial_ok": tr[0]["ok"], "apply_ok": ap.get("ok"), "route_after_apply": mid["route"]["search"],
               "verdict": vr["verdict"], "route_after_keep": tb["route"]["search"],
               "compress_after_keep": tb["compress"]["test-log"],
               "version": ver, "log": log,
               "lost_update": mid["route"]["search"] == "rg-json" and tb["route"]["search"] != "rg-json"}
    print(wl, json.dumps(out[wl]))
json.dump(out, open("validation/results/protocol-lost-update.json", "w"), indent=1)
