import json, os, subprocess, sys, time
from pathlib import Path
H = Path(__file__).parent; RES = H / "fx-final.jsonl"
if RES.exists(): RES.unlink()
for i in range(1, 16):
    for attempt in range(3):
        tag = f"fx-l{i}" + ("" if attempt == 0 else f"r{attempt}")
        env = {**os.environ, "PROVIDER": "deepseek", "MODEL": "deepseek-chat", "TASK": "list", "REPO_DIR": "/Users/bao/Code/LocalMind-imani"}
        out = subprocess.run([sys.executable, str(H / "ds_run.py"), "A", "8771", tag], capture_output=True, text=True, env=env).stdout.strip().splitlines()
        try: r = json.loads(out[-1])
        except Exception: r = {"tag": tag, "failed": "no result"}
        valid = not r.get("failed") and r.get("errors") == 0 and r.get("done_s") is not None
        r["valid"] = valid
        if valid or attempt == 2:
            open(RES, "a").write(json.dumps(r) + "\n"); break
        time.sleep(20)
    time.sleep(5)
open(H / "fx-done.flag", "w").write("done")
