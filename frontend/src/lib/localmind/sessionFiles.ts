/**
 * The Files tab's main list: what THIS chat produced.
 *
 * The backend lists a chat's workspace recursively, including the scratch
 * folders the writer stages through. The user wants the files, newest first,
 * with the ones the agent just changed marked — so hide the staging noise,
 * drop folders (the path already shows nesting), and attach the diff stats the
 * app captured for each path.
 */

import type { DiffData, SessionFileEntry } from '@/types';

export interface ChatFileRow {
  path: string;
  name: string;
  /** Folder part of the path inside the chat's workspace, '' at the top level. */
  dir: string;
  size: number;
  modified: string;
  /** Present when the app captured a diff for this file this session. */
  change: { additions: number; deletions: number } | null;
}

function isHidden(relPath: string): boolean {
  return relPath.split('/').some((seg) => seg.startsWith('.'));
}

function diffCounts(diff: DiffData | undefined): { additions: number; deletions: number } | null {
  if (!diff) return null;
  let additions = 0;
  let deletions = 0;
  for (const h of diff.hunks ?? []) {
    for (const l of h.lines) {
      if (l.type === 'added') additions += 1;
      else if (l.type === 'removed') deletions += 1;
    }
  }
  return { additions, deletions };
}

export function buildChatFiles(entries: SessionFileEntry[], diffs?: Record<string, DiffData>): ChatFileRow[] {
  const rows: ChatFileRow[] = [];
  for (const e of entries) {
    if (e.type !== 'file') continue;
    const rel = (e.relPath || e.name).replace(/\\/g, '/');
    if (isHidden(rel)) continue;
    // The edit tool leaves "<name>.bak" beside the file it changed; it is the tool's own
    // backup, not something the user made — hide it while the original is there.
    if (rel.endsWith('.bak') && entries.some((o) => (o.relPath || o.name) === rel.slice(0, -4))) continue;
    const slash = rel.lastIndexOf('/');
    rows.push({
      path: e.path,
      name: e.name || rel.slice(slash + 1),
      dir: slash >= 0 ? rel.slice(0, slash) : '',
      size: e.size,
      modified: e.modified,
      change: diffCounts(diffs?.[e.path]),
    });
  }
  // Newest first; ISO strings compare correctly, and a missing date sorts last.
  return rows.sort((a, b) => (b.modified || '').localeCompare(a.modified || '') || a.path.localeCompare(b.path));
}

/** Case-insensitive match on the file name or its folder. */
export function filterChatFiles(rows: ChatFileRow[], query: string): ChatFileRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((r) => r.name.toLowerCase().includes(q) || r.dir.toLowerCase().includes(q));
}
