/**
 * FilesPanel — the Files tab.
 *
 * Leads with what matters: the files THIS chat produced, newest first, with the
 * ones the agent changed marked and every row actually usable (click to preview,
 * hover for download / copy path / open / delete). The rest of the machine is one
 * click away under "Browse all files" instead of being the first thing you see.
 */

import { useEffect, useState } from 'react';
import { ChevronRight, Copy, Download, FolderOpen, Loader2, MonitorUp, RefreshCw, Search, Trash2, X } from 'lucide-react';
import type { DiffData, FileNode, SessionFileEntry } from '@/types';
import { localmindClient } from '@/lib/localmind/client';
import { buildChatFiles, filterChatFiles, type ChatFileRow } from '@/lib/localmind/sessionFiles';
import { formatModified, formatSize } from '@/lib/localmind/fileFormat';
import { FileIcon } from './FileIcon';
import { FileExplorer } from './FileExplorer';

interface FilesPanelProps {
  /** The open chat; null before one is started. */
  sessionId: string | null;
  /** Roots for the "Browse all files" tree. */
  files: FileNode[];
  fileDiffs?: Record<string, DiffData>;
  /** Open a file in the preview dialog. */
  onOpen: (path: string) => void;
  onFilesChanged?: () => void;
  /** While the agent is working the list refreshes on its own. */
  isStreaming?: boolean;
}

const LIVE_REFRESH_MS = 3000;

function ChatFileItem({
  row,
  onOpen,
  onDelete,
}: {
  row: ChatFileRow;
  onOpen: (path: string) => void;
  onDelete: (path: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  const act = (e: React.SyntheticEvent, fn: () => void) => {
    e.stopPropagation();
    fn();
  };
  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={() => onOpen(row.path)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onOpen(row.path);
        }}
        title={row.path}
        data-testid={`chat-file-${row.name}`}
        className="group flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-brand-border/50"
      >
        <FileIcon name={row.name} className="h-4 w-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[11.5px] text-brand-green-soft group-hover:text-brand-green">{row.name}</div>
          <div className="truncate text-[9.5px] text-brand-green-faint">
            {[row.dir, formatSize(row.size), formatModified(row.modified)].filter(Boolean).join(' · ')}
          </div>
        </div>
        {row.change && (
          <span className="shrink-0 font-mono text-[9.5px]" title="Changed by the agent this session">
            <span className="text-brand-green">+{row.change.additions}</span>{' '}
            <span className="text-red-400">−{row.change.deletions}</span>
          </span>
        )}
        <span className="flex shrink-0 items-center gap-1 text-brand-green-muted opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          <button type="button" title="Open with the default app" aria-label={`Open ${row.name} with the default app`}
            onClick={(e) => act(e, () => void localmindClient.openFile(row.path))} className="rounded p-0.5 hover:text-brand-green">
            <MonitorUp className="h-3 w-3" />
          </button>
          <button type="button" title={copied ? 'Copied' : 'Copy path'} aria-label={`Copy path of ${row.name}`}
            onClick={(e) => act(e, () => {
              void navigator.clipboard?.writeText(row.path).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1200);
              });
            })} className="rounded p-0.5 hover:text-brand-green">
            <Copy className="h-3 w-3" />
          </button>
          <button type="button" title="Download" aria-label={`Download ${row.name}`}
            onClick={(e) => act(e, () => localmindClient.downloadFile(row.path))} className="rounded p-0.5 hover:text-brand-green">
            <Download className="h-3 w-3" />
          </button>
          <button type="button" title="Delete" aria-label={`Delete ${row.name}`}
            onClick={(e) => act(e, () => onDelete(row.path))} className="rounded p-0.5 hover:text-red-400">
            <Trash2 className="h-3 w-3" />
          </button>
        </span>
      </div>
    </li>
  );
}

