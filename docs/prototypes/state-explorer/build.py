"""Rebuild index.html from template.html + captured runs.

Capture a run:  cd backend && PYTHONPATH=src .venv/bin/python -m core.state_engine --json "<goal>" > run.jsonl
Usage:          python build.py "Title::goal text=run.jsonl" ...   (the goal is read from the run when it has one)
The home directory is replaced with ~ so nothing personal is committed.
"""
import json, os, pathlib, sys

here = pathlib.Path(__file__).parent
home = os.path.expanduser("~")
runs = []
for arg in sys.argv[1:]:
    head, path = arg.rsplit("=", 1)
    title, _, given = head.partition("::")
    events = [json.loads(l.replace(home, "~")) for l in open(path) if l.startswith("{")]
    goal = (next(e for e in events if e["kind"] == "state").get("goal") or given).replace(home, "~")
    runs.append({"title": title, "goal": goal, "events": events})
(here / "index.html").write_text(
    (here / "template.html").read_text().replace("__DATA__", json.dumps(runs, ensure_ascii=False).replace("</", "<\\/"))
)
print("wrote index.html with", len(runs), "runs")
