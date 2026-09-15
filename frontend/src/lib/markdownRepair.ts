/**
 * Lightweight markdown repair pass.
 *
 * The model sometimes emits malformed markdown: an unclosed `**` (renders
 * literally), a bullet lead-in like `-**` with no space, or a stray `**`
 * with no matching close. react-markdown + remark-gfm render standard
 * markdown correctly — the problem is the INPUT. This pass applies the
 * smallest safe corrections before rendering:
 *
 *   1. Protects fenced code blocks and inline code spans (never touch them).
 *   2. Closes unclosed emphasis (`**`, `*`, `__`, `_`) at end-of-line /
 *      end-of-input — a lone opener would otherwise render literally.
 *   3. Normalizes broken bullet lead-ins (`-**` → `- **`, `*  ` → `* `).
 *
 * Everything else passes through untouched. The pass is deliberately
 * conservative: it only fixes the shapes the free-tier model actually
 * produces, and it never touches content inside code fences.
 */

const FENCE_RE = /```[\s\S]*?```|`[^`\n]*`/g;
const BULLET_RE = /^(\s*)([*+-])(\s*)(\S.*)$/gm;

// Code-span placeholder delimiters: a Private-Use-Area char that model
// output practically never contains (and that is not a control char, so
// eslint's no-control-regex stays satisfied).
const CODE_OPEN = '\uE000';
const CODE_RESTORE_RE = /\uE000CODE(\d+)\uE000/g;

export interface MarkdownRepairOptions {
  /** Close unclosed emphasis at end-of-line/input (default true). */
  closeEmphasis?: boolean;
  /** Normalize broken bullet lead-ins (default true). */
  normalizeBullets?: boolean;
}

/**
 * Repair a model-generated markdown string in place (returns a new string).
 * Code fences and inline code are extracted first and re-inserted verbatim,
 * so repairs never touch code content.
 */
export function repairMarkdown(
  text: string,
  options: MarkdownRepairOptions = {}
): string {
  if (!text) return text;
  const closeEmphasis = options.closeEmphasis ?? true;
  const normalizeBullets = options.normalizeBullets ?? true;

  // ── 1. Protect code spans ────────────────────────────────────────────
  // Extract code blocks + inline code, replacing with placeholders that
  // cannot collide with real content (a PUA char — never emitted by the
  // model — plus an index). PUA is used instead of a NUL/control char so
  // the regexes stay lint-clean (no-control-regex).
  const protectedSpans: string[] = [];
  const fenced = text.replace(FENCE_RE, (m) => {
    protectedSpans.push(m);
    return `${CODE_OPEN}CODE${protectedSpans.length - 1}${CODE_OPEN}`;
  });

  let repaired = fenced;

  // ── 2. Close unclosed emphasis ────────────────────────────────────────
  // Per line (and the final line at end-of-input), if an emphasis opener
  // has no matching closer LATER on the same line, append the closer.
  // Handles **, __, * and _ (only when the opener is a real emphasis, not
  // a lone asterisk used as a bullet — bullets are normalized in step 3).
  if (closeEmphasis) {
    repaired = repaired.split('\n').map(closeLineEmphasis).join('\n');
  }

  // ── 3. Normalize broken bullet lead-ins ───────────────────────────────
  if (normalizeBullets) {
    repaired = repaired.replace(
      BULLET_RE,
      (_m, indent: string, marker: string, spaces: string, rest: string) => {
        // A line starting with `**bold**` is EMPHASIS at line start, not a
        // `*` bullet followed by text — leave it alone.
        if (marker === '*' && rest.startsWith('*')) {
          return _m;
        }
        // "-**bold**" / "-*italic*" → "- **bold**" / "- *italic*"
        if (spaces === '' && (rest.startsWith('**') || rest.startsWith('*'))) {
          return `${indent}${marker} ${rest}`;
        }
        // Normalize 2+ spaces after the marker to exactly one.
        if (spaces.length > 1) {
          return `${indent}${marker} ${rest}`;
        }
        return _m;
      }
    );
  }

  // ── 4. Restore code spans ────────────────────────────────────────────
  return repaired.replace(CODE_RESTORE_RE, (_m, idx: string) => {
    return protectedSpans[Number(idx)] ?? '';
  });
}

/**
 * Close an unclosed emphasis opener on a single line.
 * A line like `Remember **to check` → `Remember **to check**`.
 * A line like `**bold text` (opener at start) → `**bold text**`.
 * Lines with a balanced pair, or with NO opener at all, pass through.
 */
function closeLineEmphasis(line: string): string {
  if (!line.includes('*') && !line.includes('_')) return line;

  // An hr (`***`, `___`, `* * *`) is valid markdown — never a dangling
  // emphasis opener. Leave lines that are only emphasis/space chars alone.
  if (/^[*_\s]+$/.test(line.trim())) return line;

  for (const marker of ['**', '__', '*', '_'] as const) {
    // A real opener: the marker appears and, if it's a single *, it's not
    // part of a bullet (`* item`) and not inside a word (`foo*bar`).
    const openerIdx = findEmphasisOpener(line, marker);
    if (openerIdx === -1) continue;

    // Does a matching closer appear after the opener on this line?
    const after = line.slice(openerIdx + marker.length);
    if (findEmphasisCloser(after, marker) !== -1) continue; // balanced

    // Unclosed → append the closer at end of line (before trailing spaces).
    const trailing = line.match(/\s*$/)?.[0] ?? '';
    const body = line.slice(0, line.length - trailing.length);
    return body + marker + trailing;
  }
  return line;
}

/**
 * Find the first emphasis OPENER for a marker on a line, or -1.
 * Rules:
 *  - `**`/`__`: left-flanking (start or preceded by non-word / space).
 *  - `*`/`_`: left-flanking AND not a bullet marker at line start, and not
 *    surrounded by word characters (intraword `foo*bar` is math/typo, skip).
 */
function findEmphasisOpener(line: string, marker: string): number {
  let idx = line.indexOf(marker);
  while (idx !== -1) {
    const before = idx === 0 ? '' : line[idx - 1];
    const after = line.slice(idx + marker.length);
    const next = after.charAt(0);

    // A single marker that is really part of a double marker (`*` inside
    // `**`, `_` inside `__`) belongs to the double-marker pass — skip it
    // here so `**bold**` isn't seen as lone `*` openers.
    if (marker === '*' || marker === '_') {
      const prevChar = before;
      const nextChar = after.charAt(0);
      if (nextChar === marker || prevChar === marker) {
        idx = line.indexOf(marker, idx + 1);
        continue;
      }
    }

    // Left-flanking: `**`/`__` intraword (foo**bar, a__b) is literal text
    // in CommonMark, not emphasis — never treat it as an opener.
    if (marker === '**' || marker === '__') {
      const prevIsWord = before !== '' && /\w/.test(before);
      const nextIsWord = next !== '' && /\w/.test(next);
      if (prevIsWord && nextIsWord) {
        idx = line.indexOf(marker, idx + 1);
        continue;
      }
    }

    // Single-asterisk bullets (`* item`) are list markers, not emphasis.
    if (marker === '*' || marker === '_') {
      const lineLead = line.slice(0, idx).trim();
      if (lineLead === '' && (next === ' ' || next === '\t' || next === '')) {
        idx = line.indexOf(marker, idx + 1);
        continue;
      }
      // Intraword: foo*bar or foo_bar — not emphasis.
      const prevIsWord = before !== '' && /\w/.test(before);
      const nextIsWord = next !== '' && /\w/.test(next);
      if (prevIsWord && nextIsWord) {
        idx = line.indexOf(marker, idx + 1);
        continue;
      }
      // Trailing marker at end of a word (`my_file`, `foo*`) is a truncated
      // filename/typo, not an emphasis opener — skip it.
      if (next === '' && prevIsWord) {
        idx = line.indexOf(marker, idx + 1);
        continue;
      }
    }
    return idx;
  }
  return -1;
}

/** Find the first emphasis CLOSER for a marker, or -1 (right-flanking). */
function findEmphasisCloser(after: string, marker: string): number {
  let idx = after.indexOf(marker);
  while (idx !== -1) {
    const prev = idx === 0 ? '' : after[idx - 1];
    const before = after.slice(0, idx);
    const prevChar = before.charAt(before.length - 1);
    // Right-flanking: preceded by a non-space character.
    if (prevChar !== '' && !/\s/.test(prevChar) && prev !== '\\') {
      return idx;
    }
    idx = after.indexOf(marker, idx + 1);
  }
  return -1;
}
