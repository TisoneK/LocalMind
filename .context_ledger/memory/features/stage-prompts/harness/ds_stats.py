import json, random, statistics as st, sys
from math import comb
prov = sys.argv[1] if len(sys.argv) > 1 else "deepseek"
rows = [json.loads(l) for l in open(f"ds-final-{prov}.jsonl")]
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
for task in ("list", "write"):
    V = {v: [r for r in rows if r["task"] == task and r["variant"] == v and r.get("valid")] for v in "ACD"}
    if not any(V.values()): continue
    print(f"\n===== {prov} / task={task} | valid runs {[len(V[v]) for v in 'ACD']} | gave up {sum(1 for r in rows if r['task']==task and not r.get('valid'))}")
    m = lambda v, k: round(st.mean([r[k] for r in V[v] if r.get(k) is not None]), 1) if V[v] and any(r.get(k) is not None for r in V[v]) else None
    for v in "ACD":
        n = len(V[v]); c = sum(1 for r in V[v] if r["correct"]); cf = sum(1 for r in V[v] if r.get("correct_full"))
        extra = ""
        if task == "list": extra = f" (folders {sum(r['ev_folders'] for r in V[v])} commit {sum(r['ev_commit'] for r in V[v])} count {sum(r['ev_count'] for r in V[v])} wrong-repo {sum(r['wrong_repo'] for r in V[v])})"
        print(f" {v}: correct {c}/{n} (full answer {cf}/{n}){extra} | prompt_tok {m(v,'prompt_tokens')} input_chars {m(v,'input_chars_all')} | llm_calls {m(v,'llm_calls')} act_calls {m(v,'act_calls')} | done_s {m(v,'done_s')} | 429s {m(v,'rl429')}")
    for b in "CD":
        if V["A"] and V[b]:
            f = lambda k: [r[k] for r in V[v] if r.get(k) is not None]
            ca = sum(r["correct"] for r in V["A"]); cb = sum(r["correct"] for r in V[b])
            xa = [r["input_chars_all"] for r in V["A"] if r.get("input_chars_all")]; xb = [r["input_chars_all"] for r in V[b] if r.get("input_chars_all")]
            ta = [r["done_s"] for r in V["A"]]; tb = [r["done_s"] for r in V[b]]
            print(f" A vs {b}: correct Fisher p={round(fisher(ca,len(V['A']),cb,len(V[b])),3)} | input_chars mean {round(st.mean(xa)) if xa else None}->{round(st.mean(xb)) if xb else None} perm p={perm(xa,xb)} | done_s {round(st.mean(ta),1)}->{round(st.mean(tb),1)} perm p={perm(ta,tb)}")
