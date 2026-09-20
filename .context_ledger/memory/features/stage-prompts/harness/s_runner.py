import json, os, subprocess, sys, time
from pathlib import Path
H = Path(__file__).parent; N = int(sys.argv[1]); RES = H / "s-final.jsonl"; FLAG = H / "s-done.flag"
for f in (RES, FLAG):
    if f.exists(): f.unlink()
ARMS = {"A": "/Users/bao/Code/LocalMind-imani", "S": "/Users/bao/Code/LocalMind-imani"}
def one(task, arm, i):
    for attempt in range(3):
        tag = f"pr-{task[0]}{arm}{i}" + ("" if attempt == 0 else f"r{attempt}")
        env = {**os.environ, "PROVIDER": sys.argv[2], "MODEL": sys.argv[3], "TASK": task, "REPO_DIR": ARMS[arm]}
        out = subprocess.run([sys.executable, str(H / "s_run.py"), arm, "8771", tag], capture_output=True, text=True, env=env).stdout.strip().splitlines()
        try: r = json.loads(out[-1])
        except Exception: r = {"tag": tag, "failed": "no result"}
        valid = not r.get("failed") and r.get("errors") == 0 and r.get("done_s") is not None
        r.update(arm=arm, valid=valid, task=task)
        if valid or attempt == 2:
            open(RES, "a").write(json.dumps(r) + "\n"); return
        time.sleep(30)
for i in range(1, N + 1):
    for task in ("list", "write", "edit", "find", "sys"):
        for arm in "AS":
            one(task, arm, i); time.sleep(4)
FLAG.write_text("done")
