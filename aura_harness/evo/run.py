"""The evo run: MOEA/D + prop:grammar + surrogate + evo:record! over the harness policy.

One run = one search seed. Candidate objectives are the five-seed means of the
held-out stream (success up, tokens down, latency down). Hard constraints:
the genome cannot address a protected define, post_check() runs on every
candidate, and a naive protected-boundary proposal is injected each generation
to prove the guard path is live.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..harness import post_check, seed_table
from . import genome as G
from .driver import EvoDriver
from .evaluate import boundary_of, check, evaluate, table_from_kept

SEEDS = (0, 1, 2, 3, 4)


@dataclass
class Cfg:
    search_seed: int = 0
    gens: int = 12
    ask: int = 6
    propose: int = 3
    H: int = 4
    T: int = 5
    n: int = 400
    seeds: tuple = SEEDS
    surrogate: bool = False
    prescreen: bool = True
    staged: bool = True
    gate: float = 0.45
    race_margin: float = 0.05
    race: bool = False
    restarts_at: tuple = ()
    hv_target: float | None = None
    polish_rounds: int = 2
    polish_cap: int = 84
    # Cheap-first polish: when surrogate screening is on, every coordinate
    # probe is scored on one cheap stream (1 seed x 200 tasks) and only the
    # best `polish_full` *distinct genes* pay the full 5-stream evaluation.
    # 0 keeps the old behaviour (full-evaluate every probe).
    polish_full: int = 16
    max_gens: int = 36
    log: str = ""
    tag: str = "run"


def _argmax_elite(evals: list[dict]) -> int:
    best, bi = None, -1
    for i, e in enumerate(evals):
        s, t, l = e["objectives"]
        k = (s, -t, -l)
        if best is None or k > best:
            best, bi = k, i
    return bi


def true_front(history: list[dict]) -> list[dict]:
    """Non-dominated set over every fully evaluated candidate (MOEA/D's own
    archive is capped at the population size for its trim step, so the reported
    front is computed from the evaluations themselves)."""
    pts = [h for h in history]
    front = []
    for p in pts:
        o = p["objectives"]
        dom = False
        for q in pts:
            if q is p:
                continue
            v = q["objectives"]
            if (v[0] >= o[0] and v[1] <= o[1] and v[2] <= o[2]
                    and (v[0] > o[0] or v[1] < o[1] or v[2] < o[2])):
                dom = True
                break
        if not dom:
            front.append({"objectives": [float(x) for x in o], "genome": p["genome"],
                          "id": p.get("id", ""), "origin": p.get("origin", "")})
    # de-duplicate identical objective vectors
    seen, out = set(), []
    for p in front:
        k = tuple(round(x, 6) for x in p["objectives"])
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    out.sort(key=lambda p: (p["objectives"][0], -p["objectives"][1]))
    return out


def load_worldline(path: str) -> tuple[list[dict], str]:
    """Replay a log: (resume rows, tip). The tip is the last KEEP's id."""
    rows, tip = [], ""
    if not os.path.exists(path):
        return rows, tip
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("decision") == "KEEP":
                tip = r.get("id", tip)
            objs = r.get("objectives")
            if not isinstance(objs, list) or len(objs) != 3:
                continue
            ev = r.get("evidence") or {}
            if ev.get("learn", True) is False:
                continue                     # recorded for audit, never told
            g = ev.get("genome")
            if not isinstance(g, list) or len(g) != G.DIM:
                g = G.source_genome(r.get("new", ""))
            if g is None:
                continue
            rows.append({"genome": g, "sub": int(ev.get("sub", 0)),
                         "objectives": [float(x) for x in objs],
                         "gen": int(r.get("gen", 0)), "decision": r.get("decision")})
    return rows, tip


