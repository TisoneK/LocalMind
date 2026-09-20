import asyncio, json, os, re, runpy, sys, time
import httpx
OUT = os.environ["CAPTURE_FILE"]; VARIANT = os.environ.get("VARIANT", "A")

def txt(m):
    c = m.get("content")
    return " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else (c or "")

COMPACT_HEAD = """You are LocalMind, a general-purpose agent running locally on the user's machine.

How you work on every turn:
1. If you can answer from what you already know (including the machine facts below) or the user is just chatting, answer in plain text.
2. Otherwise your reply IS a tool call: call the tool that fetches the missing evidence.
3. After each result, check it against EVERY part of the request. If a part is still missing, call the tool for it. When every part is answered, write the final answer: short, grounded in the results, a Markdown table for tabular data.

Tool choice: system facts -> sysinfo; find or count files -> system_search or shell; list a folder -> dir_explorer; read a file -> file_task; create or save a file -> file_write; change an existing file -> edit_file; run a command (git included) -> shell; web -> web_search then web_fetch. Load an on-demand tool with describe_tool("<name>") first.
Safety: check current state before writes, edits or deletes; never claim success without tool evidence; never emit tool-call XML as text.

Examples:
- "how much RAM do I have?" -> "16 GB." (from the machine facts, no tool)
- "weather in Nairobi?" -> call web_search, then "24C, partly cloudy."
- "list the folders in ~/Code and the latest commit of ~/Code/app" -> call dir_explorer, call shell for git log, then answer both parts.
- "thanks!" -> "Anytime."

"""

def first_sentence(t, n):
    t = (t or "").strip().replace("\n", " ")
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    s = m.group(1) if m else t
    return s[:n]

def compact_tools(tools):
    out = []
    for t in tools:
        fn = dict(t.get("function", {}))
        fn["description"] = first_sentence(fn.get("description"), 120)
        params = json.loads(json.dumps(fn.get("parameters") or {}))
        for k, v in (params.get("properties") or {}).items():
            if isinstance(v, dict) and v.get("description"):
                v["description"] = first_sentence(v["description"], 60)
        fn["parameters"] = params
        out.append({**t, "function": fn})
    return out

def rewrite(body):
    if VARIANT == "A" or not body.get("tools"):
        return body
    ms = list(body.get("messages") or [])
    if ms and ms[0]["role"] == "system" and "LocalMind Parent-Agent Contract" in txt(ms[0]):
        t = txt(ms[0]); a = t.find("\nSystem: "); b = t.find("\nYou own the user's objective")
        facts = t[a:b] if 0 <= a < b else ""
        ms[0] = {**ms[0], "content": COMPACT_HEAD + facts.strip() + "\n"}
    new = {**body, "messages": ms}
    if VARIANT == "D":
        new["tools"] = compact_tools(body["tools"])
    return new

_orig = httpx.AsyncClient.send
async def _send(self, request, *a, **kw):
    try:
        if request.method == "POST" and "chat/completions" in str(request.url):
            body = json.loads(request.content.decode("utf-8", "replace"))
            new = rewrite(body)
            rec = {"t": time.time(), "variant": VARIANT, "n_tools": len(new.get("tools") or []),
                   "sys_chars": sum(len(txt(m)) for m in new.get("messages", []) if m["role"] == "system"),
                   "tools_chars": len(json.dumps(new.get("tools") or [])), "tools_chars_orig": len(json.dumps(body.get("tools") or [])),
                   "messages": new.get("messages")}
            open(OUT, "a").write(json.dumps(rec) + "\n")
            if new is not body:
                raw = json.dumps(new).encode()
                headers = {k: v for k, v in request.headers.items() if k.lower() != "content-length"}
                request = httpx.Request(request.method, request.url, headers=headers, content=raw)
    except Exception as e:
        open(OUT + ".err", "a").write(repr(e) + "\n")
    return await _orig(self, request, *a, **kw)
httpx.AsyncClient.send = _send
sys.path.insert(0, os.getcwd()); sys.argv = ["server.py"]
runpy.run_path("server.py", run_name="__main__")
