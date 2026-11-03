/**
 * Lightweight markdown repair pass.
 *
 * The model sometimes emits malformed markdown: an unclosed `**` (renders
 * literally), a bullet lead-in like `-**` with no space, or a stray `**`
 * with no matching close. CJK-family models (GLM included) also emit TABLES
 * the GFM parser cannot see: full-width punctuation lookalikes (U+FF5C ｜
 * for the pipe, U+FF0D ／ U+2014 — for the delimiter dashes) and header +
 * data rows with no `| --- |` delimiter row at all. Both arrive as plain
 * paragraphs — the owner's 2026-11-03 report ("the UI does not format the
 * output in style eg tables etc its just text"). react-markdown +
 * remark-gfm render standard markdown correctly — the problem is the INPUT.
 * This pass applies the smallest safe corrections before rendering:
 *
 *   1. Protects fenced code blocks and inline code spans (never touch them).
 *   2. Normalizes full-width table lookalikes — ONLY on lines that start
 *      with a pipe (either width) and carry a full-width pipe, so a prose
 *      divider ("上海｜北京") and prose em dashes are untouched.
 *   3. Inserts a missing GFM delimiter row under a detected header row —
 *      ONLY for a run of 3+ uniform pipe rows not preceded by an existing
 *      table row, so data rows of a real table are never re-delimited.
 *   4. Closes unclosed emphasis (`**`, `*`, `__`, `_`) at end-of-line /
 *      end-of-input — a lone opener would otherwise render literally.
 *   5. Normalizes broken bullet lead-ins (`-**` → `- **`, `*  ` → `* `).
 *
 * Everything else passes through untouched. The pass is deliberately
 * conservative: it only fixes the shapes the free-tier model actually
 * produces, and it never touches content inside code fences.
 */

