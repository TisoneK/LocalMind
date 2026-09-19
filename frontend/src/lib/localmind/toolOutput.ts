/**
 * Tool output, parsed for display.
 *
 * Tools hand back plain text: a web search is "Search results via **DuckDuckGo** (8
 * results):" followed by a numbered list, a fetch is "Source: <url>" followed by the page
 * body (often raw JSON), and the backend cuts long bodies with inline markers such as
 * "… [8069 chars truncated] …". Dumping that as-is makes a step look like a wall of noise.
 * This turns it into something a view can present: real result entries, a source line, and
 * a count of what was left out instead of markers in the middle of the text.
 */

import type { ToolCall } from '@/types';

export interface SearchResult {
  title: string;
  url: string;
  host: string;
  snippet: string;
}

export type ToolOutputView =
  | { kind: 'search'; provider: string; results: SearchResult[]; hidden: number }
  | { kind: 'fetch'; source: string; body: string; isJson: boolean; hidden: number }
  | { kind: 'text'; body: string; hidden: number };

// "… [8069 chars truncated] …" (with or without the ellipses), possibly with spaces around.
const CHAR_MARKER = /\s*(?:…|\.\.\.)?\s*\[(\d[\d,]*) chars? truncated\]\s*(?:…|\.\.\.)?\s*/gi;
// "[... content truncated]" — the tail marker, which carries no count.
const TAIL_MARKER = /\s*\[\.\.\. ?content truncated\]\s*/gi;

/** Remove the backend's truncation markers; report how many characters they stood for. */
export function stripTruncation(text: string): { text: string; hidden: number; cut: boolean } {
  let hidden = 0;
  let cut = false;
  let out = text.replace(CHAR_MARKER, (_m, n: string) => {
    hidden += Number(n.replace(/,/g, ''));
    cut = true;
    return '\n… \n';
  });
  out = out.replace(TAIL_MARKER, () => {
    cut = true;
    return '\n';
  });
  return { text: out.trim(), hidden, cut };
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

const SEARCH_HEADER = /^Search results via \*{0,2}([^*\n(]+?)\*{0,2}\s*\((\d+) results?\):/i;
const SEARCH_ITEM = /(?:^|\n)\s*\d+\.\s+\*\*(.+?)\*\*[ \t]*\n\s*(https?:\/\/\S+)[ \t]*\n?([\s\S]*?)(?=\n\s*\d+\.\s+\*\*|$)/g;

function parseSearch(text: string): SearchResult[] {
  const results: SearchResult[] = [];
  for (const m of text.matchAll(SEARCH_ITEM)) {
    const url = m[2].trim();
    results.push({
      title: m[1].trim(),
      url,
      host: hostOf(url),
      snippet: m[3].replace(/\s+/g, ' ').trim(),
    });
  }
  return results;
}

export function parseToolOutput(tool: Pick<ToolCall, 'name' | 'output'>): ToolOutputView {
  const { text, hidden } = stripTruncation(tool.output || '');

  const header = SEARCH_HEADER.exec(text);
  if (header) {
    const results = parseSearch(text);
    if (results.length > 0) return { kind: 'search', provider: header[1].trim(), results, hidden };
  }

  const source = /^Source:\s*(\S+)\s*\n+/i.exec(text);
  if (source) {
    const body = text.slice(source[0].length).trim();
    return { kind: 'fetch', source: source[1], body, isJson: /^[{[]/.test(body), hidden };
  }

  return { kind: 'text', body: text, hidden };
}

/** "12,405 characters" — the size of what a truncation left out, for a footer note. */
export function formatHidden(n: number): string {
  return `${n.toLocaleString('en-US')} character${n === 1 ? '' : 's'}`;
}