def neighbours(g: list[float], cap: int = 84) -> list[list[float]]:
    """Domain-aware coordinate neighbours (the memetic refinement step).

    One gene moves at a time, to each value its own domain can take: every
    route target, every compression strategy, a ladder of limits / TTLs /
    retry counts, every delegation threshold. No objective-specific lever.
    """
    from ..env import NEEDS_TOOLS
    out = []
    ci = len(G.NEED_ORDER)                         # compress genes start after route
    for j in range(len(G.KINDS)):                  # 1. compression strategy
        for s in range(len(G.STRATS)):
            h = list(g); h[ci + 2 * j] = s / len(G.STRATS); out.append(h)
    for j in range(len(G.KINDS)):                  # 2. compression limit
        for lim in (50, 200, 400, 800, 1600, 2000):
            h = list(g); h[ci + 2 * j + 1] = (lim - G.LIMIT_LO) / (G.LIMIT_HI - G.LIMIT_LO)
            out.append(h)
    ti = ci + 2 * len(G.KINDS)
    for j in range(len(G.TTL_FACTS)):              # 3. ttl windows
        for n in (0, 20, 40, 80, 160, 300):
            h = list(g); h[ti + j] = n / G.TTL_HI; out.append(h)
    di = ti + len(G.TTL_FACTS)
    for j in range(len(G.DELEG_KINDS)):            # 4. delegation threshold
        for n in range(8):
            h = list(g); h[di + j] = n / (G.DELEG_HI + 1); out.append(h)
    ri = di + len(G.DELEG_KINDS)
    for j in range(len(G.RETRY_PAIRS)):            # 5. retry count
        for n in range(6):
            h = list(g); h[ri + j] = n / 6.0; out.append(h)
    for j, need in enumerate(G.NEED_ORDER):        # 6. route target
        for k in range(len(NEEDS_TOOLS[need])):
            h = list(g); h[j] = k / len(NEEDS_TOOLS[need]); out.append(h)
    uniq, seen = [], set()
    for h in out:
        k = tuple(int(round(G.clamp(x) * 10000)) for x in h)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    return uniq[:cap]


def run_worker(job) -> dict:
    """Process-pool entry point (module-level so it pickles under -m)."""
    cfg, baseline, out_dir = job
    return run(cfg, baseline, out_dir)


