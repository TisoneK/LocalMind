'use client';

import { useRef, useEffect } from 'react';
import {
  Cpu,
  Brain,
  Wifi,
  WifiOff,
  Shield,
  Loader2,
} from 'lucide-react';
import { ChatMessage as ChatMessageType, ModelOption } from '@/types';
import { ChatMessage } from '@/components/chat/ChatMessage';
import { ChatInput } from '@/components/chat/ChatInput';

// ADR-34 B-10: the intent badge and INTENT_LABELS map are retired.
// Intent classification is no longer a product-facing surface — the
// Agent Workspace is the canonical live UI for agent state.

interface HealthState {
  status: 'online' | 'offline' | 'checking';
  version?: string;
  uptime?: number;
  // ADR-52 phase 2 (Session 309): distinct parent-kernel readiness.
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
  sessionId?: string;
  /** The active model's max input-token budget (adapter effective context
   *  window). Renders the context-window occupancy meter in the top bar. */
  contextWindowSize?: number;
  /** Current window occupancy in tokens (this turn's real prompt size). */
  contextTokens?: number;
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
  sessionId,
  contextWindowSize,
  contextTokens,
}: CenterPanelProps) {
  const messagesContainerRef = useRef<HTMLDivElement>(null);

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
    <div className="h-full min-h-0 flex flex-col bg-brand-bg-base">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-brand-border bg-brand-bg-base">
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
              actionable one (predicts degradation / compaction). */}
          {windowSize && occupancyPct !== null && (
            <div
              className="flex items-center gap-1.5"
              title={`Context window: ${(contextTokens || 0).toLocaleString()} / ${windowSize.toLocaleString()} tokens (${occupancyPct}%)`}
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
          {/* Memory badge */}
          <div className="flex items-center gap-1.5" title={`Memory: ${memoryCount} facts loaded`}>
            <Brain className="h-3 w-3 text-brand-amber" />
            <span className="text-[10px] text-brand-green-muted">{memoryCount}</span>
          </div>
          <div className="w-px h-3 bg-brand-border" />
          {/* Online/offline status */}
          <div className="flex items-center gap-1" title={isOnline ? 'Online' : 'Offline'}>
            {isOnline ? (
              <Wifi className="h-3 w-3 text-brand-green" />
            ) : (
              <WifiOff className="h-3 w-3 text-brand-red" />
            )}
          </div>
          {/* ADR-52 phase 2 (Session 309): distinct parent-kernel readiness.
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

      {/* Messages area */}
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
              />
            );
          })}
        </div>

        {/* Streaming indicator — only show when assistant content is still empty */}
        {/* Session 30: replace static "Thinking..." with real pipeline status. */}
        {/* The engine emits status_update events ("Let me search the web...", */}
        {/* "Understanding your request...", etc.) — show those instead of a */}
        {/* dead "Thinking..." label. Only show "Thinking" when the model is */}
        {/* actually reasoning (thinking_token events fill message.thinking). */}
        {isStreaming && (() => {
          const lastMsg = messages[messages.length - 1];
          const hasContent = lastMsg && lastMsg.role === 'assistant' && lastMsg.content && lastMsg.content.trim().length > 0;
          const hasToolCalls = lastMsg && lastMsg.role === 'assistant' && lastMsg.toolCalls && lastMsg.toolCalls.length > 0;
          const hasThinking = lastMsg && lastMsg.role === 'assistant' && lastMsg.thinking && lastMsg.thinking.trim().length > 0;
          // If there's content or tool calls already visible in the message,
          // don't show the separate indicator — the message itself is the feedback.
          if (hasContent || hasToolCalls) return null;
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
              {/* Session 118: animated activity bar — the agent is working */}
              <div className="mt-2 h-0.5 w-full max-w-[260px] rounded-full bg-brand-border/60 overflow-hidden">
                <div className="h-full w-1/3 rounded-full bg-brand-green animate-[slide-x_1.2s_ease-in-out_infinite]" />
              </div>
            </div>
          );
        })()}


      </div>

      {/* Input */}
      <ChatInput
        onSend={onSend}
        onAbort={onAbort}
        onSteer={onSteer}
        isStreaming={isStreaming}
        modelName={selectedModel.name}
        modelProvider={selectedModel.provider}
        sessionId={sessionId}
      />
    </div>
  );
}
