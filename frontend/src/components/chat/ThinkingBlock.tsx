'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronRight, Brain, Terminal, Copy, Check } from 'lucide-react';
import { ThinkingStep } from '@/types';
import { MarkdownContent } from '@/components/shared/MarkdownContent';
import { useEnterMotion } from '@/lib/localmind/motion';
import { formatLatency } from '@/lib/localmind/progress';

// v0.13: Dispatch steps replace LLM-generated thinking prose. A step line
// looks like "[Web Search] Search: Nairobi weather" — the label is shown as
// a colored chip and the detail as the body.
function getIntentColor(intent: string): string {
  const colors: Record<string, string> = {
    chat: 'text-brand-green-muted',
    web_search: 'text-brand-blue',
    web_fetch: 'text-brand-purple',
    code_exec: 'text-brand-green',
    shell: 'text-brand-amber',
    file_task: 'text-brand-amber-warm',
    file_write: 'text-brand-amber-warm',
    file_edit: 'text-brand-amber-warm',
    sysinfo: 'text-brand-green-muted',
    memory_op: 'text-brand-purple-soft',
    followup: 'text-brand-amber',
  };
  return colors[intent] || 'text-brand-green-muted';
}

interface ThinkingBlockProps {
  thinking: ThinkingStep | string;
  thinkMs?: number;
  /** Whether the parent message is still being streamed. When true, the
   *  block starts expanded so the user watches the reasoning arrive in
   *  real-time (with a live caret + animated indicator). Once streaming
   *  ends, it auto-collapses to save space. */
  isStreaming?: boolean;
}

// Three-dot "thinking" indicator — pulses while the model is reasoning.
function ThinkingDots({ reduceMotion }: { reduceMotion: boolean }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-1 w-1 rounded-full bg-brand-amber"
          animate={reduceMotion ? { opacity: 0.8 } : { opacity: [0.25, 1, 0.25] }}
          transition={reduceMotion ? undefined : { duration: 1.1, repeat: Infinity, ease: 'easeInOut', delay: i * 0.18 }}
        />
      ))}
    </span>
  );
}

export function ThinkingBlock({ thinking, thinkMs, isStreaming }: ThinkingBlockProps) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  // Start expanded during streaming so thinking content is visible.
  // Collapse automatically when streaming finishes.
  const [collapsed, setCollapsed] = useState(!isStreaming);
  // Copy state for the footer button (copies the full trace).
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-collapse when streaming transitions from true → false
  useEffect(() => {
    if (!isStreaming) {
      const timer = setTimeout(() => setCollapsed(true), 1500);
      return () => clearTimeout(timer);
    } else {
      setCollapsed(false);
    }
  }, [isStreaming]);

  const content = typeof thinking === 'string' ? thinking : thinking.content;
  const duration = thinkMs;

  // Keep newly streamed reasoning visible — whenever the
  // content grows (or the block is re-expanded), scroll to the bottom so
  // the latest thought is in view instead of hiding above the fold.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [content, collapsed]);

  const handleCopy = useCallback(() => {
    if (!content) return;
    navigator.clipboard?.writeText(content).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [content]);

  // v0.13: Parse structured step lines from the thinking stream.
  // A step line looks like: "[Web Search] Search: Nairobi weather"
  const isStep = content.match(/^\[(.+?)\]\s*.+$/);
  const stepLabel = isStep ? isStep[1] : null;
  const stepColor = stepLabel ? getIntentColor(stepLabel.replace(/\s+/g, '_').toLowerCase()) : '';

  return (
    <motion.div
      {...enter({ y: 3, duration: 0.22 })}
      className={`mb-2 overflow-hidden rounded-md border ${
        isStreaming ? 'border-brand-amber/30' : 'border-brand-border'
      }`}
    >
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full items-center gap-2 bg-brand-bg-code px-3 py-1.5 text-left transition-colors hover:bg-brand-bg-rail"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 text-brand-green-muted transition-transform ${!collapsed ? 'rotate-90' : ''}`}
        />
        <Brain
          className={`h-3 w-3 shrink-0 ${stepColor || (isStreaming ? 'text-brand-amber' : 'text-brand-green-muted')} ${
            isStreaming && !reduceMotion ? 'animate-pulse' : ''
          }`}
        />
        <span className={`text-[10px] font-medium uppercase tracking-wider ${stepColor || (isStreaming ? 'text-brand-amber' : 'text-brand-green-muted')}`}>
          {/* User-facing label. Previously "Thought process"
              (exposing internal reasoning). The user-facing
              box is now "Thinking" (the internal analysis pass is labeled
              "Approach" in AgentPhases; names swapped, no behavior change).
              "Working" while streaming. */}
          {stepLabel || (isStreaming ? 'Working' : 'Thinking')}
        </span>
        {isStreaming ? (
          <ThinkingDots reduceMotion={reduceMotion} />
        ) : (
          duration !== undefined && duration > 0 && (
            <span className="ml-auto text-[9px] text-brand-amber">
              {formatLatency(duration)}
            </span>
          )
        )}
      </button>
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            initial={reduceMotion ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={reduceMotion ? undefined : { opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
            className="overflow-hidden border-t border-brand-border bg-brand-bg-dark"
          >
            {/* Bounded-height reasoning with its own scrollbar — a long
                thought process scrolls instead of stretching the message;
                new tokens auto-scroll into view. */}
            <div
              ref={scrollRef}
              data-testid="thinking-scroll"
              className="max-h-64 overflow-y-auto custom-scrollbar"
            >
              {stepLabel ? (
                <div className="whitespace-pre-wrap break-words px-3 py-2 text-[11px] leading-relaxed text-brand-green-muted">
                  <div className="flex items-start gap-2">
                    <Terminal className={`mt-0.5 h-3 w-3 shrink-0 ${stepColor}`} />
                    <span>
                      {content}
                      {isStreaming && <LiveCaret reduceMotion={reduceMotion} />}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="px-3 py-2">
                  {/* The model writes its reasoning in markdown — render it
                      through the same pipeline as answers so headings, lists,
                      emphasis and code format instead of dumping raw. */}
                  <MarkdownContent text={content} />
                  {isStreaming && <LiveCaret reduceMotion={reduceMotion} />}
                </div>
              )}
            </div>
            {/* Footer: copy the full reasoning trace */}
            <div className="flex items-center justify-end border-t border-brand-border/60 px-2 py-1">
              <button
                type="button"
                onClick={handleCopy}
                disabled={!content}
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] text-brand-green-muted transition-colors hover:text-brand-green hover:bg-brand-green/10 disabled:opacity-40 disabled:cursor-not-allowed"
                title={copied ? 'Copied' : 'Copy reasoning'}
              >
                {copied ? <Check className="h-3 w-3 text-brand-green" /> : <Copy className="h-3 w-3" />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// Blinking caret rendered at the end of the streaming reasoning text, so the
// block reads as if it is being written live token-by-token.
function LiveCaret({ reduceMotion }: { reduceMotion: boolean }) {
  return (
    <motion.span
      className="ml-0.5 inline-block h-[0.95em] w-[2px] translate-y-[2px] bg-brand-green"
      aria-hidden="true"
      animate={reduceMotion ? { opacity: 1 } : { opacity: [1, 0.15, 1] }}
      transition={reduceMotion ? undefined : { duration: 0.9, repeat: Infinity, ease: 'linear' }}
    />
  );
}
