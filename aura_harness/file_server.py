"""Decision server for the file-edit baseline: imports harness_live.py + limits.py from a directory and answers
TABLE / D over pipes (same framing as server.aura). Restarting this process is the "reload"."""
import importlib.util
import json
import sys

from .harness import ERRS, FACTS, KINDS, NEEDS, NSUBS, TKINDS, TOOLS


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    d = sys.argv[1]
    h = _load(f"{d}/harness_live.py", "harness_live")
    lim = _load(f"{d}/limits.py", "limits")

    def table():
        return {"route": {n: h.route_tool(n) for n in NEEDS}, "compress": {k: h.compress(k) for k in KINDS},
                "retry": {f"{t}|{e}": h.retry_limit(t, e) for t in TOOLS for e in ERRS},
                "ttl": {f: h.memory_ttl(f) for f in FACTS},
                "delegate": {f"{k}|{n}": h.delegate(k, n) for k in TKINDS for n in NSUBS},
                "budget": lim.context_budget(), "max_steps": lim.max_steps(), "allowed": lim.allowed_tools(),
                "sandbox": lim.sandbox_level()}

    def decide(c, a, b):
        return {"route": lambda: h.route_tool(a), "compress": lambda: h.compress(a),
                "retry": lambda: h.retry_limit(a, b), "ttl": lambda: h.memory_ttl(a),
                "delegate": lambda: h.delegate(a, int(b)), "budget": lim.context_budget,
                "maxsteps": lim.max_steps}[c]()

    print("R " + json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        fs = line.rstrip("\n").split("\t")
        if fs[0] == "QUIT":
            break
        if fs[0] == "TABLE":
            out = {"table": table()}
        elif fs[0] == "D":
            out = {"v": decide(*(fs[1:] + ["", "", ""])[:3])}
        else:
            out = {"error": "unknown command " + fs[0]}
        print("R " + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
