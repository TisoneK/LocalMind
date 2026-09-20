/**
 * ToolOutput — a tool step's result, presented instead of dumped.
 *
 * A web search becomes a short list of results, a fetch shows where it came from with the
 * body collapsed to a preview, and everything else is a capped, expandable text block.
 * Anything the backend cut is reported once, as a note, not as markers inside the text.
 */

import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import type { ToolCall } from '@/types';
import { formatHidden, parseToolOutput, type ToolOutputView } from '@/lib/localmind/toolOutput';
import { cleanToolFailure } from '@/lib/localmind/errorText';
import { looksLikeJson, prettyJson, tokenizeJson, type JsonTokenKind } from '@/lib/localmind/jsonFormat';

const PREVIEW_LINES = 8;
const VISIBLE_RESULTS = 4;

function HiddenNote({ hidden }: { hidden: number }) {
  if (hidden <= 0) return null;
  return <p className="mt-1 text-[10px] text-brand-green-faint">{formatHidden(hidden)} of the original were not kept.</p>;
}

const TOKEN_CLASS: Record<JsonTokenKind, string> = {
  key: 'text-brand-blue',
  string: 'text-brand-green',
  number: 'text-brand-amber',
  literal: 'text-brand-purple',
  punct: '',
};

/** JSON as coloured code: keys, strings, numbers and true/false/null each get their own colour. */
function HighlightedJson({ text }: { text: string }) {
  return (
    <>
      {tokenizeJson(text).map((t, i) =>
        t.kind === 'punct' ? t.text : (
          <span key={i} className={TOKEN_CLASS[t.kind]}>
            {t.text}
          </span>
        ),
      )}
    </>
  );
}

/** Monospace text limited to a few lines, with a toggle for the rest. JSON is re-indented and coloured. */
function Preview({ text, json }: { text: string; json?: boolean }) {
  const [all, setAll] = useState(false);
  const prepared = json ? prettyJson(text) : { text, valid: false };
  const lines = prepared.text.split('\n');
  const long = lines.length > PREVIEW_LINES;
  const shown = all || !long ? prepared.text : lines.slice(0, PREVIEW_LINES).join('\n');
  if (!text) return null;
  return (
    <div>
      {json && (
        <div className="mb-0.5 flex items-center gap-1.5 text-[9.5px] uppercase tracking-wider text-brand-green-faint">
          <span>JSON</span>
          {!prepared.valid && <span className="normal-case tracking-normal">· incomplete</span>}
        </div>
      )}
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-black/25 px-2 py-1.5 font-mono text-[10.5px] leading-relaxed text-brand-green-soft">
        {json ? <HighlightedJson text={shown} /> : shown}
      </pre>
      {long && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-0.5 text-[10px] text-brand-blue hover:text-brand-blue-bright">
          {all ? 'Show less' : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

function SearchResults({ view }: { view: Extract<ToolOutputView, { kind: 'search' }> }) {
  const [all, setAll] = useState(false);
  const shown = all ? view.results : view.results.slice(0, VISIBLE_RESULTS);
  return (
    <div data-testid="search-results">
      <div className="mb-1 text-[10px] text-brand-green-muted">
        {view.results.length} results · {view.provider}
      </div>
      <ul className="space-y-1.5">
        {shown.map((r) => (
          <li key={r.url} className="min-w-0">
            <a
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex items-start gap-1 text-[11.5px] text-brand-blue hover:text-brand-blue-bright"
              title={r.url}
            >
              <span className="min-w-0 flex-1 break-words">{r.title}</span>
              <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 opacity-0 group-hover:opacity-100" aria-hidden />
            </a>
            <div className="text-[10px] text-brand-green-faint">{r.host}</div>
            {r.snippet && <p className="line-clamp-2 text-[10.5px] leading-snug text-brand-green-muted">{r.snippet}</p>}
          </li>
        ))}
      </ul>
      {view.results.length > VISIBLE_RESULTS && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-1 text-[10px] text-brand-blue hover:text-brand-blue-bright">
          {all ? 'Show fewer' : `Show all ${view.results.length} results`}
        </button>
      )}
      <HiddenNote hidden={view.hidden} />
    </div>
  );
}

export function ToolOutput({ tool }: { tool: ToolCall }) {
  const view = parseToolOutput(tool);

  if (view.kind === 'search') return <SearchResults view={view} />;

  if (view.kind === 'fetch') {
    return (
      <div data-testid="fetch-output">
        <a
          href={view.source}
          target="_blank"
          rel="noopener noreferrer"
          className="mb-1 flex items-center gap-1 break-all text-[10.5px] text-brand-blue hover:text-brand-blue-bright"
          title={view.source}
        >
          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
          {view.source}
        </a>
        <Preview text={view.body} json={view.isJson} />
        <HiddenNote hidden={view.hidden} />
      </div>
    );
  }

  return (
    <div>
      <Preview text={cleanToolFailure(view.body)} json={looksLikeJson(view.body)} />
      <HiddenNote hidden={view.hidden} />
    </div>
  );
}
