'use client';

import React, { useState, useCallback, useMemo } from 'react';
import {
  Copy,
  Check,
  Expand,
  Shrink,
  Plus,
  Minus,
  GitPullRequest,
} from 'lucide-react';

// ── Diff line types ──────────────────────────────────────────────────────
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

export interface DiffBlockProps {
  /** Array of diff hunks to display */
  hunks: DiffHunk[];
  /** Language for syntax context (optional) */
  language?: string;
  /** Whether to show inline accept/reject actions */
  showActions?: boolean;
  /** Callback when user accepts the diff */
  onAccept?: () => void;
  /** Callback when user rejects the diff */
  onReject?: () => void;
  /** Whether the diff is currently being streamed */
  isStreaming?: boolean;
}

// ── Language labels ──────────────────────────────────────────────────────
const LANGUAGE_LABELS: Record<string, string> = {
  js: 'JavaScript', javascript: 'JavaScript', ts: 'TypeScript', typescript: 'TypeScript',
  py: 'Python', python: 'Python', html: 'HTML', css: 'CSS', json: 'JSON',
  bash: 'Shell', sh: 'Shell', shell: 'Shell', sql: 'SQL', go: 'Go', rust: 'Rust',
  java: 'Java', yaml: 'YAML', yml: 'YAML', markdown: 'Markdown', md: 'Markdown',
};

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

// ── Diff stats ──────────────────────────────────────────────────────────
function getDiffStats(hunks: DiffHunk[]) {
  let additions = 0;
  let deletions = 0;
  for (const hunk of hunks) {
    for (const line of hunk.lines) {
      if (line.type === 'added') additions++;
      if (line.type === 'removed') deletions++;
    }
  }
  return { additions, deletions };
}

// ── Single diff line component ──────────────────────────────────────────
function DiffLineRow({ line, showLineNumbers }: { line: DiffLine; showLineNumbers: boolean }) {
  const bgClass = line.type === 'added'
    ? 'bg-brand-gh-green-border/60'
    : line.type === 'removed'
      ? 'bg-brand-gh-red-bg/60'
      : line.type === 'hunk_header'
        ? 'bg-brand-bg-rail text-brand-green-faint'
        : '';

  const textClass = line.type === 'added'
    ? 'text-brand-green-inline'
    : line.type === 'removed'
      ? 'text-brand-gh-red-soft'
      : line.type === 'hunk_header'
        ? 'text-brand-green-faint'
        : 'text-brand-gh-green-soft';

  const gutterIcon = line.type === 'added'
    ? <Plus className="h-2.5 w-2.5 text-brand-green" />
    : line.type === 'removed'
      ? <Minus className="h-2.5 w-2.5 text-brand-red" />
      : null;

  if (line.type === 'hunk_header') {
    return (
      <div className={`flex text-[11px] font-mono leading-[1.6] ${bgClass} ${textClass} select-none`}>
        {showLineNumbers && (
          <div className="shrink-0 w-[5.5rem] flex">
            <span className="w-[2.75rem] text-right pr-2 text-brand-green-faint">...</span>
            <span className="w-[2.75rem] text-right pr-2 text-brand-green-faint">...</span>
          </div>
        )}
        <span className="pl-2 opacity-70">{line.content}</span>
      </div>
    );
  }

  return (
    <div className={`flex text-[11px] font-mono leading-[1.6] ${bgClass} group/diffline hover:brightness-110 transition-all`}>
      {showLineNumbers && (
        <div className="shrink-0 w-[5.5rem] flex select-none">
          <span className="w-[2.75rem] text-right pr-2 text-brand-green-line">
            {line.oldLine ?? ''}
          </span>
          <span className="w-[2.75rem] text-right pr-2 text-brand-green-line">
            {line.newLine ?? ''}
          </span>
        </div>
      )}
      <div className="w-5 shrink-0 flex items-center justify-center">
        {gutterIcon}
      </div>
      <span className={`flex-1 pl-1 pr-3 whitespace-pre overflow-x-auto ${textClass}`}>
        {line.content}
      </span>
    </div>
  );
}

