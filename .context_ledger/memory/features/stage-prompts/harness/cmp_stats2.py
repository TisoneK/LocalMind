import json, os, random, re, statistics as st
from math import comb
rows = [json.loads(l) for l in open("cmp-final.jsonl")]
FOLD = ["alpha", "beta", "gamma", "delta", "epsilon"]
def txt(m):
    c = m.get("content"); return " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else (c or "")
def evidence(tag):
    f = f"cmp-out/calls-{tag}.jsonl"
    if not os.path.exists(f): return None
    act = [json.loads(l) for l in open(f)]; act = [c for c in act if c["n_tools"]]
    if not act: return None
    ms = act[-1]["messages"]
    tool = " ".join(txt(m) for c in act for m in c["messages"] if m["role"] == "tool")  # union over all calls (later calls stub older results)
    ev_f = all(x in tool for x in FOLD)
    ev_c = "handle empty config gracefully" in tool
    wrong = bool(re.search(r"\b(chore\(ledger\)|fix\(agent\)|fix\(chat\)|fix\(adapter\)|feat\(chat\)|refactor\(chat\))", tool))
    ev_n = bool(re.search(r"Found 12 ", tool) or re.search(r"(?m)^\s*12\s*$", tool))
    return dict(ev_folders=ev_f, ev_commit=ev_c, ev_count=ev_n, wrong_repo=wrong, ev_all=ev_f and ev_c and ev_n and not wrong,
                tools_used=len([1 for m in ms if m["role"] == "tool"]))
R = []
for r in rows:
    if r["variant"] not in "ACD" or r.get("failed") or r.get("errors"): continue
    e = evidence(r["tag"]);
    if e is None: continue
    r = {**r, **e, "clean": "rate-limited on my final synthesis" not in (r.get("answer") or "")}
    R.append(r)
V = {v: [r for r in R if r["variant"] == v] for v in "ACD"}
def fisher(a, na, b, nb):
    k = a + b; n = na + nb; tot = comb(n, na); po = comb(k, a) * comb(n - k, na - a) / tot
    return sum(p for x in range(max(0, na - (n - k)), min(na, k) + 1) if (p := comb(k, x) * comb(n - k, na - x) / tot) <= po + 1e-12)
def perm(x, y, n=20000):
    if len(x) < 2 or len(y) < 2: return None
    obs = abs(st.mean(x) - st.mean(y)); pool = x + y; c = 0; rnd = random.Random(1)
    for _ in range(n):
        rnd.shuffle(pool)
        if abs(st.mean(pool[:len(x)]) - st.mean(pool[len(x):])) >= obs - 1e-12: c += 1
    return round(c / n, 3)
print("runs scored:", {v: len(V[v]) for v in V})
for v in "ACD":
    n = len(V[v]); g = lambda k: sum(1 for r in V[v] if r[k])
    clean = [r for r in V[v] if r["clean"]]
    mean = lambda k: round(st.mean([r[k] for r in V[v] if r.get(k) is not None]), 1) if V[v] else None
    print(f"\n{v}  n={n}: EVIDENCE all-correct {g('ev_all')}/{n} (folders {g('ev_folders')}, commit {g('ev_commit')}, count {g('ev_count')}, wrong-repo {g('wrong_repo')}) | clean final {len(clean)}/{n}, correct among clean {sum(r['correct'] for r in clean)}/{len(clean)}")
    print(f"    prompt_tokens mean {mean('prompt_tokens')} | completion {mean('completion_tokens')} | llm_calls {mean('llm_calls')} | act_calls {mean('act_calls')} | done_s {mean('done_s')} | sys_chars {mean('sys_chars')} tools_chars {mean('tools_chars')} | empties {mean('empties')}")
def col(v, k): return [r[k] for r in V[v] if r.get(k) is not None]
for b in "CD":
    if V["A"] and V[b]:
        print(f"\nA vs {b}: evidence-all Fisher p = {round(fisher(sum(r['ev_all'] for r in V['A']), len(V['A']), sum(r['ev_all'] for r in V[b]), len(V[b])), 3)}"
              f" | prompt_tokens perm p = {perm(col('A','prompt_tokens'), col(b,'prompt_tokens'))} | done_s perm p = {perm(col('A','done_s'), col(b,'done_s'))}")
