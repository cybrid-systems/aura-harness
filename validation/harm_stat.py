"""同样的 HARM 候选混入，但用 stat admission（M5b，一次性 fresh 任务 + alpha）：看统计门能否挡住窗口过拟合"""
import sys
sys.path.insert(0, "validation")
import rsi_validate as V
import aura_harness.rsi.loop as L
from aura_harness.rsi.m2 import M2Config
import harm_forward  # noqa: F401  (installs the Harmful source; also reruns the M1 check)
out = []
for s in V.SEEDS:
    r = L.run_rsi(s, cfg=M2Config(admission="stat"))
    out.append({"seed": s, "harm_kept": sum(k.startswith("HARM") for k in r["kept"]), "keep": r["keep"], "success": r["success"]})
    print(out[-1], flush=True)
L.RuleSource = harm_forward.RuleSource
clean = [L.run_rsi(s, cfg=M2Config(admission="stat"))["success"] for s in V.SEEDS]
print("clean stat success", clean)
V.save("harm-stat", {"harm": out, "clean_stat_success": clean})
