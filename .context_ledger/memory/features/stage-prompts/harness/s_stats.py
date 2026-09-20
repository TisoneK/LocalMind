import json, random, statistics as st
from math import comb
rows=[json.loads(l) for l in open("s-final.jsonl")]
def fisher(a,na,b,nb):
    k=a+b;n=na+nb;tot=comb(n,na);po=comb(k,a)*comb(n-k,na-a)/tot
    return sum(p for x in range(max(0,na-(n-k)),min(na,k)+1) if (p:=comb(k,x)*comb(n-k,na-x)/tot)<=po+1e-12)
def perm(x,y,n=20000):
    if len(x)<2 or len(y)<2: return None
    obs=abs(st.mean(x)-st.mean(y)); pool=x+y; c=0; r=random.Random(1)
    for _ in range(n):
        r.shuffle(pool)
        if abs(st.mean(pool[:len(x)])-st.mean(pool[len(x):]))>=obs-1e-12: c+=1
    return round(c/n,3)
tot={"A":[0,0],"S":[0,0]}
print("valid", sum(r["valid"] for r in rows), "of", len(rows))
for task in ("list","write","edit","find","sys"):
    G={a:[r for r in rows if r["task"]==task and r["arm"]==a and r["valid"]] for a in "AS"}
    if not G["A"] or not G["S"]: continue
    print(f"\n== {task}")
    for a,name in (("A","BASELINE (full input every call)"),("S","POLICY (later calls: no examples/tool-list/hints)")):
        g=G[a]; c=sum(1 for r in g if r["correct"]); tot[a][0]+=c; tot[a][1]+=len(g)
        ft={}
        for r in g: ft[r.get("first_tool")]=ft.get(r.get("first_tool"),0)+1
        print(f" {name:52} n={len(g)} correct {c}/{len(g)} | input_chars {round(st.mean(r['input_chars_all'] for r in g))} | llm_calls {round(st.mean(r['llm_calls'] for r in g if r.get('llm_calls')),1)} | done_s {round(st.mean(r['done_s'] for r in g),1)} | first tools {ft}")
    cb=sum(r["correct"] for r in G["A"]); cn=sum(r["correct"] for r in G["S"])
    print(f"  Fisher p (correct) = {round(fisher(cb,len(G['A']),cn,len(G['S'])),3)} | input_chars perm p = {perm([r['input_chars_all'] for r in G['A']],[r['input_chars_all'] for r in G['S']])}")
print("\nOVERALL correct:", {a:f"{tot[a][0]}/{tot[a][1]}" for a in tot}, "| Fisher p =", round(fisher(tot['A'][0],tot['A'][1],tot['S'][0],tot['S'][1]),4))
