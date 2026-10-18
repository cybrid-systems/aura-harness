import json, collections
on = json.load(open("results/runaway/fuel-on.json")); off = json.load(open("results/runaway/fuel-off.json"))
def agg(rows):
    d = collections.OrderedDict()
    for r in rows:
        d.setdefault(r["case"], []).append(r)
    return d
A, B = agg(on["rows"]), agg(off["rows"])
def cell(rs):
    outs = collections.Counter(r["outcome"] for r in rs)
    o = "/".join(sorted(outs)) if len(outs) > 1 else next(iter(outs))
    ms = max(r["ms"] for r in rs)
    if o == "HANG": return f"hang (>{ms/1000:.0f} s)"
    if o == "KILLED": return f"**killed** (OOM, {ms/1000:.1f} s)"
    if o == "REJECTED":
        reason = rs[0]["reason"]
        short = "fuel" if reason.startswith("fuel") else reason.replace("rejected by parser: ", "").replace("forbidden symbol in body: ", "token: ")
        return f"rejected: {short} ({ms:.0f} ms)" if short != "fuel" else f"fuel exhausted ({ms:.0f} ms)"
    return f"{o.lower()} ({ms:.0f} ms)"
print("| body | expect | before (token guard only) | after (fuel 100000) |\n|---|---|---|---|")
for k in A:
    print(f"| `{k}` | {A[k][0]['expect']} | {cell(B.get(k, []) ) if k in B else '-'} | {cell(A[k])} |")
print(json.dumps({"on": on["summary"], "off": off["summary"]}))
