import json, subprocess, sys, time
from pathlib import Path
H = Path(__file__).parent; N = int(sys.argv[1]); RES = H / "cmp-final.jsonl"
for f in (RES, H / "cmp-done.flag"):
    if f.exists(): f.unlink()
def one(v, i):
    for attempt in range(3):
        tag = f"{v}{i}" + ("" if attempt == 0 else f"r{attempt}")
        out = subprocess.run([sys.executable, str(H / "cmp_run.py"), v, "8771", tag], capture_output=True, text=True).stdout.strip().splitlines()
        try: r = json.loads(out[-1])
        except Exception: r = {"variant": v, "tag": tag, "failed": "no result"}
        valid = not r.get("failed") and r.get("errors") == 0 and r.get("done_s") is not None
        r["attempt"] = attempt; r["valid"] = valid
        if valid or attempt == 2:
            open(RES, "a").write(json.dumps(r) + "\n"); return
        time.sleep(60)
for i in range(1, N + 1):
    for v in "ACD":
        one(v, i); time.sleep(25)
open(H / "cmp-done.flag", "w").write("done")
