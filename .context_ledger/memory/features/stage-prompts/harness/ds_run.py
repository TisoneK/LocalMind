import json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path
MAIN = Path("/Users/bao/Code/LocalMind"); REPO = Path(os.environ.get("REPO_DIR", "/Users/bao/Code/LocalMind-exp"))
sys.path.insert(0, str(MAIN / "scripts"))
from harness_common import provider_key, venv_python, server_popen_kwargs, kill_process_tree
VARIANT, PORT, TAG = sys.argv[1], sys.argv[2], sys.argv[3]
PROVIDER, MODEL, TASK = os.environ.get("PROVIDER","deepseek"), os.environ.get("MODEL","deepseek-chat"), os.environ.get("TASK","list")
SC = Path(__file__).parent / "ds-out"; SC.mkdir(exist_ok=True)
HOME = SC / f"home-{TAG}"; HOME.mkdir(exist_ok=True)
CAP = SC / f"calls-{TAG}.jsonl"
if CAP.exists(): CAP.unlink()
F = "/Users/bao/s024-fixture"
PROMPT = (f"List the folders directly inside {F}/projects, then tell me the latest git commit message "
          f"in {F}/repo and how many .py files are under {F}/repo/pkg/core.")
PROMPT_W = (f"Create the file {F}/report.md listing the names of the folders directly inside {F}/projects, one per line, "
            f"then read it back to confirm and tell me how many lines it has.")
if TASK == "write":
    PROMPT = PROMPT_W
    try: os.remove(f"{F}/report.md")
    except FileNotFoundError: pass
FOLDERS = ["alpha", "beta", "gamma", "delta", "epsilon"]; COMMIT = "handle empty config gracefully"; COUNT = "12"
(HOME / "settings.json").write_text(json.dumps({"adapter": PROVIDER, "model": MODEL, "thinking": "enabled",
    "shell_enabled": True, "api_keys": {PROVIDER: provider_key(PROVIDER)}}))
env = os.environ.copy()
env.update({"LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(HOME), "LOCALMIND_ADAPTER": PROVIDER, "LOCALMIND_SHELL_ENABLED": "true",
            "PYTHONPATH": str(REPO / "backend/src"), "CAPTURE_FILE": str(CAP), "VARIANT": VARIANT})
log = open(SC / f"server-{TAG}.log", "w")
proc = subprocess.Popen([venv_python(MAIN / "backend"), str(Path(__file__).parent / "ds_wrap.py")], cwd=str(REPO / "backend"),
                        env=env, stdout=log, stderr=subprocess.STDOUT, **server_popen_kwargs())
res = {"variant": VARIANT, "tag": TAG}
try:
    for _ in range(80):
        try: urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2); break
        except Exception: time.sleep(0.5)
    else: raise SystemExit("boot failed")
    data = urllib.parse.urlencode({"message": PROMPT, "session_id": f"cmp-{TAG}-{int(time.time())}", "is_first": "false"}).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    t0 = time.monotonic(); rows = []
    with urllib.request.urlopen(req, timeout=480) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("data: "):
                try: rows.append((time.monotonic() - t0, json.loads(line[6:])))
                except Exception: pass
    answer = "".join(e.get("content", "") for t, e in rows if e.get("type") == "token"); a = answer.lower()
    errors = [e for t, e in rows if e.get("type") == "error"]
    done = next((e for t, e in rows if e.get("type") == "done"), {}); u = done.get("provider_usage") or {}
    tok_t = [t for t, e in rows if e.get("type") == "token"]
    dt = [t for t, e in rows if e.get("type") == "done"]
    calls = [json.loads(l) for l in CAP.read_text().splitlines()] if CAP.exists() else []
    act = [c for c in calls if c["n_tools"]]
    log_txt = open(SC / f"server-{TAG}.log", errors="replace").read()
    res.update(errors=len(errors), done_s=round(dt[0], 1) if dt else None, answer_s=round(max(tok_t), 1) if tok_t else None,
               llm_calls=u.get("llm_calls"), prompt_tokens=u.get("total_prompt_tokens"), completion_tokens=u.get("total_completion_tokens"),
               act_calls=len(act), sys_chars=act[0]["sys_chars"] if act else None,
               tools_chars=act[0]["tools_chars"] if act else None, tools_chars_orig=act[0]["tools_chars_orig"] if act else None,
               empties=log_txt.count("empty response after reasoning streamed"), rl429=log_txt.count("429 Too Many"),
               ok_folders=all(f in a for f in FOLDERS), ok_commit=COMMIT in a, ok_count=bool(re.search(rf"(?<![\d.]){COUNT}(?![\d.])", answer)),
               answer_chars=len(answer), answer=answer[:600])
    res["correct"] = res["ok_folders"] and res["ok_commit"] and res["ok_count"] and not errors
    def _t(m):
        c = m.get("content"); return " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else (c or "")
    res["task"] = TASK; res["provider"] = PROVIDER; res["model"] = MODEL
    res["input_chars_all"] = sum(len(json.dumps(c["messages"])) + c["tools_chars"] for c in act)
    res["clean"] = "rate-limited on my final synthesis" not in answer
    if TASK == "write":
        try: _lines = [x.strip() for x in open(f"{F}/report.md").read().splitlines() if x.strip()]
        except Exception: _lines = None
        res["ok_file"] = _lines is not None and sorted(_lines) == sorted(FOLDERS)
        res["ok_answer"] = bool(re.search(r"\b(5|five)\b", a))
        res["correct"] = bool(res["ok_file"] and not errors); res["correct_full"] = bool(res["ok_file"] and res["ok_answer"] and not errors)
    else:
        _tool = " ".join(_t(m) for c in act for m in c["messages"] if m["role"] == "tool")
        _ef = all(x in _tool for x in FOLDERS); _ec = COMMIT in _tool
        _en = bool(re.search(r"Found 12 ", _tool) or re.search(r"(?m)^\s*12\s*$", _tool))
        _wr = bool(re.search(r"\b(chore\(ledger\)|fix\(agent\)|fix\(chat\)|fix\(adapter\)|feat\(chat\)|refactor\(chat\))", _tool))
        res["ev_all"] = bool(_ef and _ec and _en and not _wr); res["ev_folders"], res["ev_commit"], res["ev_count"], res["wrong_repo"] = _ef, _ec, _en, _wr
        res["correct_full"] = res["correct"]; res["correct"] = res["ev_all"] and not errors
except BaseException as e:
    res["failed"] = repr(e)[:200]
finally:
    kill_process_tree(proc)
open(Path(__file__).parent / "ds-raw.jsonl", "a").write(json.dumps(res) + "\n")
print(json.dumps(res))
