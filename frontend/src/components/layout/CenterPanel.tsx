'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import {
  Cpu,
  Brain,
  Lightbulb,
  UserRound,
  Wifi,
  WifiOff,
  Shield,
  Loader2,
  X,
} from 'lucide-react';
import { ChatMessage as ChatMessageType, ModelOption, DiffData, ReflectionLesson, PassiveMemory } from '@/types';
import { ChatMessage } from '@/components/chat/ChatMessage';
import { ChatInput } from '@/components/chat/ChatInput';
import { TranscriptContextMenu } from '@/components/chat/TranscriptContextMenu';
import { localmindClient } from '@/lib/localmind/client';
import type { TodoItem } from '@/types';

// The intent badge and INTENT_LABELS map are retired.
// Intent classification is no longer a product-facing surface — the
// Agent Workspace is the canonical live UI for agent state.

// Category labels for the context-usage breakdown panel. Keys match the
// backend's per-category estimator (context_breakdown).
const BREAKDOWN_LABELS: Record<string, string> = {
  system_prompt: 'System prompt',
  turn_context: 'Turn context',
  tool_schemas: 'Tool schemas',
  history: 'Conversation history',
  current_message: 'Current message',
  tool_results: 'Tool results',
  turn_additions: 'Loop injections',
};

interface HealthState {
  status: 'online' | 'offline' | 'checking';
  version?: string;
  uptime?: number;
  // Distinct parent-kernel readiness.
  // When parentReady is false, the boot kernel is degraded (provider
  // warmup failed) — the parent will retry lazily on the first turn.
  // parentDegradedReason carries the failure string for the tooltip.
  parentReady?: boolean;
  parentDegradedReason?: string;
}

/**
 * Find the user prompt that precedes an assistant message so Retry can
 * re-send it (regenerate semantics: append a new turn with the same prompt;
 * there is no backend replace/regenerate endpoint). Returns undefined for
 * user messages or when no preceding user message has content.
 */
export function findRetryPrompt(messages: ChatMessageType[], index: number): string | undefined {
  if (messages[index]?.role !== 'assistant') return undefined;
  for (let j = index - 1; j >= 0; j--) {
    const prev = messages[j];
    if (prev.role === 'user' && prev.content) {
      return prev.content;
    }
  }
  return undefined;
}

interface CenterPanelProps {
  messages: ChatMessageType[];
  selectedModel: ModelOption;
  isStreaming: boolean;
  health: HealthState;
  onSend: (message: string, tool?: string) => void;
  onAbort: () => void;
  onSteer?: (message: string) => void;
  memoryCount: number;
  /** The session's plan; the last agent turn shows it as step progress. */
  todos?: TodoItem[];
  sessionId?: string;
  /** The active model's max input-token budget (adapter effective context
   *  window). Renders the context-window occupancy meter in the top bar. */
  contextWindowSize?: number;
  /** Current window occupancy in tokens (this turn's real prompt size). */
  contextTokens?: number;
  /** P0 Context Engineering Step 1: last request's provider-reported cache-hit
   *  input tokens (0 when the provider doesn't report caching). Shows the
   *  cached share next to the occupancy percentage. */
  cachedTokens?: number;
  /** Per-category token shares of the last model call's prompt (empty/absent
   *  when the turn never reached the agent loop). Clicking the occupancy
   *  meter opens a breakdown panel so the user can see WHAT fills the
   *  window — system prompt, tool schemas, history, tool results, ... */
  contextBreakdown?: Record<string, number>;
  /** Visible log of lessons the self-reflection loop wrote to memory on its
   *  own this session (B-2026-09-15-14) — clicking the lesson badge opens
   *  the list so proactive writes are never silent. */
  reflectionLessons?: ReflectionLesson[];
  /** Visible log of durable self-facts the agent stored on its own from
   *  incidental conversation signals (B-2026-09-15-15) — same audit surface
   *  as the reflection lessons. */
  passiveMemories?: PassiveMemory[];
  /** Per-path diff hunks captured this turn (preview Diff mode). */
  fileDiffs?: Record<string, DiffData>;
  /** Current chat mode. */
  chatMode?: string;
  /** Callback to change chat mode. */
  onChatModeChange?: (mode: 'auto' | 'agent' | 'direct') => void;
}

