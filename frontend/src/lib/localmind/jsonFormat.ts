/**
 * JSON for display: pretty-printed when it parses, and split into coloured tokens either way.
 *
 * Tool results are often JSON, and often cut off by the backend, so a strict parse can fail.
 * A cut-off document is still worth highlighting, so tokenising works on any text.
 */

export type JsonTokenKind = 'key' | 'string' | 'number' | 'literal' | 'punct';

export interface JsonToken {
  kind: JsonTokenKind;
  text: string;
}

/** Does this text look like a JSON document (object or array)? */
export function looksLikeJson(text: string): boolean {
  const t = text.trimStart();
  return t.startsWith('{') || t.startsWith('[');
}

/** Re-indent valid JSON with two spaces; return anything else untouched. */
export function prettyJson(text: string): { text: string; valid: boolean } {
  try {
    return { text: JSON.stringify(JSON.parse(text), null, 2), valid: true };
  } catch {
    return { text, valid: false };
  }
}

// A string (optionally followed by ":" → it is a key), a number, or true/false/null.
const TOKEN = /("(?:\\.|[^"\\\n])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b/g;

/** Split text into plain runs and coloured tokens, preserving every character. */
export function tokenizeJson(text: string): JsonToken[] {
  const out: JsonToken[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    const start = m.index ?? 0;
    if (start > last) out.push({ kind: 'punct', text: text.slice(last, start) });
    if (m[1] !== undefined) {
      if (m[2] !== undefined) {
        out.push({ kind: 'key', text: m[1] });
        out.push({ kind: 'punct', text: m[2] });
      } else {
        out.push({ kind: 'string', text: m[1] });
      }
    } else if (m[3] !== undefined) {
      out.push({ kind: 'number', text: m[3] });
    } else {
      out.push({ kind: 'literal', text: m[4] });
    }
    last = start + m[0].length;
  }
  if (last < text.length) out.push({ kind: 'punct', text: text.slice(last) });
  return out;
}
