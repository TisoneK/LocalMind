/**
 * State Explorer — the interface of the state-driven engine (experimental, ADR-71).
 *
 * The engine is not a chat: it holds a state, fans out candidate moves, really probes the read-only ones,
 * keeps the best and backtracks from dead ends. So this pane is an instrument for reading a search — a game
 * tree of states, moves and outcomes (never hidden reasoning) with a PGN-style move list, an eval bar, an
 * inspector that shows the real observation behind each move, budget meters, a rewindable timeline — plus
 * the controls a search needs: the budget (depth, branches, model calls, backtracks), layers to read a big
 * tree one kind of move at a time, a spine view, run history persisted across reloads, side-by-side
 * comparison, and the evidence out as JSON or Markdown. It replaces the chat pane while State is selected.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { localmindClient, type StateEngineInfo } from '@/lib/localmind/client';
import {
  ALL_LAYERS,
  buildModel,
  layoutModel,
  metersAt,
  progressCurve,
  runToJson,
  runToMarkdown,
  summarize,
  type EngineEvent,
  type Layers,
  type Model,
  type RunMeta,
} from '@/lib/localmind/stateEngine';
import { StateTree } from './StateTree';
import { Inspector } from './Inspector';
import { RunCompare } from './RunCompare';
import { SAMPLE_EVENTS, SAMPLE_GOAL } from './sampleRun';

export interface Run {
  id: string;
  title: string;
  goal: string;
  events: EngineEvent[];
  meta?: RunMeta;
  live: boolean;
  aborted: boolean;
}

export interface Budget {
  max_depth: number;
  max_branches: number;
  max_model_calls: number;
  max_backtracks: number;
}

const DEFAULT_BUDGET: Budget = { max_depth: 6, max_branches: 3, max_model_calls: 16, max_backtracks: 2 };
const BUDGET_LIMITS: Record<keyof Budget, [number, number]> = {
  max_depth: [1, 10],
  max_branches: [1, 5],
  max_model_calls: [2, 40],
  max_backtracks: [0, 5],
};
const BUDGET_LABEL: Record<keyof Budget, string> = {
  max_depth: 'depth',
  max_branches: 'branches',
  max_model_calls: 'model calls',
  max_backtracks: 'backtracks',
};
const SAMPLE: Run = { id: 'sample', title: 'Sample · find a README', goal: SAMPLE_GOAL, events: SAMPLE_EVENTS, live: false, aborted: false };
const STORE = 'localmind:state-runs';
const KEEP_RUNS = 10;

/** The budget the engine will actually be given: whole numbers, inside the bounds the backend published. */
function clampBudget(b: Budget, limits: Record<keyof Budget, [number, number]>): Budget {
  const out = { ...b };
  for (const k of Object.keys(BUDGET_LABEL) as (keyof Budget)[]) {
    const [lo, hi] = limits[k];
    out[k] = Math.max(lo, Math.min(hi, Math.round(Number(b[k]) || lo)));
  }
  return out;
}

/** Runs survive a reload (the sample excepted — it ships with the app). */
function loadRuns(): Run[] {
  try {
    const raw = window.localStorage.getItem(STORE);
    if (!raw) return [SAMPLE];
    const saved = JSON.parse(raw) as Run[];
    return [SAMPLE, ...saved.filter((r) => r && Array.isArray(r.events) && r.events.length > 0)].slice(0, KEEP_RUNS + 1);
  } catch {
    return [SAMPLE];
  }
}

function Meter({ label, value, max }: { label: string; value: string | number; max?: number }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className="text-brand-green-muted">{label}</span>
      <b className="font-medium text-brand-green-soft">{value}</b>
      {max ? (
        <span className="inline-block h-1.5 w-11 overflow-hidden rounded bg-brand-border">
          <span className="block h-full bg-brand-purple" style={{ width: `${Math.min(100, (Number(value) / max) * 100)}%` }} />
        </span>
      ) : null}
    </span>
  );
}

