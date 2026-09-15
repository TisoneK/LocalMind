'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  FolderOpen,
  FileCode,
  FileText,
  FileJson,
  Search,
  X,
  Download,
  Trash2,
  Copy,
  ExternalLink,
  Loader2,
  RefreshCw,
  Clock,
  MonitorUp,
} from 'lucide-react';
import { FileNode, SessionFileEntry } from '@/types';
import { localmindClient } from '@/lib/localmind/client';

interface FileExplorerProps {
  /** Root-level tree nodes (one level deep) to seed the browser. */
  files: FileNode[];
  onFileOpen?: (path: string) => void;
  /** Called after a delete so the owning view can re-fetch its tree. */
  onFilesChanged?: () => void;
}

function getFileIcon(name: string) {
  const ext = name.split('.').pop() || '';
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) return <FileCode className="h-3.5 w-3.5 text-brand-green" />;
  if (['json'].includes(ext)) return <FileJson className="h-3.5 w-3.5 text-brand-amber" />;
  if (['md', 'txt'].includes(ext)) return <FileText className="h-3.5 w-3.5 text-brand-green-muted" />;
  if (['env', 'example'].includes(ext)) return <File className="h-3.5 w-3.5 text-brand-amber" />;
  return <File className="h-3.5 w-3.5 text-brand-green-muted" />;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatModified(iso: string | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

interface TreeNodeState {
  children: FileNode[] | null; // null = not loaded yet
  loading: boolean;
}

type FileAction = 'open' | 'download' | 'delete' | 'copy' | 'os';

interface FileTreeNodeProps {
  node: FileNode;
  depth: number;
  /** Shared per-path child state, owned by the top-level FileExplorer. */
  nodes: Record<string, TreeNodeState>;
  onToggle: (node: FileNode) => void;
  onOpen: (path: string) => void;
  onAction: (action: FileAction, path: string, isFolder: boolean) => void;
}

function FileTreeNode({ node, depth, nodes, onToggle, onOpen, onAction }: FileTreeNodeProps) {
  const [expanded, setExpanded] = useState(node.expanded ?? false);
  const [copied, setCopied] = useState(false);
  const isFolder = node.type === 'folder';
  const state = nodes[node.path] ?? { children: null, loading: false };
  const children = state.children;

  const toggle = () => {
    setExpanded((e) => !e);
    if (!expanded && children === null && !state.loading) onToggle(node);
  };

  const copyPath = async (path: string) => {
    try {
      await navigator.clipboard.writeText(path);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      onAction('copy', path, isFolder);
    }
  };

  const rowStyle = { paddingLeft: `${depth * 12 + 8}px` };

  if (isFolder) {
    return (
      <div>
        <div
          className="flex items-center gap-1 px-2 py-1 hover:bg-brand-border/50 cursor-pointer rounded transition-colors group"
          style={rowStyle}
          onClick={toggle}
        >
          {state.loading ? (
            <Loader2 className="h-3 w-3 text-brand-green-muted animate-spin shrink-0" />
          ) : expanded ? (
            <ChevronDown className="h-3 w-3 text-brand-green-muted shrink-0" />
          ) : (
            <ChevronRight className="h-3 w-3 text-brand-green-muted shrink-0" />
          )}
          {expanded ? (
            <FolderOpen className="h-3.5 w-3.5 text-brand-amber shrink-0" />
          ) : (
            <Folder className="h-3.5 w-3.5 text-brand-amber shrink-0" />
          )}
          <span className="text-[11px] text-brand-green-soft truncate font-medium group-hover:text-brand-green transition-colors flex-1 min-w-0" title={node.path}>
            {node.name}
          </span>
          <span
            role="button"
            tabIndex={0}
            className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 text-brand-green-muted hover:text-brand-green transition-all"
            onClick={(e) => { e.stopPropagation(); onAction('os', node.path, true); }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAction('os', node.path, true); } }}
            title="Open in OS"
            data-testid={`os-folder-${node.name}`}
          >
            <MonitorUp className="h-2.5 w-2.5" />
          </span>
          <span
            role="button"
            tabIndex={0}
            className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 text-brand-green-muted hover:text-brand-green transition-all"
            onClick={(e) => { e.stopPropagation(); copyPath(node.path); }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); copyPath(node.path); } }}
            title="Copy path"
            data-testid={`copy-${node.name}`}
          >
            <Copy className="h-2.5 w-2.5" />
          </span>
        </div>
        {expanded && (
          <div data-testid={`folder-children-${node.name}`}>
            {state.loading ? (
              <div className="text-[10px] text-brand-green-faint italic px-2 py-0.5" style={{ paddingLeft: `${(depth + 1) * 12 + 8}px` }}>
                Loading…
              </div>
            ) : children !== null && children.length === 0 ? (
              <div className="text-[10px] text-brand-green-faint italic px-2 py-0.5" style={{ paddingLeft: `${(depth + 1) * 12 + 8}px` }}>
                Empty
              </div>
            ) : children !== null ? (
              children.map((child) => (
                <FileTreeNode
                  key={child.path}
                  node={child}
                  depth={depth + 1}
                  nodes={nodes}
                  onToggle={onToggle}
                  onOpen={onOpen}
                  onAction={onAction}
                />
              ))
            ) : null}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="flex items-center gap-1 px-2 py-1 hover:bg-brand-border/50 rounded transition-colors group"
      style={rowStyle}
      onClick={() => onOpen(node.path)}
      title={node.path}
      data-testid={`file-row-${node.name}`}
    >
      {getFileIcon(node.name)}
      <span className="text-[11px] text-brand-green-soft truncate group-hover:text-brand-green transition-colors flex-1 min-w-0">
        {node.name}
      </span>
      {node.size !== undefined && (
        <span className="text-[9px] text-brand-green-faint shrink-0">{formatSize(node.size)}</span>
      )}
      {node.modified && (
        <span className="text-[9px] text-brand-green-faint shrink-0" title={node.modified}>
          {formatModified(node.modified)}
        </span>
      )}
      {/* Per-file actions — visible on hover */}
      <span className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5 text-brand-green-muted transition-all">
        <span
          role="button"
          tabIndex={0}
          className="p-0.5 rounded hover:text-brand-green hover:bg-brand-border/60"
          onClick={(e) => { e.stopPropagation(); onAction('open', node.path, false); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAction('open', node.path, false); } }}
          title="Preview"
          data-testid={`preview-${node.name}`}
        >
          <ExternalLink className="h-2.5 w-2.5" />
        </span>
        <span
          role="button"
          tabIndex={0}
          className="p-0.5 rounded hover:text-brand-green hover:bg-brand-border/60"
          onClick={(e) => { e.stopPropagation(); onAction('os', node.path, false); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAction('os', node.path, false); } }}
          title="Open in OS"
          data-testid={`os-${node.name}`}
        >
          <MonitorUp className="h-2.5 w-2.5" />
        </span>
        <span
          role="button"
          tabIndex={0}
          className="p-0.5 rounded hover:text-brand-green hover:bg-brand-border/60"
          onClick={(e) => { e.stopPropagation(); onAction('download', node.path, false); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAction('download', node.path, false); } }}
          title="Download"
          data-testid={`download-${node.name}`}
        >
          <Download className="h-2.5 w-2.5" />
        </span>
        <span
          role="button"
          tabIndex={0}
          className="p-0.5 rounded hover:text-brand-green hover:bg-brand-border/60"
          onClick={(e) => { e.stopPropagation(); copyPath(node.path); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); copyPath(node.path); } }}
          title="Copy path"
          data-testid={`copy-${node.name}`}
        >
          {copied ? <X className="h-2.5 w-2.5 text-brand-green" /> : <Copy className="h-2.5 w-2.5" />}
        </span>
        <span
          role="button"
          tabIndex={0}
          className="p-0.5 rounded hover:text-brand-red hover:bg-brand-red/10"
          onClick={(e) => { e.stopPropagation(); onAction('delete', node.path, false); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAction('delete', node.path, false); } }}
          title="Delete"
          data-testid={`delete-${node.name}`}
        >
          <Trash2 className="h-2.5 w-2.5" />
        </span>
      </span>
    </div>
  );
}

