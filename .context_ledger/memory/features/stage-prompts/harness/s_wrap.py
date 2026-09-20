import asyncio, json, os, re, runpy, sys, time
import httpx
OUT = os.environ["CAPTURE_FILE"]; VARIANT = os.environ.get("VARIANT", "A")

def txt(m):
    c = m.get("content")
    return " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else (c or "")

def compress_rules(t):
    """Rule-PRESERVING compression of the real system prompt: only stale/duplicate text is removed."""
    t = t.replace("You are the user-facing LocalMind agent. You own the complete objective; child\nagents are internal workers and never answer the user directly.",
                  "You are the user-facing LocalMind agent and own the complete objective.")
    t = re.sub(r"- Delegate only bounded.*?output or child reasoning as the answer\.\n", "", t, flags=re.S)
    t = t.replace("Replan, change strategy, delegate, or ask", "Replan, change strategy, or ask")
    t = t.replace("## Anti-hedging rules (CRITICAL for weak models)", "## Anti-hedging rules")
    core_m = re.search(r"Core tools \(([^)]*)\)", t); od_m = re.search(r"on-demand tool \(([^)]*)\)", t)
    a = t.find("Available tools — pick the RIGHT one"); b = t.find("Selection hints:")
    c = t.find("Core tools (browse"); d = t.find("Safety:")
    if not (core_m and od_m and 0 <= a < b < c < d):
        return t  # unexpected shape: leave untouched rather than guess
    core = core_m.group(1).strip(); ondemand = {x.strip() for x in od_m.group(1).split(",")}
    lines = [l for l in t[a:b].splitlines()[1:] if l.startswith("- ")]
    keep = [l for l in lines if l[2:].split(":")[0].strip() in ondemand]
    block = ("Core tools (full schemas loaded — call them directly): " + core + ".\n"
             "On-demand tools have no schema until loaded — call describe_tool(\"<name>\") FIRST (e.g. describe_tool(\"sql\")):\n"
             + "\n".join(keep) + "\n")
    return t[:a] + block + t[b:c] + t[d:]


def staged_prompt(t, has_tools):
    """Input-selection policy for LATER calls (a tool result exists): keep every rule and the machine facts;
    drop only what serves choosing the FIRST tool — the style examples, the tool-list one-liners and the selection hints.
    Answer-only calls (no tools offered) also drop the on-demand-loading paragraph."""
    a = t.find("Style — terseness"); b = t.find("Available tools — pick the RIGHT")
    c = t.find("Core tools ("); d = t.find("Safety:")
    if not (0 <= a < b < c < d): return t
    out = t[:a] + t[c:] if has_tools else t[:a] + t[d:]
    return out

def first_sentence(t, n):
    t = (t or "").strip().replace("\n", " ")
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return (m.group(1) if m else t)[:n]

def compact_tools(tools):
    out = []
    for t in tools:
        fn = dict(t.get("function", {})); fn["description"] = first_sentence(fn.get("description"), 120)
        params = json.loads(json.dumps(fn.get("parameters") or {}))
        for k, v in (params.get("properties") or {}).items():
            if isinstance(v, dict) and v.get("description"): v["description"] = first_sentence(v["description"], 60)
        fn["parameters"] = params; out.append({**t, "function": fn})
    return out

def rewrite(body):
    if VARIANT == "S":
        ms = list(body.get("messages") or [])
        later = any(m.get("role") == "tool" for m in ms)
        if later and ms and ms[0]["role"] == "system" and "LocalMind Parent-Agent Contract" in txt(ms[0]):
            ms[0] = {**ms[0], "content": staged_prompt(txt(ms[0]), bool(body.get("tools")))}
            return {**body, "messages": ms}
        return body
    if VARIANT == "A" or not body.get("tools"): return body
    ms = list(body.get("messages") or [])
    if ms and ms[0]["role"] == "system" and "LocalMind Parent-Agent Contract" in txt(ms[0]):
        ms[0] = {**ms[0], "content": compress_rules(txt(ms[0]))}
    new = {**body, "messages": ms}
    if VARIANT == "D": new["tools"] = compact_tools(body["tools"])
    return new

_orig = httpx.AsyncClient.send
async def _send(self, request, *a, **kw):
    try:
        if request.method == "POST" and "chat/completions" in str(request.url):
            body = json.loads(request.content.decode("utf-8", "replace")); new = rewrite(body)
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