export function FilesPanel({ sessionId, files, fileDiffs, onOpen, onFilesChanged, isStreaming }: FilesPanelProps) {
  const [entries, setEntries] = useState<SessionFileEntry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const [browse, setBrowse] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // Load on mount (the panel is keyed by chat, so a new chat starts fresh), on manual
  // refresh, and when a turn ends; while the agent works, poll so files appear as written.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    const run = () =>
      localmindClient
        .getSessionFiles(sessionId)
        .then((list) => {
          if (cancelled) return;
          setEntries(list);
          setFailed(false);
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    void run();
    if (!isStreaming) return () => { cancelled = true; };
    const id = setInterval(() => void run(), LIVE_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [sessionId, tick, isStreaming]);

  const rows = filterChatFiles(buildChatFiles(entries ?? [], fileDiffs), query);
  const total = buildChatFiles(entries ?? [], fileDiffs).length;
  const flash = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(null), 2000);
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    const path = confirmDelete;
    setConfirmDelete(null);
    try {
      await localmindClient.deleteFile(path);
      flash('Deleted');
      onFilesChanged?.();
      setTick((t) => t + 1);
    } catch {
      flash('Delete failed');
    }
  };

  return (
    <div className="flex min-h-0 flex-col" data-testid="files-panel">
      <div className="flex items-center gap-1 px-2 pt-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-brand-green-muted" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter this chat's files…"
            aria-label="Filter this chat's files"
            className="w-full rounded-md border border-brand-border bg-brand-bg-panel py-1 pl-7 pr-6 text-[11px] text-brand-green-soft placeholder:text-brand-green-faint focus:border-brand-green/40 focus:outline-none"
          />
          {query && (
            <button type="button" onClick={() => setQuery('')} title="Clear filter" aria-label="Clear filter"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-brand-green-muted hover:text-brand-green">
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <button type="button" onClick={() => { setTick((t) => t + 1); onFilesChanged?.(); }} title="Refresh" aria-label="Refresh files"
          className="rounded p-1 text-brand-green-muted transition-colors hover:bg-brand-border/60 hover:text-brand-green">
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      <section className="px-1 pt-2" aria-label="This chat's files">
        <div className="flex items-center justify-between px-2 pb-1 text-[10px] font-medium uppercase tracking-wider text-brand-green-muted">
          <span>This chat</span>
          {sessionId && entries && total > 0 && <span className="normal-case tracking-normal">{total}</span>}
        </div>

        {!sessionId ? (
          <p className="px-2 py-3 text-[11px] text-brand-green-muted">Start a chat and the files it creates will show up here.</p>
        ) : failed ? (
          <p className="px-2 py-3 text-[11px] text-red-300">
            Couldn't load this chat's files.{' '}
            <button type="button" className="underline" onClick={() => setTick((t) => t + 1)}>Try again</button>
          </p>
        ) : entries === null ? (
          <p className="flex items-center gap-2 px-2 py-3 text-[11px] text-brand-green-muted">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Loading files…
          </p>
        ) : total === 0 ? (
          <p className="px-2 py-3 text-[11px] leading-relaxed text-brand-green-muted" data-testid="chat-files-empty">
            No files yet. Anything the agent creates in this chat appears here as it's written.
          </p>
        ) : rows.length === 0 ? (
          <p className="px-2 py-3 text-[11px] text-brand-green-muted">No files match “{query.trim()}”.</p>
        ) : (
          <ul className="space-y-0.5">
            {rows.map((r) => (
              <ChatFileItem key={r.path} row={r} onOpen={onOpen} onDelete={setConfirmDelete} />
            ))}
          </ul>
        )}
      </section>

      {notice && <div className="px-3 py-1 text-[10px] text-brand-green">{notice}</div>}

      {confirmDelete && (
        <div className="mx-2 mt-1 rounded border border-red-400/30 bg-brand-border p-2" data-testid="delete-confirm">
          <div className="mb-2 break-all text-[10px] text-brand-green-soft">
            Delete <span className="font-mono">{confirmDelete.split(/[\\/]/).pop()}</span>? This can't be undone.
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setConfirmDelete(null)} className="rounded px-2 py-1 text-[10px] text-brand-green-muted hover:text-brand-green-soft">
              Cancel
            </button>
            <button type="button" onClick={doDelete} data-testid="delete-confirm-yes"
              className="rounded bg-red-400/10 px-2 py-1 text-[10px] text-red-300 hover:bg-red-400/20">
              Delete
            </button>
          </div>
        </div>
      )}

      <div className="mt-2 border-t border-brand-border/60">
        <button
          type="button"
          onClick={() => setBrowse((b) => !b)}
          aria-expanded={browse}
          className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[10.5px] text-brand-green-muted hover:text-brand-green"
        >
          <ChevronRight className={`h-3 w-3 transition-transform ${browse ? 'rotate-90' : ''}`} aria-hidden />
          <FolderOpen className="h-3 w-3" aria-hidden />
          Browse all files
        </button>
        {browse && (
          <div className="px-2 pb-2" data-testid="browse-all">
            {files.length === 0 ? (
              <p className="px-1 py-2 text-[10.5px] text-brand-green-muted">Nothing to browse yet.</p>
            ) : (
              <FileExplorer files={files} onFileOpen={onOpen} onFilesChanged={onFilesChanged} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
