/** A real captured run (deepseek-chat, 2026-09-21; home path shown as ~) so the explorer is never an empty page. */
import type { EngineEvent } from '@/lib/localmind/stateEngine';

export const SAMPLE_GOAL =
  "Find the README of the LocalMind project under ~/Code (several LocalMind folders exist there) and tell me which frontend framework it says it uses.";

export const SAMPLE_EVENTS = [
 {
  "seq": 1,
  "t_ms": 0,
  "kind": "state",
  "depth": 0,
  "facts": 0,
  "failed": 0,
  "progress": 0.0,
  "node": "n0",
  "parent": null,
  "goal": "Find the README of the LocalMind project under ~/Code (several LocalMind folders exist there) and tell me which frontend framework it says it uses."
 },
 {
  "seq": 2,
  "t_ms": 1286,
  "kind": "candidates",
  "moves": [
   {
    "fp": "0500754814ce",
    "label": "dir_explorer(operation=list, path=~/Code)",
    "tool": "dir_explorer",
    "why": "Reveal which LocalMind folders exist under ~/Code so we can target the right one."
   },
   {
    "fp": "62826a16895f",
    "label": "dir_explorer(operation=tree, path=~/Code)",
    "tool": "dir_explorer",
    "why": "Get a recursive view to locate README files inside any LocalMind folder in one pass."
   },
   {
    "fp": "a4232e297e5f",
    "label": "web_search(query=LocalMind project README frontend framework)",
    "tool": "web_search",
    "why": "Check if LocalMind is a known public project whose README states its frontend framework."
   }
  ],
  "at": "n0"
 },
 {
  "seq": 3,
  "t_ms": 3913,
  "kind": "probe",
  "fp": "0500754814ce",
  "move": "dir_explorer(operation=list, path=~/Code)",
  "ok": true,
  "chars": 681,
  "ms": 122,
  "excerpt": "Contents of ~/Code — 14 entries: 📁 .claude/ · 2026-07-20 22:34 📁 context/ · 2026-09-18 13:19 📁 flashscore-scraper/ · 2026-07-16 20:08 📁 glyph/ · 2026-08-17 20:12 📁 InjectX/ · 2026-08-01 15:19 📁 LocalMind/ · 2026-09-21 03:51 📁 PortalLens/ · 2026-08-02 04:54 📁 proxigrid/ · 2026-09-03 20:24 📁 scorewise-engine/ · ",
  "at": "n0"
 },
 {
  "seq": 4,
  "t_ms": 3913,
  "kind": "probe",
  "fp": "62826a16895f",
  "move": "dir_explorer(operation=tree, path=~/Code)",
  "ok": true,
  "chars": 3000,
  "ms": 10,
  "excerpt": "~/Code/ .claude/ context/ context-workflow-quickstart.md (3.9 KB) flashscore-scraper/ glyph/ InjectX/ LocalMind/ PortalLens/ proxigrid/ ScoreWise-Audit-and-Reversal-Plan.pdf (10.8 KB) scorewise-engine/ scorewise-website/ scrapamoja/ vert/ launch.json (235 B) .context_ledger/ … (depth limit 2 — contents not sho",
  "at": "n0"
 },
 {
  "seq": 5,
  "t_ms": 3913,
  "kind": "probe",
  "fp": "a4232e297e5f",
  "move": "web_search(query=LocalMind project README frontend framework)",
  "ok": true,
  "chars": 2952,
  "ms": 2494,
  "excerpt": "Search results via **DuckDuckGo** (8 results): 1. **GitHub - sametgurtuna/localmind: AI-powered desktop file search...** https://github.com/sametgurtuna/localmind LocalMind indexes your local files and lets you search them with natural language queries. Everything — embeddings, vector storage, retrieval — runs on your ",
  "at": "n0"
 },
 {
  "seq": 6,
  "t_ms": 5358,
  "kind": "evaluation",
  "fp": "0500754814ce",
  "move": "dir_explorer(operation=list, path=~/Code)",
  "progress": 0.1,
  "done": false,
  "reason": "Lists ~/Code and reveals a single LocalMind/ folder, but no README contents or framework info. Only locates the candidate directory.",
  "at": "n0"
 },
 {
  "seq": 7,
  "t_ms": 5358,
  "kind": "evaluation",
  "fp": "62826a16895f",
  "move": "dir_explorer(operation=tree, path=~/Code)",
  "progress": 0.15,
  "done": false,
  "reason": "Tree view shows LocalMind/ exists but its contents are truncated/not expanded, so the README and its framework claim are still unknown.",
  "at": "n0"
 },
 {
  "seq": 8,
  "t_ms": 5358,
  "kind": "evaluation",
  "fp": "a4232e297e5f",
  "move": "web_search(query=LocalMind project README frontend framework)",
  "progress": 0.0,
  "done": false,
  "reason": "Web search returns unrelated LocalMind projects (GitHub, Flutter app, etc.), not the local ~/Code/LocalMind README. No relevant fact about the target project's ",
  "at": "n0"
 },
 {
  "seq": 9,
  "t_ms": 5359,
  "kind": "selected",
  "fp": "62826a16895f",
  "move": "dir_explorer(operation=tree, path=~/Code)",
  "progress": 0.15,
  "at": "n0"
 },
 {
  "seq": 10,
  "t_ms": 5359,
  "kind": "state",
  "depth": 1,
  "facts": 3,
  "failed": 0,
  "progress": 0.15,
  "node": "n1",
  "parent": "n0"
 },
 {
  "seq": 11,
  "t_ms": 6635,
  "kind": "candidates",
  "moves": [
   {
    "fp": "1ac583140a32",
    "label": "dir_explorer(operation=list, path=~/Code/LocalMind)",
    "tool": "dir_explorer",
    "why": "Inspect the top-level LocalMind folder to locate its README and see if other LocalMind folders exist inside."
   },
   {
    "fp": "b5c84d076506",
    "label": "dir_explorer(operation=tree, path=~/Code/LocalMind)",
    "tool": "dir_explorer",
    "why": "Get a recursive view of LocalMind to find README files and distinguish multiple LocalMind subprojects."
   },
   {
    "fp": "7e874235b745",
    "label": "file_task(path=~/Code/LocalMind/README.md)",
    "tool": "file_task",
    "why": "Directly read the most likely README location to extract the frontend framework."
   }
  ],
  "at": "n1"
 },
 {
  "seq": 12,
  "t_ms": 6653,
  "kind": "probe",
  "fp": "1ac583140a32",
  "move": "dir_explorer(operation=list, path=~/Code/LocalMind)",
  "ok": true,
  "chars": 1296,
  "ms": 2,
  "excerpt": "Contents of ~/Code/LocalMind — 27 entries: 📁 .claude/ · 2026-09-18 21:22 📁 .context_ledger/ · 2026-09-19 02:43 📁 .git/ · 2026-09-21 06:06 · skipped — not descended (heavy directory) 📁 .pytest_cache/ · 2026-07-31 14:05 📁 .ruff_cache/ · 2026-07-31 14:05 📁 backend/ · 2026-09-18 03:43 📁 docs/ · 2026-09-10 19:29 📁 ",
  "at": "n1"
 },
 {
  "seq": 13,
  "t_ms": 6653,
  "kind": "probe",
  "fp": "b5c84d076506",
  "move": "dir_explorer(operation=tree, path=~/Code/LocalMind)",
  "ok": true,
  "chars": 3000,
  "ms": 14,
  "excerpt": "~/Code/LocalMind/ .claude/ .context_ledger/ .git/ (skipped) .gitattributes (712 B) .gitignore (1.2 KB) .pre-commit-config.yaml (743 B) .pytest_cache/ .ruff_cache/ AGENTS.md (2.5 KB) backend/ CHANGELOG.md (129.1 KB) CLAUDE.md (1.3 KB) CONTRIBUTING.md (3.7 KB) docs/ electron/ frontend/ LICENSE (1.1 KB) localmind",
  "at": "n1"
 },
 {
  "seq": 14,
  "t_ms": 6654,
  "kind": "probe",
  "fp": "7e874235b745",
  "move": "file_task(path=~/Code/LocalMind/README.md)",
  "ok": true,
  "chars": 3000,
  "ms": 1,
  "excerpt": "File: ~/Code/LocalMind/README.md Size: 11,384 bytes Lines: 242 1 # LocalMind 2 3 **A local AI runtime that gives Ollama models real tools — file reading, code execution, shell access, web search, persistent memory, and browser automation. Everything runs on your machine. No data leaves your device.** 4 5 [![Li",
  "at": "n1"
 },
 {
  "seq": 15,
  "t_ms": 8290,
  "kind": "evaluation",
  "fp": "1ac583140a32",
  "move": "dir_explorer(operation=list, path=~/Code/LocalMind)",
  "progress": 0.3,
  "done": false,
  "reason": "Confirms the LocalMind folder at ~/Code/LocalMind exists and contains a README.md, but does not reveal the frontend framework.",
  "at": "n1"
 },
 {
  "seq": 16,
  "t_ms": 8290,
  "kind": "evaluation",
  "fp": "b5c84d076506",
  "move": "dir_explorer(operation=tree, path=~/Code/LocalMind)",
  "progress": 0.3,
  "done": false,
  "reason": "Tree view confirms README.md and a frontend/ directory exist, but no README contents or framework info.",
  "at": "n1"
 },
 {
  "seq": 17,
  "t_ms": 8290,
  "kind": "evaluation",
  "fp": "7e874235b745",
  "move": "file_task(path=~/Code/LocalMind/README.md)",
  "progress": 1.0,
  "done": true,
  "reason": "The README.md contents are shown: badge on line 7 reads 'React 19' linking to react.dev, and the Frontend section describes npm/vite build. This settles the goa",
  "at": "n1"
 },
 {
  "seq": 18,
  "t_ms": 8291,
  "kind": "selected",
  "fp": "7e874235b745",
  "move": "file_task(path=~/Code/LocalMind/README.md)",
  "progress": 1.0,
  "at": "n1"
 },
 {
  "seq": 19,
  "t_ms": 8291,
  "kind": "state",
  "depth": 2,
  "facts": 6,
  "failed": 0,
  "progress": 1.0,
  "node": "n2",
  "parent": "n1"
 },
 {
  "seq": 20,
  "t_ms": 8291,
  "kind": "done",
  "answer": "React (React 19)",
  "trail": [
   "dir_explorer(operation=tree, path=~/Code)",
   "file_task(path=~/Code/LocalMind/README.md)"
  ],
  "model_calls": 4,
  "at": "n2"
 }
] as EngineEvent[];