export function FileExplorer({ files, onFileOpen, onFilesChanged }: FileExplorerProps) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<SessionFileEntry[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [nodes, setNodes] = useState<Record<string, TreeNodeState>>({});
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [recent, setRecent] = useState<SessionFileEntry[]>([]);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The browser is seeded with the home directory's children (useFileTree()
  // with no path); derive the searchable root from the first entry's parent.
  const root = files.length > 0 ? files[0].path.split(/[\\/]/).slice(0, -1).join('/') || '/' : '';

  const loadRecent = useCallback(async () => {
    const items = await localmindClient.getRecentFiles(root, 8);
    setRecent(items);
  }, [root]);

  useEffect(() => {
    let cancelled = false;
    // getRecentFiles swallows errors internally and returns [] on failure.
    localmindClient.getRecentFiles(root, 8).then((items) => {
      if (!cancelled) setRecent(items);
    });
    return () => {
      cancelled = true;
    };
  }, [root]);

  const loadChildren = useCallback(async (node: FileNode) => {
    setNodes((prev) => ({ ...prev, [node.path]: { children: prev[node.path]?.children ?? null, loading: true } }));
    try {
      const children = await localmindClient.getFileTree(node.path);
      setNodes((prev) => ({ ...prev, [node.path]: { children, loading: false } }));
    } catch {
      setNodes((prev) => ({ ...prev, [node.path]: { children: [], loading: false } }));
    }
  }, []);

  // Debounced recursive search across the browser's root.
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const q = query.trim();
    if (!q) {
      setSearchResults(null);
      setSearchError(null);
      return;
    }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      try {
        const results = await localmindClient.searchFiles(root, q);
        setSearchResults(results);
        setSearchError(null);
      } catch {
        setSearchResults([]);
        setSearchError('Search failed');
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, [query, root]);

  const handleAction = (action: FileAction, path: string, isFolder: boolean) => {
    if (action === 'open') {
      onFileOpen?.(path);
      return;
    }
    if (action === 'os') {
      // Open with the OS default app (files) or in the file manager (folders).
      void (isFolder ? localmindClient.openFolder(path) : localmindClient.openFile(path)).catch(() => {
        setNotice('Open failed');
        setTimeout(() => setNotice(null), 2000);
      });
      return;
    }
    if (action === 'download') {
      localmindClient.downloadFile(path);
      return;
    }
    if (action === 'delete') {
      setConfirmDelete(path);
      return;
    }
    // copy handled per-row for its own feedback; this branch is a fallback.
    void path;
  };

  const handleRefresh = () => {
    void loadRecent();
    onFilesChanged?.();
  };

  const confirmDeleteFile = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await localmindClient.deleteFile(confirmDelete);
      setNotice('Deleted');
      setTimeout(() => setNotice(null), 1500);
      setConfirmDelete(null);
      // Ask the owning view to re-fetch so the tree reflects the deletion.
      onFilesChanged?.();
      void loadRecent();
    } catch {
      setNotice('Delete failed');
      setTimeout(() => setNotice(null), 2000);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      {/* Search box + refresh */}
      <div className="flex items-center gap-1">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-brand-green-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search files…"
            className="w-full pl-7 pr-6 py-1 rounded-md border border-brand-border bg-brand-bg-panel text-[11px] text-brand-green-soft placeholder:text-brand-green-faint focus:outline-none focus:border-brand-green/40"
            data-testid="file-search"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-brand-green-muted hover:text-brand-green"
              title="Clear search"
              data-testid="file-search-clear"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <button
          onClick={handleRefresh}
          className="p-1 rounded text-brand-green-muted hover:text-brand-green hover:bg-brand-border/60 transition-colors"
          title="Refresh"
          data-testid="file-refresh"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>

      {/* Recent files */}
      {recent.length > 0 && (
        <div className="pt-0.5">
          <div className="flex items-center gap-1 px-1 py-0.5">
            <Clock className="h-2.5 w-2.5 text-brand-green-muted" />
            <span className="text-[9px] uppercase tracking-wider text-brand-green-faint font-medium">Recent</span>
          </div>
          <div className="space-y-0.5" data-testid="recent-files">
            {recent.map((entry) =>
              entry.type === 'folder' ? null : (
                <div
                  key={entry.path}
                  className="flex items-center gap-1.5 px-2 py-1 hover:bg-brand-border/50 rounded transition-colors cursor-pointer group"
                  onClick={() => onFileOpen?.(entry.path)}
                  title={entry.path}
                  data-testid={`recent-${entry.name}`}
                >
                  {getFileIcon(entry.name)}
                  <span className="text-[11px] text-brand-green-soft truncate flex-1 min-w-0 group-hover:text-brand-green transition-colors">
                    {entry.name}
                  </span>
                  <span className="text-[9px] text-brand-green-faint shrink-0">{formatSize(entry.size)}</span>
                  <span className="text-[9px] text-brand-green-faint shrink-0" title={entry.modified}>
                    {formatModified(entry.modified)}
                  </span>
                </div>
              ),
            )}
          </div>
        </div>
      )}

      {searching && (
        <div className="flex items-center gap-1.5 px-1 py-1 text-[10px] text-brand-green-muted">
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
          Searching…
        </div>
      )}

      {searchError && (
        <div className="px-1 py-1 text-[10px] text-brand-red">{searchError}</div>
      )}

      {searchResults !== null && !searching ? (
        searchResults.length === 0 ? (
          <div className="px-1 py-2 text-[10px] text-brand-green-faint italic">
            No matches for “{query.trim()}”
          </div>
        ) : (
          <div className="space-y-0.5" data-testid="search-results">
            {searchResults.map((entry) =>
              entry.type === 'folder' ? (
                <div key={entry.relPath} className="flex items-center gap-1.5 px-2 py-1 rounded">
                  <Folder className="h-3.5 w-3.5 text-brand-amber shrink-0" />
                  <span className="text-[11px] text-brand-green-soft truncate">{entry.name}</span>
                </div>
              ) : (
                <div
                  key={entry.relPath}
                  className="flex items-center gap-1.5 px-2 py-1 hover:bg-brand-border/50 rounded transition-colors cursor-pointer group"
                  onClick={() => onFileOpen?.(entry.path)}
                  title={entry.path}
                  data-testid={`search-result-${entry.name}`}
                >
                  {getFileIcon(entry.name)}
                  <span className="text-[11px] text-brand-green-soft truncate flex-1 min-w-0 group-hover:text-brand-green transition-colors">
                    {entry.name}
                  </span>
                  <span className="text-[9px] text-brand-green-faint shrink-0">{formatSize(entry.size)}</span>
                  <span
                    role="button"
                    tabIndex={0}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-brand-green hover:bg-brand-border/60 transition-all"
                    onClick={(e) => { e.stopPropagation(); localmindClient.downloadFile(entry.path); }}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); localmindClient.downloadFile(entry.path); } }}
                    title="Download"
                    data-testid={`search-download-${entry.name}`}
                  >
                    <Download className="h-2.5 w-2.5" />
                  </span>
                </div>
              ),
            )}
          </div>
        )
      ) : (
        <div className="space-y-0.5" data-testid="file-tree">
          {files.map((node) => (
            <FileTreeNode
              key={node.path}
              node={node}
              depth={0}
              nodes={nodes}
              onToggle={loadChildren}
              onOpen={(path) => onFileOpen?.(path)}
              onAction={handleAction}
            />
          ))}
        </div>
      )}

      {notice && <div className="px-1 py-1 text-[10px] text-brand-green">{notice}</div>}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="mt-1 p-2 rounded bg-brand-border border border-brand-red/30" data-testid="delete-confirm">
          <div className="text-[10px] text-brand-green-soft mb-2 break-all">
            Delete <span className="font-mono">{confirmDelete.split(/[\\/]/).pop()}</span>?
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setConfirmDelete(null)}
              className="px-2 py-1 text-[10px] rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft"
            >
              Cancel
            </button>
            <button
              onClick={confirmDeleteFile}
              disabled={deleting}
              className="px-2 py-1 text-[10px] rounded bg-brand-red/10 text-brand-red hover:bg-brand-red/20 disabled:opacity-50"
              data-testid="delete-confirm-yes"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
