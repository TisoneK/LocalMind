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
    ? 'bg-[#1a3a1a]/60'
    : line.type === 'removed'
      ? 'bg-[#3a1a1a]/60'
      : line.type === 'hunk_header'
        ? 'bg-[#111a11] text-[#5a7a5a]'
        : '';

  const textClass = line.type === 'added'
    ? 'text-[#7ddf7d]'
    : line.type === 'removed'
      ? 'text-[#df7d7d]'
      : line.type === 'hunk_header'
        ? 'text-[#5a7a5a]'
        : 'text-[#a8c8a8]';

  const gutterIcon = line.type === 'added'
    ? <Plus className="h-2.5 w-2.5 text-[#39d353]" />
    : line.type === 'removed'
      ? <Minus className="h-2.5 w-2.5 text-[#e05555]" />
      : null;

  if (line.type === 'hunk_header') {
    return (
      <div className={`flex text-[11px] font-mono leading-[1.6] ${bgClass} ${textClass} select-none`}>
        {showLineNumbers && (
          <div className="shrink-0 w-[5.5rem] flex">
            <span className="w-[2.75rem] text-right pr-2 text-[#5a7a5a]">...</span>
            <span className="w-[2.75rem] text-right pr-2 text-[#5a7a5a]">...</span>
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
          <span className="w-[2.75rem] text-right pr-2 text-[#3a5a3a]">
            {line.oldLine ?? ''}
          </span>
          <span className="w-[2.75rem] text-right pr-2 text-[#3a5a3a]">
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
    <div className="rounded-lg overflow-hidden border border-[#1a3a1a] my-2 shadow-lg shadow-black/20 font-mono group">
      {/* ── Header Bar ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#0a120a] border-b border-[#1a3a1a]">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {/* Diff icon */}
          <div className="flex items-center justify-center w-5 h-5 rounded shrink-0 bg-[#39d353]/10 border border-[#39d353]/20">
            <GitPullRequest className="h-3 w-3 text-[#39d353]" />
          </div>

          {/* File path + line range */}
          <div className="flex items-center gap-1.5 min-w-0 truncate">
            <span className="text-[12px] text-[#d4e8d4] font-medium truncate">
              {fileName}
            </span>
            {lineRange && (
              <span className="text-[10px] text-[#5a7a5a] shrink-0">
                · {lineRange}
              </span>
            )}
          </div>

          {/* Language badge */}
          {langLabel && (
            <span className="text-[10px] px-1.5 py-[1px] rounded font-medium shrink-0 bg-[#39d353]/10 text-[#39d353] border border-[#39d353]/20">
              {langLabel}
            </span>
          )}

          {/* Separator */}
          <div className="w-px h-3 bg-[#1a2a1a] shrink-0" />

          {/* Diff stats */}
          <span className="text-[10px] shrink-0 flex items-center gap-1.5">
            <span className="text-[#39d353]">+{stats.additions}</span>
            <span className="text-[#e05555]">-{stats.deletions}</span>
          </span>

          {/* Streaming indicator */}
          {isStreaming && (
            <>
              <div className="w-px h-3 bg-[#1a2a1a] shrink-0" />
              <span className="inline-block w-1.5 h-3 bg-[#39d353] animate-pulse rounded-[1px]" />
            </>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0 ml-2">
          {/* Expand/collapse toggle */}
          <button
            onClick={() => setExpanded(prev => !prev)}
            className="flex items-center justify-center w-6 h-6 rounded hover:bg-[#1a2a1a] text-[#5a7a5a] hover:text-[#d4e8d4] transition-colors"
            title={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? <Shrink className="h-3.5 w-3.5" /> : <Expand className="h-3.5 w-3.5" />}
          </button>

          {/* Copy button */}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] hover:bg-[#1a2a1a] transition-colors"
            title="Copy changed lines"
          >
            {copied ? (
              <><Check className="h-3 w-3 text-[#39d353]" /><span className="text-[#39d353]">Copied!</span></>
            ) : (
              <><Copy className="h-3 w-3 text-[#5a7a5a] group-hover:text-[#8ab08a]" /><span className="text-[#5a7a5a] group-hover:text-[#8ab08a]">Copy</span></>
            )}
          </button>
        </div>
      </div>

      {/* ── Diff Content ───────────────────────────────────────────────── */}
      <div
        className={`bg-[#080d08] overflow-hidden transition-all duration-200 ${
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
                  background: 'linear-gradient(to bottom, transparent, #080d08)',
                }}
              />
              <div className="flex items-center justify-center py-2 relative z-10">
                <button
                  onClick={() => setExpanded(true)}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#111a11] border border-[#1a3a1a] text-[11px] text-[#39d353] hover:bg-[#1a2a1a] hover:text-[#5af75a] transition-colors"
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
        <div className="flex items-center justify-between px-3 py-1.5 bg-[#0a120a] border-t border-[#1a3a1a]">
          <span className="text-[10px] text-[#8ab08a]">
            Apply these changes?
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleAccept}
              className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded border border-[#39d353]/30 bg-[#39d353]/10 text-[#39d353] hover:bg-[#39d353]/20 transition-colors"
            >
              <Check className="h-3 w-3" />
              Accept
            </button>
            <button
              onClick={handleReject}
              className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded border border-[#e05555]/30 bg-[#e05555]/10 text-[#e05555] hover:bg-[#e05555]/20 transition-colors"
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
            ? 'bg-[#39d353]/5 border-[#39d353]/20 text-[#39d353]'
            : 'bg-[#e05555]/5 border-[#e05555]/20 text-[#e05555]'
        }`}>
          {actionStatus === 'accepted' ? '✓ Changes accepted' : '✕ Changes rejected'}
        </div>
      )}

      {/* ── Footer Stats ───────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-1 bg-[#0a120a] border-t border-[#1a3a1a] text-[10px] text-[#5a7a5a]">
        <div className="flex items-center gap-3">
          <span>{langLabel || 'text'}</span>
          <span>UTF-8</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[#39d353]">+{stats.additions}</span>
          <span className="text-[#e05555]">-{stats.deletions}</span>
          <span>{stats.additions + stats.deletions} changed</span>
        </div>
      </div>
    </div>
  );
}

export default DiffBlock;