// ── Main DiffBlock component ────────────────────────────────────────────
export function DiffBlock({
  hunks,
  language = '',
  showActions = true,
  onAccept,
  onReject,
  isStreaming = false,
}: DiffBlockProps) {
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [actionStatus, setActionStatus] = useState<'pending' | 'accepted' | 'rejected'>('pending');

  const stats = useMemo(() => getDiffStats(hunks), [hunks]);
  const langLabel = LANGUAGE_LABELS[language.toLowerCase()] || language.toUpperCase() || '';

  // Combine all hunk lines for display
  const allLines = useMemo(() => {
    const lines: DiffLine[] = [];
    for (const hunk of hunks) {
      lines.push(...hunk.lines);
    }
    return lines;
  }, [hunks]);

  // Get primary file path from first hunk
  const filePath = hunks[0]?.filePath || '';
  const fileName = filePath.split('/').pop() || '';

  // Line range for header
  const lineRange = useMemo(() => {
    if (hunks.length === 0) return '';
    const first = hunks[0].newStart;
    const last = hunks[hunks.length - 1];
    const end = last.newStart + last.newLines - 1;
    return first === end ? `line ${first}` : `lines ${first}–${end}`;
  }, [hunks]);

  const handleCopy = useCallback(() => {
    const text = allLines
      .filter(l => l.type !== 'hunk_header')
      .map(l => l.content)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [allLines]);

  const handleAccept = useCallback(() => {
    setActionStatus('accepted');
    onAccept?.();
  }, [onAccept]);

  const handleReject = useCallback(() => {
    setActionStatus('rejected');
    onReject?.();
  }, [onReject]);

  // Count visible lines for truncation
  const totalLines = allLines.length;
  const MAX_COLLAPSED = 40;
  const shouldTruncate = !expanded && totalLines > MAX_COLLAPSED;
  const displayLines = shouldTruncate ? allLines.slice(0, MAX_COLLAPSED) : allLines;

  return (
    <div className="rounded-lg overflow-hidden border border-brand-gh-green-border my-2 shadow-lg shadow-black/20 font-mono group">
      {/* ── Header Bar ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-brand-bg-code border-b border-brand-gh-green-border">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {/* Diff icon */}
          <div className="flex items-center justify-center w-5 h-5 rounded shrink-0 bg-brand-green/10 border border-brand-green/20">
            <GitPullRequest className="h-3 w-3 text-brand-green" />
          </div>

          {/* File path + line range */}
          <div className="flex items-center gap-1.5 min-w-0 truncate">
            <span className="text-[12px] text-brand-green-soft font-medium truncate">
              {fileName}
            </span>
            {lineRange && (
              <span className="text-[10px] text-brand-green-faint shrink-0">
                · {lineRange}
              </span>
            )}
          </div>

          {/* Language badge */}
          {langLabel && (
            <span className="text-[10px] px-1.5 py-[1px] rounded font-medium shrink-0 bg-brand-green/10 text-brand-green border border-brand-green/20">
              {langLabel}
            </span>
          )}

          {/* Separator */}
          <div className="w-px h-3 bg-brand-border shrink-0" />

          {/* Diff stats */}
          <span className="text-[10px] shrink-0 flex items-center gap-1.5">
            <span className="text-brand-green">+{stats.additions}</span>
            <span className="text-brand-red">-{stats.deletions}</span>
          </span>

          {/* Streaming indicator */}
          {isStreaming && (
            <>
              <div className="w-px h-3 bg-brand-border shrink-0" />
              <span className="inline-block w-1.5 h-3 bg-brand-green animate-pulse rounded-[1px]" />
            </>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0 ml-2">
          {/* Expand/collapse toggle */}
          <button
            onClick={() => setExpanded(prev => !prev)}
            className="flex items-center justify-center w-6 h-6 rounded hover:bg-brand-border text-brand-green-faint hover:text-brand-green-soft transition-colors"
            title={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? <Shrink className="h-3.5 w-3.5" /> : <Expand className="h-3.5 w-3.5" />}
          </button>

          {/* Copy button */}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] hover:bg-brand-border transition-colors"
            title="Copy changed lines"
          >
            {copied ? (
              <><Check className="h-3 w-3 text-brand-green" /><span className="text-brand-green">Copied!</span></>
            ) : (
              <><Copy className="h-3 w-3 text-brand-green-faint group-hover:text-brand-green-muted" /><span className="text-brand-green-faint group-hover:text-brand-green-muted">Copy</span></>
            )}
          </button>
        </div>
      </div>

      {/* ── Diff Content ───────────────────────────────────────────────── */}
      <div
        className={`bg-brand-bg-dark overflow-hidden transition-all duration-200 ${
          expanded ? 'max-h-[80vh]' : ''
        }`}
      >
        <div
          className="overflow-auto custom-scrollbar-vsc"
          style={{
            maxHeight: expanded ? '80vh' : shouldTruncate ? `${MAX_COLLAPSED * 20 + 16}px` : '600px',
          }}
        >
          <div className="py-1">
            {displayLines.map((line, i) => (
              <DiffLineRow key={`${line.type}-${i}`} line={line} showLineNumbers={true} />
            ))}
          </div>

          {/* Truncation overlay */}
          {shouldTruncate && (
            <div className="relative">
              <div
                className="absolute bottom-0 left-0 right-0 h-12 pointer-events-none"
                style={{
                  background: 'linear-gradient(to bottom, transparent, var(--brand-bg-dark))',
                }}
              />
              <div className="flex items-center justify-center py-2 relative z-10">
                <button
                  onClick={() => setExpanded(true)}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-brand-bg-rail border border-brand-gh-green-border text-[11px] text-brand-green hover:bg-brand-border hover:text-brand-green-bright transition-colors"
                >
                  <Expand className="h-3 w-3" />
                  <span>Show all {totalLines} lines</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Accept/Reject Bar ──────────────────────────────────────────── */}
      {showActions && actionStatus === 'pending' && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-brand-bg-code border-t border-brand-gh-green-border">
          <span className="text-[10px] text-brand-green-muted">
            Apply these changes?
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleAccept}
              className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded border border-brand-green/30 bg-brand-green/10 text-brand-green hover:bg-brand-green/20 transition-colors"
            >
              <Check className="h-3 w-3" />
              Accept
            </button>
            <button
              onClick={handleReject}
              className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded border border-brand-red/30 bg-brand-red/10 text-brand-red hover:bg-brand-red/20 transition-colors"
            >
              <span className="text-sm leading-none">✕</span>
              Reject
            </button>
          </div>
        </div>
      )}

      {/* ── Status Bar (after action) ──────────────────────────────────── */}
      {actionStatus !== 'pending' && (
        <div className={`flex items-center justify-center px-3 py-1.5 border-t text-[11px] ${
          actionStatus === 'accepted'
            ? 'bg-brand-green/5 border-brand-green/20 text-brand-green'
            : 'bg-brand-red/5 border-brand-red/20 text-brand-red'
        }`}>
          {actionStatus === 'accepted' ? '✓ Changes accepted' : '✕ Changes rejected'}
        </div>
      )}

      {/* ── Footer Stats ───────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1 bg-brand-bg-code border-t border-brand-gh-green-border text-[10px] text-brand-green-faint">
        <div className="flex items-center gap-3">
          <span>{langLabel || 'text'}</span>
          <span>UTF-8</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-brand-green">+{stats.additions}</span>
          <span className="text-brand-red">-{stats.deletions}</span>
          <span>{stats.additions + stats.deletions} changed</span>
        </div>
      </div>
    </div>
  );
}

export default DiffBlock;