const FENCE_RE = /```[\s\S]*?```|`[^`\n]*`/g;
const BULLET_RE = /^(\s*)([*+-])(\s*)(\S.*)$/gm;

// Full-width punctuation lookalikes CJK-family models emit in tables.
// Pipe: U+FF5C. Dashes: U+FF0D (fullwidth hyphen-minus), U+2014 (em dash),
// U+2013 (en dash) — all three appear as delimiter-row "dashes".
const FULLWIDTH_PIPE = '｜';
const FULLWIDTH_PIPE_RE = /[｜]/g;
const DASH_LOOKALIKE_RE = /[－—–]/g;

// A table row candidate AFTER lookalike normalization: a leading pipe and
// at least one more pipe. Rows without a leading pipe are left alone
// (conservative — prose lines with pipes stay prose).
const PIPE_ROW_RE = /^\s*\|/;

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

  // ── 2. Normalize full-width table lookalikes ──────────────────────────
  // Scoped to lines that start with a pipe (either width) and carry at
  // least one full-width pipe: inside such a row ｜ → | and the dash
  // lookalikes → -, so remark-gfm parses the table. Prose lines keep
  // their punctuation; code spans are already extracted and out of reach.
  repaired = normalizeFullWidthTableRows(repaired);

  // ── 3. Insert a missing GFM delimiter row ────────────────────────────
  repaired = insertMissingDelimiterRow(repaired);

  // ── 4. Close unclosed emphasis ────────────────────────────────────────
  // Per line (and the final line at end-of-input), if an emphasis opener
  // has no matching closer LATER on the same line, append the closer.
  // Handles **, __, * and _ (only when the opener is a real emphasis, not
  // a lone asterisk used as a bullet — bullets are normalized in step 5).
  if (closeEmphasis) {
    repaired = repaired.split('\n').map(closeLineEmphasis).join('\n');
  }

  // ── 5. Normalize broken bullet lead-ins ───────────────────────────────
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

  // ── 6. Restore code spans ────────────────────────────────────────────
  return repaired.replace(CODE_RESTORE_RE, (_m, idx: string) => {
    return protectedSpans[Number(idx)] ?? '';
  });
}

/**
 * Normalize full-width table lookalikes — scoped to unambiguous table rows.
 *
 * A line that STARTS with a pipe (ASCII or full-width) and carries at least
 * one full-width pipe (U+FF5C) is a table row the CJK-family models (GLM
 * included) emit when they reach for their native punctuation — sometimes
 * fully full-width (`｜ Plan ｜ Price ｜`), sometimes MIXED with ASCII outer
 * pipes (`| Plan ｜ Price |` — a single inner ｜). remark-gfm parses ASCII
 * pipes only, so the whole table arrives as plain text. Inside such a row:
 * ｜ → | and the dash lookalikes (U+FF0D/U+2014/U+2013) → -, so BOTH the
 * cells and the `| --- |` delimiter row become parseable GFM. Prose lines
 * (a ｜ divider mid-sentence, em dashes in a sentence) are untouched — they
 * never START with a pipe; code spans are already extracted and out of
 * reach.
 */
function normalizeFullWidthTableRows(text: string): string {
  if (!text.includes(FULLWIDTH_PIPE)) return text;
  return text
    .split('\n')
    .map((line) => {
      const trimmed = line.trimStart();
      const startsAsRow =
        trimmed.startsWith('|') || trimmed.startsWith(FULLWIDTH_PIPE);
      if (startsAsRow && trimmed.includes(FULLWIDTH_PIPE)) {
        return line.replace(FULLWIDTH_PIPE_RE, '|').replace(DASH_LOOKALIKE_RE, '-');
      }
      return line;
    })
    .join('\n');
}

/** A table row candidate: a leading pipe plus at least one more pipe. */
function isPipeRow(line: string): boolean {
  return PIPE_ROW_RE.test(line) && (line.match(/\|/g) || []).length >= 2;
}

/** A GFM delimiter row: pipes + dashes/colons/spaces only, at least one dash. */
function isDelimiterRow(line: string): boolean {
  if (!isPipeRow(line)) return false;
  const body = line.replace(/^\s*\|/, '').replace(/\|\s*$/, '');
  return body.includes('-') && /^[\s:|-]+$/.test(body);
}

/** The delimiter row for a header row: one `---` cell per header cell. */
function delimiterForRow(line: string): string {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  const cells = trimmed.split('|').length;
  return `|${' --- |'.repeat(cells)}`;
}

/**
 * Insert a missing GFM delimiter row under a detected header row.
 *
 * A GFM table needs a `| --- |` delimiter row under the header. Models
 * sometimes emit header + data rows with no delimiter — remark-gfm then
 * renders the whole block as plain paragraphs (the owner's "its just
 * text"). Conservative detection: a run of 3+ consecutive pipe rows with
 * the SAME pipe count, no delimiter row under the header, NOT preceded by a
 * pipe row (the data rows of a real table are never re-delimited — a run
 * after a delimiter belongs to it). The delimiter is inserted after the
 * FIRST row of the run (it becomes the header). Rows without a leading
 * pipe, quoted rows and 2-row runs (header + one data line — too
 * ambiguous) are left alone. Code spans are already extracted (step 1) and
 * out of reach.
 */
function insertMissingDelimiterRow(text: string): string {
  const lines = text.split('\n');
  const out: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (
      isPipeRow(line) &&
      !isDelimiterRow(line) &&
      (i === 0 || !isPipeRow(lines[i - 1])) &&
      runLength(lines, i) >= 3 &&
      runPipeCountsUniform(lines, i) &&
      // The row under the candidate header must not ALREADY be a delimiter:
      // a well-formed table's run (header + delimiter + data rows) looks
      // exactly like the shape above, and only this check tells them apart.
      !isDelimiterRow(lines[i + 1])
    ) {
      out.push(line);
      out.push(delimiterForRow(line));
      continue;
    }
    out.push(line);
  }
  return out.join('\n');
}

/** Consecutive pipe-row count starting at index i. */
function runLength(lines: string[], i: number): number {
  let n = 0;
  while (i + n < lines.length && isPipeRow(lines[i + n])) n++;
  return n;
}

/** Every pipe row of the run starting at i carries the same pipe count. */
function runPipeCountsUniform(lines: string[], i: number): boolean {
  const count = (ln: string) => (ln.match(/\|/g) || []).length;
  const expected = count(lines[i]);
  for (let j = i + 1; j < lines.length && isPipeRow(lines[j]); j++) {
    if (count(lines[j]) !== expected) return false;
  }
  return true;
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