export function CenterPanel({
  messages,
  selectedModel,
  isStreaming,
  health,
  onSend,
  onAbort,
  onSteer,
  memoryCount,
  todos,
  sessionId,
  contextWindowSize,
  contextTokens,
  cachedTokens,
  contextBreakdown,
  reflectionLessons,
  passiveMemories,
  fileDiffs,
  chatMode,
  onChatModeChange,
}: CenterPanelProps) {
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  // Guide the user in chat when the configured embed model
  // isn't pulled in Ollama but an alternative is — memory stores would
  // otherwise silently fail. Dismissed per session (sessionStorage) so it
  // doesn't nag after the user has seen it once.
  const [embedGuide, setEmbedGuide] = useState<{ configured: string; suggested: string } | null>(null);
  // One-click auto-fix: switching the embed model
  // right from the banner instead of sending the user to Settings.
  const [embedFixing, setEmbedFixing] = useState(false);
  const [embedFixed, setEmbedFixed] = useState(false);
  const [embedFixError, setEmbedFixError] = useState<string | null>(null);

  useEffect(() => {
    if (sessionStorage.getItem('localmind:embed-guide-dismissed') === '1') return;
    let mounted = true;
    localmindClient.getEmbeddingModels().then((info) => {
      if (!mounted) return;
      // Only guide when the configured model is genuinely missing and there's
      // a real pulled alternative to offer.
      if (info.configured_available === false && info.current && info.suggested) {
        setEmbedGuide({ configured: info.current, suggested: info.suggested });
      }
    }).catch(() => { /* non-fatal: Ollama may be off */ });
    return () => { mounted = false; };
  }, []);

  const dismissEmbedGuide = () => {
    setEmbedGuide(null);
    sessionStorage.setItem('localmind:embed-guide-dismissed', '1');
  };

  // Apply the suggested embed model via POST /api/settings/local — the same
  // endpoint the Settings modal uses — so the fix is one click. On success the
  // banner flips to a confirmation and then dismisses itself for the session.
  const applyEmbedFix = async () => {
    if (!embedGuide || embedFixing) return;
    setEmbedFixing(true);
    setEmbedFixError(null);
    try {
      await localmindClient.setLocalSettings({ embedModel: embedGuide.suggested });
      setEmbedFixed(true);
      sessionStorage.setItem('localmind:embed-guide-dismissed', '1');
      // Let the confirmation read before collapsing.
      window.setTimeout(() => setEmbedGuide(null), 1500);
    } catch {
      setEmbedFixError('Failed to update the embedding model. Open Settings to set it manually.');
    } finally {
      setEmbedFixing(false);
    }
  };

  // Scroll only the transcript container on new messages. Calling
  // scrollIntoView() on a nested marker can also scroll outer ancestors,
  // which may move the entire workspace (including the header) in a flex
  // layout. Targeting this container keeps the document viewport fixed.
  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    container.scrollTo({
      top: container.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages]);

  // Right-click menu: full text of the message under the pointer ("Copy
  // message" copies the stored source — markdown for assistant replies —
  // the same text the hover Copy chip uses).
  const getMessageText = useCallback(
    (messageId: string) => messages.find((m) => m.id === messageId)?.content,
    [messages],
  );

  // Select all text within the transcript (not the whole document — a
  // document-wide Ctrl+A would sweep in the side panels and chrome).
  const selectAllTranscript = useCallback(() => {
    const container = messagesContainerRef.current;
    const selection = window.getSelection();
    if (!container || !selection) return;
    const range = document.createRange();
    range.selectNodeContents(container);
    selection.removeAllRanges();
    selection.addRange(range);
  }, []);


  const isOnline = health.status === 'online';

  // Context-window occupancy (replaces the old confidence badge): this turn's
  // prompt size / the model's real max budget. The top bar's "percentage that
  // matters" is now the one that predicts whether the next message degrades.
  const windowSize = contextWindowSize && contextWindowSize > 0 ? contextWindowSize : null;
  const occupancyPct = windowSize
    ? Math.min(100, Math.round(((contextTokens || 0) / windowSize) * 100))
    : null;
  const occupancyColor = occupancyPct === null
    ? ''
    : occupancyPct >= 85
      ? 'bg-brand-red'
      : occupancyPct >= 60
        ? 'bg-brand-amber'
        : 'bg-brand-green';
  // P0 Context Engineering Step 1: the cached share of that prompt (last
  // request's cache-hit tokens) — the meter's raw percentage overstates the
  // real load when the provider's prompt cache is serving most of it.
  const cacheHitPct = cachedTokens && contextTokens && contextTokens > 0
    ? Math.min(100, Math.round((cachedTokens / contextTokens) * 100))
    : 0;

  // Context-usage breakdown: the meter shows ONE occupancy number; clicking
  // it opens the per-category shares so the user can see WHAT fills the
  // window (system prompt, tool schemas, history, tool results, ...). The
  // entries come pre-scaled from the backend to the provider-reported prompt
  // total of the last call; percentages are shares of that call.
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const breakdownEntries = (() => {
    const b = contextBreakdown ?? {};
    const total = Object.values(b).reduce((s, v) => s + (Number(v) || 0), 0);
    if (total <= 0) return [] as { key: string; label: string; tokens: number; pct: number }[];
    return Object.entries(b)
      .filter(([, v]) => Number(v) > 0)
      .sort((a, c) => Number(c[1]) - Number(a[1]))
      .map(([key, tokens]) => ({
        key,
        label: BREAKDOWN_LABELS[key] ?? key.replace(/_/g, ' '),
        tokens: Number(tokens),
        pct: Math.round((Number(tokens) / total) * 100),
      }));
  })();
  const toggleBreakdown = () => {
    if (breakdownEntries.length > 0) setBreakdownOpen((o) => !o);
  };

  // Reflection-lesson log (B-2026-09-15-14): visible surface for the
  // self-reflection loop's autonomous memory writes. Owner decision
  // 2026-09-18 — proactive writes must never be silent, so every lesson the
  // loop stores shows up here, newest first.
  const [lessonsOpen, setLessonsOpen] = useState(false);
  const lessons = reflectionLessons ?? [];
  const toggleLessons = () => {
    if (lessons.length > 0) setLessonsOpen((o) => !o);
  };

  // Passive-context log (B-2026-09-15-15): visible surface for durable
  // self-facts the agent stored on its own from incidental conversation
  // signals — no "remember this" trigger. Same audit rule as the lessons.
  const [passiveOpen, setPassiveOpen] = useState(false);
  const passives = passiveMemories ?? [];
  const togglePassives = () => {
    if (passives.length > 0) setPassiveOpen((o) => !o);
  };

  // Clean up model name for display: remove internal suffixes, format nicely
  const rawModelName = selectedModel?.name || selectedModel?.id || '';
  const displayModelName = rawModelName
    ? rawModelName
        .replace(/\s*-\s*zen$/i, '')
        .replace(/\s*-\s*local$/i, '')
        .replace(/^ollama[:/]/, '')
        .replace(/_/g, ' ')
        .replace(/^\w/, c => c.toUpperCase())
        .trim()
    : 'Connecting…';

  return (
    <div className="h-full min-h-0 flex flex-col bg-brand-bg-app">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-brand-border bg-brand-bg-app">
        <div className="flex items-center gap-3">
          <h1 className="text-[12px] font-medium text-brand-green-soft">
            LocalMind Assistant
          </h1>
          {/* Model badge — green pill showing the active model */}
          <span
            className="text-[9px] px-2 py-0.5 rounded-full bg-brand-green/15 text-brand-green border border-brand-green/20 font-mono truncate max-w-[180px]"
            title={`Model: ${selectedModel?.name || selectedModel?.id}`}
          >
            {displayModelName}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Context-window occupancy meter — the confidence badge was removed:
              it duplicated the Observe panel's Intent Classification section
              and was low-value as an always-on number. The window meter is the
              actionable one (predicts degradation / compaction). Clicking it
              opens the per-category breakdown when the backend reported one. */}
          <div className="relative flex items-center gap-3">
          {windowSize && occupancyPct !== null && (cachedTokens || 0) > 0 && (
            <div
              className={`flex items-center gap-1.5${breakdownEntries.length ? ' cursor-pointer' : ''}`}
              onClick={toggleBreakdown}
              title={`Last model call: ${(contextTokens || 0).toLocaleString()} / ${windowSize.toLocaleString()} context tokens (${occupancyPct}%). ${(cachedTokens || 0).toLocaleString()} of them were served from the provider's prompt cache at ~10% of the price. The stats corner's prompt counter is the session cumulative — calls re-send history, so per-turn prompts overlap rather than stack.${breakdownEntries.length ? ' Click for the per-category breakdown.' : ''}`}
            >
              <span className="text-[9px] text-brand-green-muted uppercase tracking-wider">Context</span>
              <div className="w-14 h-1.5 rounded-full bg-brand-border overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${occupancyColor}`}
                  style={{ width: `${occupancyPct}%` }}
                />
              </div>
              <span className="text-[10px] font-mono text-brand-green-soft">{occupancyPct}%</span>
              <span
                className="text-[9px] font-mono text-brand-green"
                title={`${(cachedTokens || 0).toLocaleString()} of the last call's ${(contextTokens || 0).toLocaleString()} input tokens hit the provider's prompt cache (~10% cost) — the real inference load is well under the raw percentage. This is the LAST call's share; the stats corner's "cached:" is the whole session's share, so the two can differ.`}
              >
                · {cacheHitPct}% cached
              </span>
            </div>
          )}
          {windowSize && occupancyPct !== null && !(cachedTokens || 0) && (
            <div
              className={`flex items-center gap-1.5${breakdownEntries.length ? ' cursor-pointer' : ''}`}
              onClick={toggleBreakdown}
              title={`Last model call: ${(contextTokens || 0).toLocaleString()} / ${windowSize.toLocaleString()} context tokens (${occupancyPct}%). The stats corner's prompt counter is the session cumulative — calls re-send history, so per-turn prompts overlap rather than stack.${breakdownEntries.length ? ' Click for the per-category breakdown.' : ''}`}
            >
              <span className="text-[9px] text-brand-green-muted uppercase tracking-wider">Context</span>
              <div className="w-14 h-1.5 rounded-full bg-brand-border overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${occupancyColor}`}
                  style={{ width: `${occupancyPct}%` }}
                />
              </div>
              <span className="text-[10px] font-mono text-brand-green-soft">{occupancyPct}%</span>
            </div>
          )}
          {/* Window unknown (provider doesn't report it, model not in the
              registry): show the last call's token count WITHOUT a fake
              percentage — a meter against a guessed denominator lies. */}
          {!windowSize && (contextTokens || 0) > 0 && (
            <div
              className={`flex items-center gap-1.5${breakdownEntries.length ? ' cursor-pointer' : ''}`}
              onClick={toggleBreakdown}
              title={`Last model call: ${(contextTokens || 0).toLocaleString()} tokens. The model's context window is unknown (the provider doesn't report it and it isn't in the registry), so no percentage is shown — a meter against a guessed denominator would lie.${breakdownEntries.length ? ' Click for the per-category breakdown.' : ''}`}
            >
              <span className="text-[9px] text-brand-green-muted uppercase tracking-wider">Context</span>
              <span className="text-[10px] font-mono text-brand-green-soft">
                {(contextTokens || 0).toLocaleString()} tok · window unknown
              </span>
            </div>
          )}
          {/* Per-category breakdown popover (last model call). */}
          {breakdownOpen && breakdownEntries.length > 0 && (
            <div className="absolute right-0 top-full mt-1.5 z-30 w-64 rounded-md border border-brand-border bg-brand-bg-panel p-2.5 shadow-xl">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[9px] uppercase tracking-wider text-brand-green-muted">
                  Context — last model call
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); setBreakdownOpen(false); }}
                  className="text-brand-green-muted hover:text-brand-green-soft"
                  aria-label="Close context breakdown"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
              {breakdownEntries.map((e) => (
                <div key={e.key} className="mb-1.5 last:mb-0">
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-brand-green-soft">{e.label}</span>
                    <span className="font-mono text-brand-green-muted">
                      {e.tokens.toLocaleString()} · {e.pct}%
                    </span>
                  </div>
                  <div className="h-1 rounded-full bg-brand-border overflow-hidden">
                    <div
                      className="h-full rounded-full bg-brand-green/70"
                      style={{ width: `${Math.min(100, e.pct)}%` }}
                    />
                  </div>
                </div>
              ))}
              <div className="text-[9px] leading-snug text-brand-green-muted mt-1.5 pt-1.5 border-t border-brand-border">
                Shares of the last call's prompt, scaled to the provider-reported
                total. Estimates per category — the total is exact.
              </div>
            </div>
          )}
          </div>
          {/* Memory badge */}
          <div className="flex items-center gap-1.5" title={`Memory: ${memoryCount} facts loaded`}>
            <Brain className="h-3 w-3 text-brand-amber" />
            <span className="text-[10px] text-brand-green-muted">{memoryCount}</span>
          </div>
          {/* Reflection-lesson badge: the visible log for the self-reflection
              loop's own autonomous memory writes (B-2026-09-15-14). Hidden
              when no lesson has been noted this session — nothing to click. */}
          {lessons.length > 0 && (
            <div className="relative">
              <div
                className="flex items-center gap-1.5 cursor-pointer"
                onClick={toggleLessons}
                data-testid="reflection-lesson-badge"
                title={`${lessons.length} lesson${lessons.length === 1 ? '' : 's'} the agent noted about its own answers this session. Click to review what it decided to remember.`}
              >
                <Lightbulb className="h-3 w-3 text-brand-amber" />
                <span className="text-[10px] text-brand-green-muted">{lessons.length}</span>
              </div>
              {lessonsOpen && (
                <div
                  className="absolute right-0 top-full mt-1.5 z-30 w-72 max-h-80 overflow-y-auto rounded-md border border-brand-border bg-brand-bg-panel p-2.5 shadow-xl"
                  data-testid="reflection-lesson-panel"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[9px] uppercase tracking-wider text-brand-green-muted">
                      Self-reflection lessons
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); setLessonsOpen(false); }}
                      className="text-brand-green-muted hover:text-brand-green-soft"
                      aria-label="Close reflection lessons"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                  {[...lessons].reverse().map((lesson) => (
                    <div key={lesson.id} className="mb-2 last:mb-0 pb-2 last:pb-0 border-b last:border-0 border-brand-border">
                      <div className="text-[10px] text-brand-green-soft leading-snug">{lesson.text}</div>
                      <div className="text-[9px] text-brand-green-muted mt-0.5">
                        {lesson.intent && `${lesson.intent} · `}score {lesson.score}/10
                        {lesson.confidence && ` · ${lesson.confidence} confidence`}
                      </div>
                    </div>
                  ))}
                  <div className="text-[9px] leading-snug text-brand-green-muted mt-1.5 pt-1.5 border-t border-brand-border">
                    Written to memory automatically, without being asked — this
                    log exists so that stays visible instead of silent.
                  </div>
                </div>
              )}
            </div>
          )}
          {/* Passive-memory badge: the visible log for durable self-facts the
              agent picked up from incidental conversation and stored on its
              own (B-2026-09-15-15). Hidden until the first passive write. */}
          {passives.length > 0 && (
            <div className="relative">
              <div
                className="flex items-center gap-1.5 cursor-pointer"
                onClick={togglePassives}
                data-testid="passive-memory-badge"
                title={`${passives.length} fact${passives.length === 1 ? '' : 's'} the agent picked up from this conversation and remembered on its own. Click to review what it decided to remember.`}
              >
                <UserRound className="h-3 w-3 text-brand-amber" />
                <span className="text-[10px] text-brand-green-muted">{passives.length}</span>
              </div>
              {passiveOpen && (
                <div
                  className="absolute right-0 top-full mt-1.5 z-30 w-72 max-h-80 overflow-y-auto rounded-md border border-brand-border bg-brand-bg-panel p-2.5 shadow-xl"
                  data-testid="passive-memory-panel"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[9px] uppercase tracking-wider text-brand-green-muted">
                      Picked up from conversation
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); setPassiveOpen(false); }}
                      className="text-brand-green-muted hover:text-brand-green-soft"
                      aria-label="Close passive memory log"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                  {[...passives].reverse().map((item) => (
                    <div key={item.id} className="mb-2 last:mb-0 pb-2 last:pb-0 border-b last:border-0 border-brand-border">
                      <div className="text-[10px] text-brand-green-soft leading-snug">{item.text}</div>
                      <div className="text-[9px] text-brand-green-muted mt-0.5">
                        {item.subject && item.subject !== 'general' && `${item.subject} · `}
                        remembered without being asked
                      </div>
                    </div>
                  ))}
                  <div className="text-[9px] leading-snug text-brand-green-muted mt-1.5 pt-1.5 border-t border-brand-border">
                    Noticed in what you said — no "remember this" needed — and
                    written to memory automatically. This log keeps those
                    writes visible; ask me to forget any of them and I will.
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="w-px h-3 bg-brand-border" />
          {/* Online/offline status */}
          <div className="flex items-center gap-1" title={isOnline ? 'Online' : 'Offline'}>
            {isOnline ? (
              <Wifi className="h-3 w-3 text-brand-green" />
            ) : (
              <WifiOff className="h-3 w-3 text-brand-red" />
            )}
          </div>
          {/* Distinct parent-kernel readiness.
              Shows a warning dot when the parent kernel is degraded (provider
              warmup failed at boot). The parent still serves requests via
              lazy retry, but the user should know something is off. Hidden
              when health is checking/offline or parentReady is true/undefined. */}
          {isOnline && health.parentReady === false && (
            <div
              className="flex items-center gap-1"
              title={`Parent kernel degraded${health.parentDegradedReason ? `: ${health.parentDegradedReason}` : ''}. The first turn may be slow while it retries.`}
            >
              <span
                className="h-2 w-2 rounded-full bg-brand-amber"
                data-testid="parent-degraded-indicator"
              />
            </div>
          )}
          <div className="flex items-center gap-1" title="Local execution">
            <Shield className="h-3 w-3 text-brand-green" />
            <span className="text-[9px] text-brand-green-muted">Local</span>
          </div>
        </div>
      </div>

      {/* Embed-model guide — shown when the configured
          embedding model isn't installed but an alternative is pulled.
          One-click fix: the primary button applies the suggested model via
          the same settings endpoint the Settings modal uses. */}
      {embedGuide && (
        <div
          className="mx-4 mt-2 flex flex-wrap items-center gap-2 rounded-md border border-brand-amber/30 bg-brand-amber/10 px-2.5 py-1.5 text-[11px] text-brand-amber"
          data-testid="embed-guide"
        >
          {embedFixed ? (
            <span className="flex-1 min-w-0 text-brand-green">
              ✓ Embedding model switched to <span className="font-mono">{embedGuide.suggested}</span> — memory can be saved now.
            </span>
          ) : (
            <>
              <span className="flex-1 min-w-0">
                💡 Your embedding model <span className="font-mono">{embedGuide.configured}</span> isn't installed in Ollama — memory can't be saved.
              </span>
              <button
                type="button"
                onClick={applyEmbedFix}
                disabled={embedFixing}
                className="rounded border border-brand-amber/40 bg-brand-amber/10 px-1.5 py-0.5 text-[10px] font-medium text-brand-amber hover:bg-brand-amber/20 disabled:opacity-50 transition-colors"
                data-testid="embed-guide-fix"
              >
                {embedFixing ? (
                  <span className="flex items-center gap-1"><Loader2 className="h-2.5 w-2.5 animate-spin" /> Switching…</span>
                ) : (
                  <>Use {embedGuide.suggested}</>
                )}
              </button>
              {embedFixError && <span className="w-full text-brand-red text-[10px]">{embedFixError}</span>}
            </>
          )}
          <button
            type="button"
            onClick={dismissEmbedGuide}
            className="p-0.5 rounded text-brand-amber/60 hover:text-brand-amber transition-colors"
            title="Dismiss"
            data-testid="embed-guide-dismiss"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Messages area — wrapped in the right-click menu (copy selection /
          copy message / select all) */}
      <TranscriptContextMenu getMessageText={getMessageText} onSelectAll={selectAllTranscript}>
        <div ref={messagesContainerRef} className="flex-1 min-h-0 overflow-y-auto custom-scrollbar min-w-0">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-center px-8">
              <div className="w-12 h-12 rounded-xl bg-brand-green/10 flex items-center justify-center">
                <Cpu className="h-6 w-6 text-brand-green" />
              </div>
              <div>
                <h2 className="text-sm font-medium text-brand-green-soft mb-1">
                  Welcome to LocalMind
                </h2>
                <p className="text-[11px] text-brand-green-muted max-w-sm">
                  Your local AI assistant. Ask me to build, debug, explain, or refactor code.
                  I can read files, run commands, search code, and more.
                </p>
              </div>
            </div>
          )}

          <div className="divide-y divide-brand-border/50 overflow-hidden">
            {messages.map((msg, i) => {
              // Retry = regenerate the response to the user message that
              // precedes this assistant reply (re-sends that exact prompt).
              const prompt = findRetryPrompt(messages, i);
              return (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  isStreaming={isStreaming && msg === messages[messages.length - 1] && msg.role === 'assistant'}
                  onRetry={prompt ? () => onSend(prompt) : undefined}
                  fileDiffs={fileDiffs}
                  todos={msg === messages[messages.length - 1] ? todos : undefined}
                />
              );
            })}
          </div>

        {/* Streaming indicator — only show when assistant content is still empty */}
        {/* Replace static "Thinking..." with real pipeline status. */}
        {/* The engine emits status_update events ("Let me search the web...", */}
        {/* "Understanding your request...", etc.) — show those instead of a */}
        {/* dead "Thinking..." label. Only show "Thinking" when the model is */}
        {/* actually reasoning (thinking_token events fill message.thinking). */}
          {isStreaming && (() => {
            const lastMsg = messages[messages.length - 1];
            const hasContent = lastMsg && lastMsg.role === 'assistant' && lastMsg.content && lastMsg.content.trim().length > 0;
            const hasThinking = lastMsg && lastMsg.role === 'assistant' && lastMsg.thinking && lastMsg.thinking.trim().length > 0;
            // Only hide the status indicator when the FINAL ANSWER
            // (content) is being streamed — not when thinking text is visible.
            // The old check (hasContent || hasToolCalls) hid the status as soon
            // as thinking started, leaving the user in the dark for the entire
            // tool execution phase. Tool calls should NOT hide the status —
            // the status shows "Searching..." / "Fetching..." alongside the
            // tool cards in the Actions panel.
            if (hasContent) return null;
            // Once the assistant reply exists its turn header (spinner, status,
            // heartbeat) is the one live indicator — a second one just repeats it.
            if (lastMsg?.role === 'assistant') return null;
            // Get the status text — prefer the real pipeline status, fall back
            // to "Thinking" only if the model is actually reasoning, otherwise
            // "Working on it..." as the initial acknowledgment.
            const statusText = lastMsg?.statusText || (hasThinking ? 'Thinking' : 'Working on it...');
            return (
              <div className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-3 w-3 text-brand-green animate-spin" />
                  <span className="text-[10px] text-brand-green-muted">{statusText}</span>
                  <span className="flex gap-0.5">
                    <span className="w-1 h-1 bg-brand-green rounded-full animate-bounce [animation-delay:0ms]" />
                    <span className="w-1 h-1 bg-brand-green rounded-full animate-bounce [animation-delay:150ms]" />
                    <span className="w-1 h-1 bg-brand-green rounded-full animate-bounce [animation-delay:300ms]" />
                  </span>
                </div>
                {/* Animated activity bar — the agent is working */}
                <div className="mt-2 h-0.5 w-full max-w-[260px] rounded-full bg-brand-border/60 overflow-hidden">
                  <div className="h-full w-1/3 rounded-full bg-brand-green animate-[slide-x_1.2s_ease-in-out_infinite]" />
                </div>
              </div>
            );
          })()}


        </div>
      </TranscriptContextMenu>

      {/* Input */}
      <ChatInput
        onSend={onSend}
        onAbort={onAbort}
        onSteer={onSteer}
        isStreaming={isStreaming}
        modelName={selectedModel.name}
        modelProvider={selectedModel.provider}
        sessionId={sessionId}
        chatMode={chatMode}
        onChatModeChange={onChatModeChange}
      />
    </div>
  );
}
