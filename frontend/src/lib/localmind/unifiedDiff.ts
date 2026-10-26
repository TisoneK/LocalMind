// ── Unified-diff parsing (pure) — extracted from DiffBlock so the
//    component file exports only its component ──────────────────────────

export type DiffLineType = 'context' | 'added' | 'removed' | 'hunk_header';

export interface DiffLine {
  type: DiffLineType;
  /** Line number in the original file (undefined for added lines) */
  oldLine?: number;
  /** Line number in the new file (undefined for removed lines) */
  newLine?: number;
  /** The text content of the line */
  content: string;
}

export interface DiffHunk {
  /** File path being edited */
  filePath: string;
  /** Starting line in original file */
  oldStart: number;
  /** Number of lines in original */
  oldLines: number;
  /** Starting line in new file */
  newStart: number;
  /** Number of lines in new file */
  newLines: number;
  /** The individual diff lines */
  lines: DiffLine[];
}

// ── Parse unified diff text into structured hunks ────────────────────────
export function parseUnifiedDiff(diffText: string, filePath?: string): DiffHunk[] {
  const lines = diffText.split('\n');
  const hunks: DiffHunk[] = [];
  let currentHunk: DiffHunk | null = null;
  let oldLine = 0;
  let newLine = 0;

  for (const line of lines) {
    // Hunk header: @@ -oldStart,oldLines +newStart,newLines @@
    const hunkMatch = line.match(/^@@@? -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
    if (hunkMatch) {
      if (currentHunk) hunks.push(currentHunk);
      currentHunk = {
        filePath: filePath || '',
        oldStart: parseInt(hunkMatch[1]),
        oldLines: parseInt(hunkMatch[2] || '1'),
        newStart: parseInt(hunkMatch[3]),
        newLines: parseInt(hunkMatch[4] || '1'),
        lines: [],
      };
      oldLine = currentHunk.oldStart;
      newLine = currentHunk.newStart;
      currentHunk.lines.push({
        type: 'hunk_header',
        content: line,
        oldLine: currentHunk.oldStart,
        newLine: currentHunk.newStart,
      });
      continue;
    }

    if (!currentHunk) {
      // Skip diff header lines (---, +++, etc.)
      continue;
    }

    if (line.startsWith('+')) {
      currentHunk.lines.push({
        type: 'added',
        content: line.slice(1),
        newLine: newLine++,
      });
    } else if (line.startsWith('-')) {
      currentHunk.lines.push({
        type: 'removed',
        content: line.slice(1),
        oldLine: oldLine++,
      });
    } else if (line.startsWith(' ')) {
      currentHunk.lines.push({
        type: 'context',
        content: line.slice(1),
        oldLine: oldLine++,
        newLine: newLine++,
      });
    } else if (line.startsWith('\\')) {
      // "No newline at end of file" — skip
    }
  }

  if (currentHunk) hunks.push(currentHunk);
  return hunks;
}
