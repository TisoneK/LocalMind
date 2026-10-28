'use client';

import React, { useCallback, useState } from 'react';
import { AlertTriangle, ChevronDown, RefreshCw, Settings2 } from 'lucide-react';
import type { ModelError } from '@/types';

/**
 * Error presentation — the friendly face of a model/provider failure.
 *
 * The backend normalizes provider errors into a canonical `ModelError` object
 * (never the raw payload); this card renders what the user should see: what
 * happened, why, and what they can do next. The raw provider response lives
 * in a collapsed "Technical details" block — the developer/debug surface,
 * not the chat.
 */

/** Human-readable labels for the canonical codes. */
const CODE_LABELS: Record<string, string> = {
  rate_limit: 'Rate limit reached',
  auth_error: 'Authentication failed',
  payment_required: 'Payment required',
  model_not_found: 'Model not found',
  context_overflow: 'Context too long',
  timeout: 'Request timed out',
  server_error: 'Provider error',
  network_error: 'Network error',
  error: 'Error',
};

/** Stronger action hints for non-retryable codes. */
const ACTION_HINTS: Record<string, string> = {
  auth_error: 'Check the API key in Settings.',
  model_not_found: 'Pick a different model below.',
  context_overflow: 'Start a new chat or switch to a larger-context model.',
  payment_required: 'Top up or switch to a free model.',
};

interface ErrorMessageProps {
  error: ModelError;
  /** Re-send the prompt that produced this failure (Try again). */
  onRetry?: () => void;
}

export function ErrorMessage({ error, onRetry }: ErrorMessageProps) {
  const [showDetails, setShowDetails] = useState(false);

  const handleSwitchModel = useCallback(() => {
    // LeftPanel listens and opens the sidebar ModelSelector dropdown.
    window.dispatchEvent(new CustomEvent('localmind:open-model-selector'));
  }, []);

  const codeLabel = CODE_LABELS[error.code] || error.code;
  const hint = ACTION_HINTS[error.code];
  const provider = error.provider || 'unknown';

  return (
    <div
      data-testid="error-message-card"
      className="mt-1 rounded-md border border-brand-red/40 bg-brand-red/5 overflow-hidden"
      role="alert"
    >
      {/* Headline row */}
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <AlertTriangle className="h-4 w-4 text-brand-red shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-[600] text-brand-red">
            Unable to get a response
          </div>
          <div className="mt-0.5 text-[11.5px] text-brand-green-soft leading-relaxed">
            {error.message}
          </div>
          {hint && (
            <div className="mt-1 text-[10.5px] text-brand-green-muted">
              {hint}
            </div>
          )}
        </div>
      </div>

      {/* Meta row: provider · code · retryable */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-2">
        <span className="text-[9.5px] font-mono text-brand-green-muted">
          Provider: <span className="text-brand-green-soft">{provider}</span>
        </span>
        <span className="text-[9.5px] font-mono text-brand-green-muted">
          Status: <span className="text-brand-green-soft">{codeLabel}</span>
        </span>
        <span
          className={`text-[9.5px] font-mono px-1.5 py-px rounded-full border ${
            error.retryable
              ? 'text-brand-amber border-brand-amber/30 bg-brand-amber/5'
              : 'text-brand-green-muted border-brand-border bg-brand-bg-table'
          }`}
        >
          {error.retryable ? 'Retryable' : 'Not retryable'}
        </span>
      </div>

      {/* Actions: Try again ONLY when retrying can actually work — a
          non-retryable failure (balance=0, bad key) makes that button a lie.
          Switch model stays: a different model/provider can still succeed. */}
      <div className="flex flex-wrap items-center gap-2 px-3 pb-2.5">
        {onRetry && error.retryable && (
          <button
            onClick={onRetry}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium border border-brand-green/30 bg-brand-green/10 text-brand-green hover:bg-brand-green/20 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            Try again
          </button>
        )}
        <button
          onClick={handleSwitchModel}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium border border-brand-border bg-brand-bg-table text-brand-green-soft hover:border-brand-green/30 hover:text-brand-green transition-colors"
        >
          <Settings2 className="h-3 w-3" />
          Switch model
        </button>
      </div>

      {/* Collapsed developer details — the raw provider response. Never shown
          by default; this is the debug surface the user's principle allows. */}
      {error.raw !== undefined && error.raw !== null && (
        <details
          // A "too long" verdict on a short chat needs its reason on screen, not behind a click.
          open={error.code === 'context_overflow'}
          className="border-t border-brand-border"
          onToggle={(e) => setShowDetails((e.target as HTMLDetailsElement).open)}
        >
          <summary className="flex items-center gap-1 px-3 py-1.5 cursor-pointer select-none text-[10px] font-mono text-brand-green-faint hover:text-brand-green-muted transition-colors">
            <ChevronDown
              className={`h-3 w-3 transition-transform ${showDetails ? 'rotate-180' : ''}`}
            />
            Technical details
          </summary>
          <pre className="px-3 pb-2.5 text-[10px] font-mono text-brand-green-faint whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
            {typeof error.raw === 'string' ? error.raw : JSON.stringify(error.raw, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