const chip = (on: boolean) =>
  `rounded-full border px-2 py-0.5 transition-colors ${on ? 'border-brand-green text-brand-green' : 'border-brand-border text-brand-green-muted hover:text-brand-green-soft'}`;

export function StateExplorer() {
  const [runs, setRuns] = useState<Run[]>(loadRuns);
  const [activeId, setActiveId] = useState(SAMPLE.id);
  const [pin, setPin] = useState<number | null>(null); // null = follow the latest event
  const [playing, setPlaying] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [hoverFp, setHoverFp] = useState<string | null>(null);
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS);
  const [spineOnly, setSpineOnly] = useState(false);
  const [userScale, setUserScale] = useState<number | null>(null);
  const [stage, setStage] = useState({ w: 800, h: 480 });
  const [goalText, setGoalText] = useState('');
  const [info, setInfo] = useState<StateEngineInfo | null>(null);
  const [offline, setOffline] = useState(false);
  const [budget, setBudget] = useState<Budget>(DEFAULT_BUDGET);
  const [showSearch, setShowSearch] = useState(false);
  const [comparing, setComparing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = runs.find((r) => r.id === activeId) ?? runs[0];
  const total = run.events.length;
  const cursor = Math.max(1, Math.min(pin ?? total, total || 1));
  const model: Model = useMemo(() => buildModel(run.events), [run.events]);
  const layout = useMemo(() => layoutModel(model), [model]);
  const meters = useMemo(() => metersAt(run.events, model, cursor), [run.events, model, cursor]);
  const curve = useMemo(() => progressCurve(run.events, cursor), [run.events, cursor]);
  const limits = info?.budget_limits ?? BUDGET_LIMITS;
  const finished = !!model.end && model.end.seq <= cursor;
  const runTotalMs = run.events.length ? Math.max(1, run.events[run.events.length - 1].t_ms) : 1;

  // What the backend will use (provider/model) and what a run may be told to spend.
  useEffect(() => {
    let live = true;
    localmindClient
      .getStateEngineInfo()
      .then((i) => {
        if (!live) return;
        setInfo(i);
        if (i.budget) setBudget(i.budget);
      })
      .catch(() => live && setOffline(true));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Keep finished runs (the sample is code, not data).
  useEffect(() => {
    try {
      const keep = runs.filter((r) => r.id !== SAMPLE.id && !r.live && r.events.length > 0).slice(-KEEP_RUNS);
      window.localStorage.setItem(STORE, JSON.stringify(keep));
    } catch {
      /* a full or unavailable localStorage must never break a run */
    }
  }, [runs]);

  // Fit the tree to the pane; resizing refits (unless the user zoomed by hand).
  useEffect(() => {
    const el = stageRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setStage({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const fitScale = Math.max(0.25, Math.min(1, (stage.w - 16) / layout.width, (stage.h - 16) / layout.height));
  const scale = userScale ?? fitScale;

  // Follow the newest element while a run is streaming or playing.
  useEffect(() => {
    const el = stageRef.current;
    if (!el || spineOnly) return;
    let latest: HTMLElement | null = null;
    let best = -1;
    el.querySelectorAll<HTMLElement>('[data-seq]').forEach((n) => {
      const s = Number(n.dataset.seq);
      if (s <= cursor && s > best) {
        best = s;
        latest = n;
      }
    });
    (latest as HTMLElement | null)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [cursor, activeId, spineOnly]);

  // Replay: step through the events at roughly the pace they happened.
  useEffect(() => {
    if (!playing) return;
    const a = run.events[cursor - 1];
    const b = run.events[cursor];
    const wait = a && b ? Math.max(110, Math.min(900, (b.t_ms - a.t_ms) * 0.55)) : 200;
    const t = setTimeout(() => {
      if (cursor >= total) setPlaying(false);
      else setPin(cursor + 1);
    }, wait);
    return () => clearTimeout(t);
  }, [playing, cursor, run.events, total]);

  const pause = useCallback(() => setPlaying(false), []);
  const play = () => {
    setPin(cursor >= total ? 1 : cursor);
    setPlaying(true);
  };
  const step = (d: number) => {
    setPlaying(false);
    setPin(Math.max(1, Math.min(total, cursor + d)));
  };
  const jump = (seq: number) => {
    setPlaying(false);
    setPin(seq);
  };
  const select = (id: string) => {
    setPlaying(false);
    setActiveId(id);
    setPin(null);
    setPicked(null);
    setUserScale(null);
    setComparing(false);
  };

  const startLive = async (goal: string, withBudget: Budget = budget) => {
    const id = `live-${Date.now()}`;
    const ctl = new AbortController();
    abortRef.current = ctl;
    const fresh: Run = { id, title: `Live · ${goal.slice(0, 36)}`, goal, events: [], live: true, aborted: false };
    setRuns((rs) => [...rs, fresh]);
    select(id);
    const patch = (fn: (r: Run) => Run) => setRuns((rs) => rs.map((r) => (r.id === id ? fn(r) : r)));
    try {
      await localmindClient.runStateEngine(
        goal,
        {
          onMeta: (meta) => patch((r) => ({ ...r, meta })),
          onEvent: (e) => patch((r) => ({ ...r, events: [...r.events, e] })),
        },
        ctl.signal,
        clampBudget(withBudget, limits)
      );
    } catch (err) {
      if ((err as Error).name === 'AbortError') patch((r) => ({ ...r, aborted: true }));
      else
        patch((r) => ({
          ...r,
          events: [
            ...r.events,
            { seq: r.events.length + 1, t_ms: r.events.at(-1)?.t_ms ?? 0, kind: 'stopped', reason: `error: ${(err as Error).message}`, settled: false, trail: [], model_calls: 0 },
          ],
        }));
    } finally {
      patch((r) => ({ ...r, live: false }));
      if (abortRef.current === ctl) abortRef.current = null;
    }
  };
  const busy = runs.some((r) => r.live);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const g = goalText.trim();
    if (g.length >= 3 && !busy) void startLive(g);
  };

  const flash = (msg: string) => {
    setNotice(msg);
    window.setTimeout(() => setNotice(null), 2600);
  };
  const exportJson = () => {
    try {
      const blob = new Blob([runToJson(run)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `state-run-${run.id}.json`;
      a.click();
      URL.revokeObjectURL(url);
      flash('Saved the run as JSON.');
    } catch {
      flash('Could not save the file here.');
    }
  };
  const copySummary = async () => {
    try {
      await navigator.clipboard.writeText(runToMarkdown(run));
      flash('Run summary copied.');
    } catch {
      flash('Clipboard unavailable.');
    }
  };
  const rerun = () => {
    if (!busy) void startLive(run.goal);
  };
  const dropRun = () => {
    if (run.id === SAMPLE.id || run.live) return;
    setRuns((rs) => rs.filter((r) => r.id !== run.id));
    select(rs_next(activeId) ?? SAMPLE.id);
    setNotice('Run removed.');
  };
  const rs_next = (_id: string) => runs.find((r) => r.id !== run.id && r.id !== SAMPLE.id)?.id;
  const clearRuns = () => {
    setRuns([SAMPLE]);
    setActiveId(SAMPLE.id);
    setPin(null);
  };

  const onKey = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if (e.key === ' ') {
      e.preventDefault();
      if (playing) pause();
      else play();
    } else if (e.key === 'ArrowRight' || e.key === 'l' || e.key === 'j') step(1);
    else if (e.key === 'ArrowLeft' || e.key === 'h' || e.key === 'k') step(-1);
    else if (e.key === 'Home') jump(1);
    else if (e.key === 'End') {
      setPlaying(false);
      setPin(null);
    } else if (e.key === '0') setUserScale(null);
    else if (e.key === '+' || e.key === '=') setUserScale(Math.min(1.6, scale * 1.2));
    else if (e.key === '-') setUserScale(Math.max(0.3, scale / 1.2));
    else if (e.key === 's') setSpineOnly((v) => !v);
    else if (e.key === 'c') setComparing((v) => !v);
    else if (e.key === 'e') exportJson();
  };

  const pill = finished
    ? model.end?.kind === 'done'
      ? { text: 'SETTLED', cls: 'border-brand-green text-brand-green' }
      : { text: 'NOT SETTLED', cls: 'border-brand-red text-brand-red' }
    : run.live
      ? { text: 'LIVE', cls: 'border-brand-blue text-brand-blue' }
      : run.aborted
        ? { text: 'STOPPED', cls: 'border-brand-amber text-brand-amber' }
        : { text: cursor >= total ? 'REPLAY' : 'RUNNING', cls: 'border-brand-amber text-brand-amber' };

  const moves = run.events.filter((e) => ['selected', 'backtrack', 'needs_confirmation', 'done', 'stopped'].includes(e.kind));
  let ply = 0;
  const summary = summarize(run);

  return (
    <section
      data-testid="state-explorer"
      aria-label="State Explorer"
      tabIndex={0}
      onKeyDown={onKey}
      className="flex h-full min-h-0 flex-col bg-brand-bg-base font-mono text-xs text-brand-green-soft outline-none"
    >
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-brand-border bg-brand-bg-panel px-4 py-2.5">
        <div className="font-bold tracking-[0.14em] text-brand-green">STATE EXPLORER</div>
        <select
          aria-label="Run"
          value={activeId}
          onChange={(e) => select(e.target.value)}
          className="max-w-[260px] rounded-md border border-brand-border-strong bg-brand-bg-panel-alt px-2 py-1"
        >
          {runs.map((r, i) => (
            <option key={r.id} value={r.id}>{`${i + 1}. ${r.title}`}</option>
          ))}
        </select>
        <span className={`rounded-full border px-2.5 py-0.5 font-bold tracking-wider ${pill.cls}`} data-testid="run-pill">{pill.text}</span>
        <div className="min-w-0 flex-1 basis-64 truncate text-brand-green-soft" title={run.goal}>
          <span className="mr-1.5 text-brand-green-muted">GOAL</span>{run.goal}
        </div>
        <form onSubmit={submit} className="flex basis-full items-center gap-2" autoComplete="off">
          <input
            aria-label="Goal"
            value={goalText}
            onChange={(e) => setGoalText(e.target.value)}
            disabled={busy || offline}
            maxLength={2000}
            placeholder="Give the engine a goal — it can look and read, never change anything"
            className="min-w-0 flex-1 rounded-md border border-brand-border-strong bg-brand-bg-panel-alt px-2.5 py-1.5 text-brand-green-soft placeholder:text-brand-green-faint disabled:opacity-50"
          />
          {busy ? (
            <button type="button" onClick={() => abortRef.current?.abort()} className="rounded-md border border-brand-red px-3 py-1.5 text-brand-red">■ stop</button>
          ) : (
            <button type="submit" disabled={offline || goalText.trim().length < 3} className="rounded-md border border-brand-green px-3 py-1.5 text-brand-green disabled:opacity-50">▶ run live</button>
          )}
          <button
            type="button"
            aria-expanded={showSearch}
            onClick={() => setShowSearch((v) => !v)}
            className="rounded-md border border-brand-border-strong px-2.5 py-1.5"
            title="How hard the engine may search"
          >
            ⚙ search
          </button>
          <span className="hidden text-brand-green-muted md:inline" data-testid="engine-note">
            {offline ? 'Live runs need the LocalMind backend.' : info ? `${info.provider} · ${info.model} · ${info.tools.length} read-only tools` : ''}
          </span>
        </form>

        {showSearch && (
          <div className="flex basis-full flex-wrap items-end gap-x-4 gap-y-2 rounded-md border border-brand-border bg-brand-bg-panel-alt px-3 py-2" data-testid="search-panel">
            {(Object.keys(BUDGET_LABEL) as (keyof Budget)[]).map((k) => (
              <label key={k} className="flex flex-col gap-1">
                <span className="text-[11px] text-brand-green-muted">{BUDGET_LABEL[k]}</span>
                <span className="flex items-center gap-1">
                  <input
                    type="number"
                    aria-label={BUDGET_LABEL[k]}
                    min={limits[k][0]}
                    max={limits[k][1]}
                    value={budget[k]}
                    disabled={busy}
                    // Typing is not fought with: the field takes what you type and the bound is applied when
                    // you leave it (and again before the run is sent).
                    onChange={(e) => {
                      const v = Math.max(0, Math.min(999, Math.floor(Number(e.target.value) || 0)));
                      setBudget((b) => ({ ...b, [k]: v }));
                    }}
                    onBlur={() => setBudget((b) => clampBudget(b, limits))}
                    className="w-16 rounded-md border border-brand-border-strong bg-brand-bg-panel px-2 py-1"
                  />
                  <span className="text-brand-green-faint">≤ {limits[k][1]}</span>
                </span>
              </label>
            ))}
            <span className="ml-auto flex items-center gap-2">
              <button type="button" onClick={() => setBudget(DEFAULT_BUDGET)} className="rounded-md border border-brand-border-strong px-2 py-1">reset</button>
              <button
                type="button"
                onClick={rerun}
                disabled={busy || offline || !run.goal}
                className="rounded-md border border-brand-green px-2 py-1 text-brand-green disabled:opacity-50"
                title="Run the active run's goal again with these settings"
              >
                ↻ re-run this goal
              </button>
              <span className="text-[11px] text-brand-green-faint">applies to the next run</span>
            </span>
          </div>
        )}
      </header>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-brand-border bg-brand-bg-panel-alt px-4 py-1.5" data-testid="meters">
        <Meter label="MODEL CALLS" value={meters.calls} max={budget.max_model_calls} />
        <Meter label="DEPTH" value={meters.depth} max={budget.max_depth} />
        <Meter label="BACKTRACKS" value={meters.backtracks} max={budget.max_backtracks} />
        <Meter label="PROBES" value={meters.probes} />
        <Meter label="ELAPSED" value={`${(meters.elapsedMs / 1000).toFixed(1)}s`} />
        <Meter label="PLY" value={meters.plies} />
        {/* The run's curve: the best progress after each applied move. */}
        <span className="ml-auto flex items-center gap-2" title="Best progress after each applied move">
          <span className="text-brand-green-muted">CURVE</span>
          <svg width="90" height="16" aria-hidden="true">
            {curve.length > 1 && (
              <>
                <polyline
                  fill="none"
                  className="stroke-brand-green"
                  strokeWidth="1.5"
                  points={curve.map((p, i) => `${(i / (curve.length - 1)) * 88 + 1},${15 - Math.max(0, Math.min(1, p)) * 13}`).join(' ')}
                />
                <polyline
                  fill="none"
                  className="stroke-brand-green"
                  strokeOpacity="0.18"
                  strokeWidth="1.5"
                  points={`1,15 ${curve.map((p, i) => `${(i / (curve.length - 1)) * 88 + 1},${15 - Math.max(0, Math.min(1, p)) * 13}`).join(' ')} 89,15`}
                />
              </>
            )}
          </svg>
          <b className="text-brand-green-soft">{meters.best.toFixed(2)}</b>
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-brand-border bg-brand-bg-panel px-4 py-1.5">
        <span className="text-brand-green-muted">LAYERS</span>
        <button type="button" aria-pressed={layers.moves} onClick={() => setLayers((l) => ({ ...l, moves: !l.moves }))} className={chip(layers.moves)}>moves</button>
        <button type="button" aria-pressed={layers.failed} onClick={() => setLayers((l) => ({ ...l, failed: !l.failed }))} className={chip(layers.failed)}>failed</button>
        <button type="button" aria-pressed={layers.rejected} onClick={() => setLayers((l) => ({ ...l, rejected: !l.rejected }))} className={chip(layers.rejected)}>not best</button>
        <button type="button" aria-pressed={layers.pruned} onClick={() => setLayers((l) => ({ ...l, pruned: !l.pruned }))} className={chip(layers.pruned)}>pruned</button>
        <span className="mx-1 h-4 w-px bg-brand-border" />
        <button type="button" aria-pressed={spineOnly} onClick={() => setSpineOnly((v) => !v)} className={chip(spineOnly)} title="Show only the path the engine actually took (s)">
          chosen path only
        </button>
        <span className="mx-1 h-4 w-px bg-brand-border" />
        <button type="button" aria-pressed={comparing} onClick={() => setComparing((v) => !v)} className={chip(comparing)} title="Compare two runs (c)">compare runs</button>
        <span className="ml-auto flex items-center gap-2">
          {notice && <span className="text-brand-amber" data-testid="notice">{notice}</span>}
          <button type="button" onClick={exportJson} className="rounded-md border border-brand-border-strong px-2 py-0.5" title="Save the raw events (e)">⤓ json</button>
          <button type="button" onClick={copySummary} className="rounded-md border border-brand-border-strong px-2 py-0.5" title="Copy a plain summary of the run">⧉ summary</button>
          {run.id !== SAMPLE.id && !run.live && (
            <button type="button" onClick={dropRun} className="rounded-md border border-brand-border-strong px-2 py-0.5" title="Forget this run">✕ forget</button>
          )}
          {runs.length > 1 && (
            <button type="button" onClick={clearRuns} className="rounded-md border border-brand-border-strong px-2 py-0.5" title="Forget every stored run">clear all</button>
          )}
        </span>
      </div>

      {comparing ? (
        <div className="min-h-0 flex-1">
          <RunCompare runs={runs} onClose={() => setComparing(false)} />
        </div>
      ) : (
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-56 shrink-0 overflow-auto border-r border-brand-border bg-brand-bg-panel xl:block" aria-label="Move list">
          <h3 className="sticky top-0 border-b border-brand-border bg-brand-bg-panel px-3 py-2 text-[11px] font-semibold tracking-[0.14em] text-brand-green-muted">MOVE LIST</h3>
          <ol>
            {moves.length === 0 && <li className="px-3 py-2 text-brand-green-muted">{run.live ? 'connecting…' : 'no moves'}</li>}
            {moves.map((e) => {
              if (e.kind === 'selected') ply++;
              const text =
                e.kind === 'selected' ? `${ply}. ${e.move} ✓ ${(e.progress ?? 0).toFixed(2)}`
                : e.kind === 'backtrack' ? `↩ backtrack → ${e.node}`
                : e.kind === 'needs_confirmation' ? `🔒 ${e.move} (needs confirmation)`
                : e.kind === 'done' ? `✔ settled: ${String(e.answer).slice(0, 80)}`
                : `⛔ not settled: ${e.reason}`;
              const cls = e.kind === 'backtrack' || e.kind === 'needs_confirmation' ? 'text-brand-amber' : e.kind === 'done' ? 'text-brand-green' : e.kind === 'stopped' ? 'text-brand-red' : '';
              return (
                <li key={e.seq}>
                  <button type="button" onClick={() => jump(e.seq)} className={`w-full truncate border-l-[3px] px-3 py-1.5 text-left hover:bg-brand-bg-panel-alt ${e.seq <= cursor ? 'text-brand-green-soft' : 'text-brand-green-muted'} ${cls} ${
                    e.seq <= cursor && (moves.find((m) => m.seq > e.seq)?.seq ?? Infinity) > cursor ? 'border-brand-green bg-brand-bg-panel-alt' : 'border-transparent'
                  }`}>
                    {text}
                  </button>
                </li>
              );
            })}
          </ol>
        </aside>

        <div className="relative flex w-8 shrink-0 flex-col items-center gap-1 border-r border-brand-border bg-brand-bg-panel py-2 text-[10px] text-brand-green-muted" title="Best progress reached so far" data-testid="eval-bar">
          <span>{meters.best.toFixed(2)}</span>
          <div className="relative min-h-24 w-3.5 flex-1 overflow-hidden rounded bg-brand-border">
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-brand-purple to-brand-green transition-[height] duration-300" style={{ height: `${Math.round(meters.best * 100)}%` }} />
          </div>
          <span>EVAL</span>
        </div>

        <div ref={stageRef} className="relative min-w-0 flex-1 overflow-auto bg-brand-bg-base" aria-label="State tree">
          <div style={{ width: layout.width * scale, height: layout.height * scale }} className="relative">
            <div style={{ transform: `scale(${scale})`, transformOrigin: '0 0' }} className="absolute left-0 top-0">
              <StateTree model={model} layout={layout} cursor={cursor} picked={picked} onPick={setPicked} layers={layers} spineOnly={spineOnly} hoverFp={hoverFp} onHover={setHoverFp} />
            </div>
          </div>
        </div>

        <aside className="hidden w-80 shrink-0 overflow-auto border-l border-brand-border bg-brand-bg-panel lg:block" aria-label="Inspector">
          <h3 className="sticky top-0 border-b border-brand-border bg-brand-bg-panel px-3 py-2 text-[11px] font-semibold tracking-[0.14em] text-brand-green-muted">INSPECTOR</h3>
          <Inspector events={run.events} model={model} picked={picked} cursor={cursor} onPick={setPicked} />
        </aside>
      </div>
      )}

      <footer className="grid gap-2 border-t border-brand-border bg-brand-bg-panel px-4 py-2">
        <div className="relative h-6" data-testid="timeline">
          {run.events.map((e) => (
            <span key={e.seq} aria-hidden="true" title={`#${e.seq} ${e.kind}`} className={`absolute top-1 h-4 w-0.5 rounded ${TICK[e.kind]}`} style={{ left: `${(e.t_ms / runTotalMs) * 100}%` }} />
          ))}
          <input
            type="range"
            aria-label="Timeline"
            min={1}
            max={Math.max(1, total)}
            value={cursor}
            onChange={(e) => jump(Number(e.target.value))}
            className="absolute inset-0 h-6 w-full cursor-pointer opacity-40"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" aria-label="Step back" onClick={() => step(-1)} className="rounded-md border border-brand-border-strong px-2.5 py-1">◀</button>
          <button type="button" onClick={() => (playing ? pause() : play())} className="rounded-md border border-brand-border-strong px-2.5 py-1">
            {playing ? '❚❚ pause' : cursor >= total ? '↺ replay' : '▶ play'}
          </button>
          <button type="button" aria-label="Step forward" onClick={() => step(1)} className="rounded-md border border-brand-border-strong px-2.5 py-1">▶|</button>
          <span className="flex items-center gap-1 text-brand-green-muted">
            <button type="button" aria-label="Zoom out" onClick={() => setUserScale(Math.max(0.3, scale / 1.2))} className="rounded-md border border-brand-border-strong px-2 py-1">−</button>
            <button type="button" onClick={() => setUserScale(null)} className="rounded-md border border-brand-border-strong px-2 py-1">fit</button>
            <button type="button" aria-label="Zoom in" onClick={() => setUserScale(Math.min(1.6, scale * 1.2))} className="rounded-md border border-brand-border-strong px-2 py-1">+</button>
          </span>
          <span className="text-brand-green-muted" data-testid="run-summary">
            {summary.calls} calls · {summary.probes} probes · {summary.plies} plies · {summary.tools.length} tools
          </span>
          <span className="ml-auto text-[11px] text-brand-green-faint">Space play · ←/→ step · j/k · Home/End · 0 fit · ± zoom · s path · c compare · e export</span>
        </div>
        <p className="text-[11px] text-brand-green-faint">
          The engine only looks and reads — it never changes anything. Experimental. Runs use your current provider and model.
        </p>
      </footer>
    </section>
  );
}

const TICK: Record<EngineEvent['kind'], string> = {
  state: 'bg-brand-green-faint',
  candidates: 'bg-brand-purple',
  probe: 'bg-brand-blue',
  evaluation: 'bg-brand-green-faint',
  selected: 'bg-brand-green',
  backtrack: 'bg-brand-amber',
  needs_confirmation: 'bg-brand-purple',
  done: 'bg-brand-green',
  stopped: 'bg-brand-red',
};