def run(cfg: Cfg, baseline: dict, out_dir: str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = cfg.log or str(out / "evo-log.jsonl")
    if os.path.exists(log):
        os.remove(log)
    boundary = boundary_of()
    drv = EvoDriver(log)
    history: list[dict] = []
    tip = ""
    ini = drv.init(seed=cfg.search_seed, dim=G.DIM, H=cfg.H, T=cfg.T,
                   search=f"{cfg.tag}-s{cfg.search_seed}", tip=tip, gen=0, resume=[])
    pop = int(ini.get("weights", cfg.H))

    full_evals = 0
    cheap_evals = 0
    blocked: list[dict] = []
    gen_rows: list[dict] = []
    target_full: int | None = None
    # The incumbent: this seed's gated policy, the policy the handwritten
    # KEEP/DROP loop ended with. The search starts from it and must dominate it.
    inc = next((p for p in baseline.get("per_table", []) if p.get("seed") == cfg.search_seed),
               None)
    if inc and inc.get("kept"):
        elite = G.encode(table_from_kept(inc["kept"]))
        seed_genome = elite
    else:
        elite = G.encode(seed_table())
        seed_genome = None
    X: list[list[float]] = []
    y: list[float] = []
    seen: set = set()
    n_grammar = 0
    t0 = time.perf_counter()

    def met(front: list[dict]) -> dict:
        # The acceptance baseline is the issue's own point: the gated loop's
        # five-seed held-out success / tokens, with the latency of those five
        # gated tables as the latency reference (the README has no latency).
        b = baseline["issue"]
        b2 = baseline["mean"]
        def weak(p, q, strict=True):
            o = p["objectives"]
            ok = o[0] >= q["success"] and o[1] <= q["tokens"] and o[2] <= q["latency"]
            if not strict:
                return ok
            return ok and (o[0] > q["success"] or o[1] < q["tokens"] or o[2] < q["latency"])
        dom = [p for p in front if weak(p, b)]
        cut = [p for p in front
               if p["objectives"][0] >= b["success"]
               and p["objectives"][1] <= 0.90 * b["tokens"]]
        dom2 = [p for p in front if weak(p, b2)]
        return {"dominates_baseline": len(dom) > 0, "token_cut_10": len(cut) > 0,
                "n_dom": len(dom), "n_cut": len(cut),
                "dominates_cross_stream_gated": len(dom2) > 0, "n_dom2": len(dom2)}

    def eval_and_tell(uniq: list[dict], gen: int):
        nonlocal elite, tip, full_evals, cheap_evals
        chosen = list(range(len(uniq)))
        screen_info = None
        # Free-form proposals (MOEA/D offspring, grammar mutations) are
        # ranked by the GP/kNN surrogate below. The structured polish batch
        # gets the cheaper screen: one held-out stream per probe, ranked by
        # distance to the acceptance point (see polish_prefilter).
        structured = bool(uniq) and uniq[0].get("origin") == "polish"
        if cfg.surrogate and cfg.prescreen and not structured and len(X) >= 8 and uniq:
            k = max(1, math.ceil(len(uniq) * 0.4))
            sc = drv.screen(X=X, y=y, cands=[c["genome"] for c in uniq], k=k)
            chosen = [i for i in sc.get("selected", []) if 0 <= i < len(uniq)]
            screen_info = {"k": k, "n": len(uniq), "cold": sc.get("cold", False),
                           "rows": sc.get("rows", [])}
        evals: list[dict] = []
        # Multi-fidelity race (the std/surrogate staged-eval / race idea):
        # every candidate is scored on one cheap stream (1 seed x 200 tasks);
        # only the ones within race_margin of the batch's best cheap score pay
        # the full 5-stream evaluation. The margin keeps a candidate whose
        # single-seed estimate is noisy but whose mean is good.
        quick: dict[int, float] = {}
        # Cheap-first polish (Issue #4943, second cut). The memetic sweep is
        # the expensive phase: 84 coordinate probes per target, four targets
        # per seed. Score every probe on the cheap stream first, keep the best
        # probe *per gene* (a sweep tests one gene at a time, so keeping the
        # top 12 raw scores would spend the budget on five values of one
        # gene), then send only those to the full held-out evaluation. Every
        # dropped probe stays in the log with its cheap score, so the
        # false-kill audit can spot-check them.
        polish_prefilter = None
        if (cfg.surrogate and cfg.prescreen and structured and not quick
                and cfg.polish_full > 0 and full_evals >= cfg.ask
                and len(uniq) > cfg.polish_full):
            cheap_all: dict[int, tuple] = {}
            for i, c in enumerate(uniq):
                tbl = G.decode(c["genome"])
                if check(tbl, boundary):
                    continue
                q = evaluate(tbl, seeds=(cfg.seeds[0],), n=200)
                cheap_evals += 1
                cheap_all[i] = (q["success"], q["tokens"])
            # Rank by distance to the issue's acceptance point, not by raw
            # cheap success: on this bench success saturates while tokens is
            # the binding objective, so a success-only ranking forwards
            # candidates that can never satisfy the token cut.
            isucc = baseline["issue"]["success"]
            itok = 0.90 * baseline["issue"]["tokens"]

            def goal_key(sc):
                succ, tok = sc
                ds = max(0.0, isucc - succ) / 0.05
                dt = max(0.0, tok - itok) / 600.0
                passed = 0.5 if (succ >= isucc and tok <= itok) else 0.0
                return (passed - (ds * ds + dt * dt), succ, -tok)

            by_gene: dict[object, tuple] = {}
            for i, sc in cheap_all.items():
                gk = uniq[i].get("gene", i)
                if gk not in by_gene or goal_key(sc) > by_gene[gk][0]:
                    by_gene[gk] = (goal_key(sc), i)
            ranked = sorted(by_gene.values(), key=lambda e: e[0], reverse=True)
            chosen = [i for _sc, i in ranked[:cfg.polish_full]]
            for i in chosen:
                quick[i] = cheap_all[i][0]
            polish_prefilter = {"n": len(uniq), "cheap": len(cheap_all),
                                "kept": len(chosen)}
            screen_info = {"k": len(chosen), "n": len(uniq), "cold": False,
                           "rows": [], "polish": polish_prefilter}
        if cfg.staged and cfg.race and structured and not quick and len(chosen) > 1 and full_evals >= cfg.ask:
            for i in chosen:
                tbl = G.decode(uniq[i]["genome"])
                if check(tbl, boundary):
                    continue
                q = evaluate(tbl, seeds=(cfg.seeds[0],), n=200)
                cheap_evals += 1
                quick[i] = q["success"]
            if quick:
                best_q = max(quick.values())
                chosen = [i for i in chosen if i not in quick
                          or quick[i] >= max(best_q - cfg.race_margin, cfg.gate)]
        for i in chosen:
            c = uniq[i]
            tbl = G.decode(c["genome"])
            reason = check(tbl, boundary)
            if reason:
                blocked.append({"gen": gen, "proposal": G.policy_source(c["genome"]),
                                "blocked": reason, "source": "post-check"})
                continue
            if cfg.staged and i not in quick and full_evals >= cfg.ask:
                q = evaluate(tbl, seeds=(cfg.seeds[0],), n=200)
                cheap_evals += 1
                if q["success"] < cfg.gate:
                    continue
            m = evaluate(tbl, seeds=cfg.seeds, n=cfg.n)
            full_evals += 1
            evals.append({"genome": c["genome"], "sub": int(c.get("sub", 0)) % pop,
                          "objectives": [m["success"], m["tokens"], m["latency"]],
                          "viol": 0.0, "reason": f"{c['origin']} {c['thought']}".strip(),
                          "source": G.policy_source(c["genome"]), "dur": 0.0,
                          "surrogate": screen_info is not None,
                          "origin": c["origin"], "per_seed": m["per_seed"]})
            X.append(c["genome"])
            y.append(m["success"])
            seen.add(G.key(c["genome"]))
            history.append(evals[-1])
        elite_i = _argmax_elite(evals)
        # Record every evaluation, but feed the search only the best few of a
        # large batch (local-search sweeps): telling 150 neighbours one by one
        # costs more than evaluating them.
        order = sorted(range(len(evals)),
                       key=lambda i: (evals[i]["objectives"][0], -evals[i]["objectives"][1]),
                       reverse=True)
        learn = set(order[:24])
        tel = drv.tell(evals=[{k: e[k] for k in ("genome", "sub", "objectives", "viol",
                                                 "reason", "source", "dur", "surrogate")}
                              | {"learn": i in learn}
                              for i, e in enumerate(evals)], elite=elite_i, gen=gen)
        if 0 <= elite_i < len(evals):
            elite = evals[elite_i]["genome"]
            tip = tel.get("tip", tip)
        return evals, screen_info

    gens = cfg.max_gens if cfg.surrogate else cfg.gens
    for gen in range(gens):
        if gen in cfg.restarts_at:
            rows, tip = load_worldline(log)
            drv.restart()
            drv.init(seed=cfg.search_seed, dim=G.DIM, H=cfg.H, T=cfg.T,
                     search=f"{cfg.tag}-s{cfg.search_seed}", tip=tip, gen=gen, resume=rows)

        got = drv.ask(k=cfg.ask)
        pool: list[dict] = []
        for c in got.get("cands", []):
            g = [G.clamp(v) for v in c["genome"]]
            pool.append({"genome": g, "sub": c.get("sub", 0), "origin": "moead-de",
                         "strategy": "de", "thought": ""})
        pr = drv.propose(k=cfg.propose, parent=elite, gen=gen, seed=cfg.search_seed * 1000 + gen)
        for p in pr.get("props", []):
            if p.get("genome") and not p.get("reject"):
                pool.append({"genome": [G.clamp(v) for v in p["genome"]],
                             "sub": (gen * cfg.ask + len(pool)) % pop,
                             "origin": "prop-grammar", "strategy": p.get("strategy", "grammar"),
                             "thought": p.get("thought", "")})
                n_grammar += 1

        if gen == 0 and seed_genome is not None:
            pool.insert(0, {"genome": seed_genome, "sub": 0, "origin": "seed-policy",
                            "strategy": "incumbent", "thought": "gated baseline policy"})

        uniq, keys = [], set()
        for c in pool:
            k = G.key(c["genome"])
            if k in keys or k in seen:
                continue
            keys.add(k)
            uniq.append(c)

        # hard constraint, live: a naive proposer asks for a bigger context budget
        attack = seed_table()
        attack["budget"] = 2 * attack["budget"]
        why = post_check(attack, boundary)
        blocked.append({"gen": gen, "proposal": "raise context-budget to 8000",
                        "blocked": why, "source": "naive-protected"})
        if why is None:
            raise RuntimeError("scope guard failed to block the protected proposal")
        drv.record(target="context-budget", decision="ROLLBACK", reason=f"blocked: {why}",
                   evidence={"boundary": "context-budget", "generation": gen},
                   source="(define (context-budget) 8000)", objectives=[])

        evals, screen_info = eval_and_tell(uniq, gen)
        chosen_n = len(uniq) if screen_info is None else screen_info["k"]

        front = true_front(history)
        hv = drv.hv([p["objectives"] for p in front], [0.40, 9800.0, 250.0])
        st = met(front)
        if target_full is None and st["dominates_baseline"] and st["token_cut_10"]:
            if cfg.hv_target is None or hv >= cfg.hv_target:
                target_full = full_evals
        gen_rows.append({"gen": gen, "pool": len(pool), "uniq": len(uniq),
                         "chosen": chosen_n, "evals": len(evals),
                         "full_evals": full_evals, "cheap_evals": cheap_evals,
                         "front": len(front), "hv": hv,
                         "dominates_baseline": st["dominates_baseline"],
                         "token_cut_10": st["token_cut_10"],
                         "grammar_props": len(pr.get("props", [])),
                         "screen": None if screen_info is None else
                         {"k": screen_info["k"], "n": screen_info["n"],
                          "cold": screen_info["cold"],
                          "polish": screen_info.get("polish")}})
        print(f"[{cfg.tag}] gen {gen:2d} pool={len(pool):2d} eval={len(evals):2d} "
              f"full={full_evals:3d} front={len(front):2d} hv={hv:.2f} "
              f"dom={st['dominates_baseline']} cut={st['token_cut_10']}", flush=True)
        if cfg.hv_target is not None and target_full is not None:
            break

    # ── memetic refinement: coordinate neighbours of the frontier's best
    # success point, then of its best token point, two rounds each. ────────
    for rnd in range(cfg.polish_rounds):
        front = true_front(history)
        if not front:
            break
        el = max(front, key=lambda p: (p["objectives"][0], -p["objectives"][1]))
        # the point closest to the requirement (0.634 success, 0.9x tokens):
        # a goal-directed knee, not an objective-specific lever
        req = (baseline["issue"]["success"], 0.90 * baseline["issue"]["tokens"])
        ec = min(front, key=lambda p: (((p["objectives"][0] - req[0]) / 0.1) ** 2
                                       + ((p["objectives"][1] - req[1]) / 1000.0) ** 2))
        targets = [el] + ([ec] if ec is not el else [])
        for tgt in targets:
            cand = []
            for h in neighbours(tgt["genome"], cfg.polish_cap):
                diff = next((i for i, (a, b) in enumerate(zip(tgt["genome"], h))
                             if abs(a - b) > 1e-12), -1)
                cand.append({"genome": [G.clamp(x) for x in h], "sub": 0, "origin": "polish",
                             "strategy": "coordinate", "thought": f"round {rnd}",
                             "gene": diff})
            cand = [c for c in cand if G.key(c["genome"]) not in seen]
            if not cand:
                continue
            print(f"[{cfg.tag}] polish r{rnd} target {[round(x, 3) for x in tgt['objectives']]} "
                  f"n={len(cand)}", flush=True)
            evals, _ = eval_and_tell(cand, gens - 1)
            st = met(true_front(history))
            hv_now = drv.hv([p["objectives"] for p in true_front(history)],
                            [0.40, 9800.0, 250.0])
            if (target_full is None and st["dominates_baseline"] and st["token_cut_10"]
                    and (cfg.hv_target is None or hv_now >= cfg.hv_target)):
                target_full = full_evals
            print(f"[{cfg.tag}] polish r{rnd} n={len(evals)} full={full_evals} "
                  f"dom={st['dominates_baseline']} cut={st['token_cut_10']} "
                  f"target={target_full}", flush=True)
            gen_rows.append({"gen": f"polish{rnd}", "pool": len(cand), "uniq": len(cand),
                             "chosen": len(cand), "evals": len(evals),
                             "full_evals": full_evals, "cheap_evals": cheap_evals,
                             "front": len(true_front(history)), "hv": None,
                             "dominates_baseline": st["dominates_baseline"],
                             "token_cut_10": st["token_cut_10"],
                             "grammar_props": 0, "screen": None})

    front = true_front(history)
    hv = drv.hv([p["objectives"] for p in front], [0.40, 9800.0, 250.0])
    final = met(front)
    res = {
        "tag": cfg.tag, "search_seed": cfg.search_seed,
        "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.__dict__.items()},
        "baseline": baseline,
        "front": front, "hv": hv, "criteria": final,
        "full_evals": full_evals, "cheap_evals": cheap_evals,
        "full_evals_to_target": target_full,
        "grammar_proposals": n_grammar,
        "blocked": blocked, "generations": gen_rows,
        "records": drv.stats().get("records"),
        "tip": tip, "restarts": drv.restarts,
        "wall_s": time.perf_counter() - t0,
        "log": log,
        "front_descriptions": [{"objectives": p["objectives"],
                                "genome": p["genome"],
                                "changes": G.describe(p["genome"])} for p in front],
    }
    drv.close()
    with open(out / "run.json", "w") as fh:
        json.dump(res, fh, indent=1)
    return res
