"""httpx tap: records each request (messages summary + params) AND a summary of the streamed response
(finish_reason, usage, content/reasoning/tool_call sizes). Never records headers/keys."""
import json, os, runpy, sys, time
import httpx
OUT = os.environ["CAPTURE_FILE"]
def txt(m):
    c = m.get("content"); return " ".join(p.get("text","") for p in c if isinstance(p,dict)) if isinstance(c,list) else (c or "")
_orig_send = httpx.AsyncClient.send
_orig_lines = httpx.Response.aiter_lines
async def _send(self, request, *a, **kw):
    rec = None
    try:
        if request.method == "POST" and "chat/completions" in str(request.url):
            body = json.loads(request.content.decode("utf-8","replace"))
            ms = body.get("messages") or []
            rec = {"t": time.time(), "params": {k: v for k, v in body.items() if k not in ("messages","tools")},
                   "n_tools": len(body.get("tools") or []), "n_msgs": len(ms),
                   "last_role": ms[-1]["role"] if ms else None, "last": txt(ms[-1])[:120] if ms else "",
                   "content_chars": 0, "reasoning_chars": 0, "tool_calls": 0, "finish": None, "usage": None, "chunks": 0}
    except Exception as e:
        open(OUT + ".err","a").write(repr(e)+"\n")
    resp = await _orig_send(self, request, *a, **kw)
    if rec is not None:
        resp._tap_rec = rec
    return resp
def _flush(rec):
    if rec is not None and not rec.get("_done"):
        rec["_done"] = True; rec["t_end"] = time.time()
        open(OUT, "a").write(json.dumps(rec) + "\n")

_orig_aclose = httpx.Response.aclose
async def _aclose(self):
    _flush(getattr(self, "_tap_rec", None))
    return await _orig_aclose(self)
httpx.Response.aclose = _aclose

async def _lines(self):
    rec = getattr(self, "_tap_rec", None)
    try:
        async for line in _orig_lines(self):
            if rec is not None and line.startswith("data:") and "[DONE]" not in line:
                try:
                    j = json.loads(line[5:]); rec["chunks"] += 1
                    if j.get("usage"): rec["usage"] = j["usage"]
                    for ch in j.get("choices") or []:
                        d = ch.get("delta") or {}
                        rec["content_chars"] += len(d.get("content") or "")
                        rec["reasoning_chars"] += len(d.get("reasoning_content") or d.get("reasoning") or "")
                        if d.get("tool_calls"): rec["tool_calls"] += 1
                        if ch.get("finish_reason"): rec["finish"] = ch["finish_reason"]
                except Exception: pass
            yield line
    finally:
        _flush(rec)
httpx.AsyncClient.send = _send
httpx.Response.aiter_lines = _lines
sys.path.insert(0, os.getcwd()); sys.argv = ["server.py"]
runpy.run_path("server.py", run_name="__main__")
