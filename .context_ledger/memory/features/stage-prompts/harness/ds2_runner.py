import json, os, subprocess, sys, time
from pathlib import Path
H = Path(__file__).parent; N = int(sys.argv[1]); PROV = sys.argv[2]; MODEL = sys.argv[3]; PAUSE = int(sys.argv[4]) if len(sys.argv) > 4 else 8
RES = H / f"ds2-final-{PROV}.jsonl"; FLAG = H / f"ds2-done-{PROV}.flag"
for f in (RES, FLAG):
    if f.exists(): f.unlink()
def one(task, v, i):
    for attempt in range(3):
        tag = f"{PROV[:2]}-{task[0]}{v}{i}" + ("" if attempt == 0 else f"r{attempt}")
        env = {**os.environ, "PROVIDER": PROV, "MODEL": MODEL, "TASK": task, "REPO_DIR": "/Users/bao/Code/LocalMind-exp"}
        out = subprocess.run([sys.executable, str(H / "ds2_run.py"), v, "8771", tag], capture_output=True, text=True, env=env).stdout.strip().splitlines()
        try: r = json.loads(out[-1])
        except Exception: r = {"variant": v, "tag": tag, "failed": "no result"}
        valid = not r.get("failed") and r.get("errors") == 0 and r.get("done_s") is not None
        r["attempt"] = attempt; r["valid"] = valid; r["task"] = task
        if valid or attempt == 2:
            open(RES, "a").write(json.dumps(r) + "\n"); return
        time.sleep(30)
for i in range(1, N + 1):
    for task in ("list", "write", "edit"):
        for v in "ACD":
            one(task, v, i); time.sleep(PAUSE)
FLAG.write_text("done")
