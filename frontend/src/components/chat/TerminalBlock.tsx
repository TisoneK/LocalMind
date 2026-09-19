/**
 * TerminalBlock — a shell / code step rendered as a terminal, inside the turn.
 *
 * The agent's commands used to be visible only in a separate side tab. Showing the
 * command and its output where the work happened keeps the story in one place: what
 * ran, what it printed, and whether it worked.
 */

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import type { ToolCall } from '@/types';

// Terminal colour / cursor escape sequences (ESC [ … final-byte), stripped so output reads
// as plain text. ESC is built from its char code so no control character sits in the source.
const ANSI = new RegExp(`${String.fromCharCode(27)}\\[[0-9;?]*[ -/]*[@-~]`, 'g');

export function TerminalBlock({ tool }: { tool: ToolCall }) {
  const [copied, setCopied] = useState(false);
  const isCode = tool.name === 'code_exec';
  const failed = tool.status === 'failed';
  const output = (tool.error || tool.output || '').replace(ANSI, '').replace(/\s+$/, '');

  const copy = () => {
    void navigator.clipboard?.writeText(tool.input).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };

  return (
    <div
      className={`my-1 overflow-hidden rounded-md border bg-black/40 font-mono text-[10.5px] ${
        failed ? 'border-red-400/30' : 'border-white/10'
      }`}
      data-testid="terminal-block"
    >
      <div className="flex items-start gap-2 border-b border-white/[0.06] px-2.5 py-1.5">
        {isCode ? (
          <span className="shrink-0 rounded bg-white/10 px-1 text-[9px] uppercase text-brand-green-muted">python</span>
        ) : (
          <span className="shrink-0 select-none text-brand-green" aria-hidden>
            $
          </span>
        )}
        <code className="min-w-0 flex-1 whitespace-pre-wrap break-all text-brand-green-soft">{tool.input}</code>
        <button
          type="button"
          onClick={copy}
          title={copied ? 'Copied' : isCode ? 'Copy code' : 'Copy command'}
          aria-label={isCode ? 'Copy code' : 'Copy command'}
          className="shrink-0 rounded p-0.5 text-brand-green-muted hover:text-brand-green"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      {output ? (
        <pre
          className={`max-h-56 overflow-auto whitespace-pre-wrap break-words px-2.5 py-1.5 leading-relaxed ${
            failed ? 'text-red-300' : 'text-brand-green-muted'
          }`}
        >
          {output}
        </pre>
      ) : (
        <div className="px-2.5 py-1.5 text-brand-green-faint">{tool.status === 'done' ? '(no output)' : ''}</div>
      )}
      {failed && <div className="border-t border-red-400/20 px-2.5 py-1 text-[10px] text-red-300">Command failed</div>}
    </div>
  );
}
