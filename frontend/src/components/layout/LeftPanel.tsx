'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Plus, MessageSquare, FolderTree, CheckSquare, Square, Trash2, Loader2, Terminal, Brain, Download, X, ListChecks, ChevronRight, ChevronDown, File as FileIcon, Folder as FolderIcon, MoreVertical, Settings, LayoutDashboard, ClipboardCopy } from 'lucide-react';
import { Session, FileNode, SessionFileEntry, ModelOption, DiffData } from '@/types';
import type { ExportFormat } from '@/lib/localmind/exportChats';
import { stripMarkdownToPreview } from '@/lib/previewText';
import { FilesPanel } from '@/components/panels/FilesPanel';
// ObjectivesPanel import removed — the "Autonomous work" block
// is retired from the normal-chat sidebar. The component file is kept in tree
// for potential re-mount behind a flag.
import { ModelSelector } from '@/components/shared/ModelSelector';
import { FilePreviewDialog } from '@/components/chat/FilePreviewDialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

interface LeftPanelProps {
  sessions: Session[];
  files: FileNode[];
  // Objective props are retired from the sidebar. The
  // useObjectives hook still runs in WorkspaceLayout for backend sync.
  models: ModelOption[];
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
  onDeleteSessions: (sessionIds: string[]) => void | Promise<void>;
  onExportSessions: (sessionIds: string[], format: ExportFormat) => void | Promise<void>;
  onCopySessions: (sessionIds: string[], format: ExportFormat) => void | Promise<void>;
  /** Force the Chat tab to be active (e.g. right after "New Chat"). */
  forceChatTab?: boolean;
  /** Called after the Chat tab has been shown. */
  onChatTabShown?: () => void;
  /** Called after a file is deleted from the Files tab, so the tree can re-fetch. */
  onFilesChanged?: () => void;
  width?: number;
  /** Per-path diff hunks captured this turn (preview Diff mode). */
  fileDiffs?: Record<string, DiffData>;
  /** While the agent is working, the Files tab refreshes on its own. */
  isStreaming?: boolean;
}

type LeftTab = 'chat' | 'files';

export function LeftPanel({
  sessions,
  files,
  models,
  selectedModel,
  onModelChange,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onDeleteSessions,
  onExportSessions,
  onCopySessions,
  forceChatTab,
  onChatTabShown,
  onFilesChanged,
  width = 280,
  fileDiffs,
  isStreaming,
}: LeftPanelProps) {
  const [activeTab, setActiveTab] = useState<LeftTab>('chat');
  // Per-session workspace artifact listings: expanded session
  // ids → their file entries, plus a loading/error flag per id.
  const [expandedSessionFiles, setExpandedSessionFiles] = useState<Record<string, SessionFileEntry[]>>({});
  const [loadingSessionFiles, setLoadingSessionFiles] = useState<Record<string, boolean>>({});
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  // Multi-select chat management (mark → bulk delete / export).
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [copyMenuOpen, setCopyMenuOpen] = useState(false);
  const isCompact = width < 220;

  const sessionList = Array.isArray(sessions) ? sessions : [];
  const selectedCount = selectedIds.size;
  const allSelected = sessionList.length > 0 && selectedCount === sessionList.length;

  const exitSelection = () => {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setConfirmBulkDelete(false);
    setExportMenuOpen(false);
    setCopyMenuOpen(false);
  };

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds((prev) =>
      prev.size === sessionList.length ? new Set() : new Set(sessionList.map((s) => s.id)),
    );
  };

  const handleBulkDelete = () => {
    if (selectedCount === 0) return;
    onDeleteSessions(Array.from(selectedIds));
    exitSelection();
  };

  const handleExport = (format: ExportFormat) => {
    if (selectedCount === 0) return;
    onExportSessions(Array.from(selectedIds), format);
    setExportMenuOpen(false);
  };

  // Copy-to-clipboard bulk action: the same export payload, written to the
  // clipboard instead of downloaded. A transient state on the button tells
  // the user whether the write succeeded (the menu closes either way).
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const handleCopy = async (format: ExportFormat) => {
    if (selectedCount === 0) return;
    setCopyMenuOpen(false);
    try {
      await onCopySessions(Array.from(selectedIds), format);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
    window.setTimeout(() => setCopyState('idle'), 1800);
  };

  // Toggle a session's workspace-artifact listing. Files are
  // fetched once on first expand and cached; the toggle collapses back.
  const toggleSessionFiles = async (sessionId: string) => {
    if (expandedSessionFiles[sessionId]) {
      setExpandedSessionFiles((prev) => {
        const next = { ...prev };
        delete next[sessionId];
        return next;
      });
      return;
    }
    setLoadingSessionFiles((prev) => ({ ...prev, [sessionId]: true }));
    try {
      const { localmindClient } = await import('@/lib/localmind/client');
      const entries = await localmindClient.getSessionFiles(sessionId);
      setExpandedSessionFiles((prev) => ({ ...prev, [sessionId]: entries }));
    } catch {
      // Best-effort: a failed fetch leaves the section collapsed; the user
      // can retry by clicking the toggle again.
    } finally {
      setLoadingSessionFiles((prev) => ({ ...prev, [sessionId]: false }));
    }
  };

  // "New Chat" returns the sidebar to the Chat tab so the fresh conversation
  // (and its session list) is immediately visible instead of leaving the user
  // stranded on Files from the previous chat.
  // ALWAYS consume the flag — even when already on Chat. The
  // old guard `activeTab !== 'chat'` left forceChatTab=true after a New Chat
  // while on Chat, so the FIRST tool event switched to Actions and this
  // effect (activeTab is a dep) yanked it straight back; only the second
  // action stuck. Consuming unconditionally means the flag is gone before
  // the first tool event can race it.
  const forceChatConsumed = useRef(false);
  useEffect(() => {
    if (!forceChatTab) {
      forceChatConsumed.current = false;
      return;
    }
    // Fire at most once per flag activation: setActiveTab('chat') below
    // re-runs this effect (activeTab is a dep) before the parent's
    // onChatTabShown re-render lands, which would double-call otherwise.
    if (forceChatConsumed.current) return;
    forceChatConsumed.current = true;
    if (activeTab !== 'chat') {
      setActiveTab('chat');
    }
    onChatTabShown?.();
  }, [forceChatTab, activeTab, onChatTabShown]);

  // The command palette (⌘K) asks for the Files tab by event, like the right rail's tabs.
  useEffect(() => {
    const show = () => setActiveTab('files');
    window.addEventListener('localmind:focus-files', show);
    return () => window.removeEventListener('localmind:focus-files', show);
  }, []);

  // The error card's "Switch model" action dispatches
  // this event — forward it to the ModelSelector trigger so the dropdown
  // opens, putting the user one click from a different provider/model.
  useEffect(() => {
    const openSelector = () => {
      document
        .querySelector('[data-testid="model-selector-trigger"]')
        ?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    };
    window.addEventListener('localmind:open-model-selector', openSelector);
    return () => window.removeEventListener('localmind:open-model-selector', openSelector);
  }, []);

  // Format epoch timestamp to human-readable date/time
  function formatTimestamp(ts: string | number, formattedDate?: string): string {
    // FIX: Prefer pre-formatted date from backend to avoid showing raw epoch numbers
    if (formattedDate) return formattedDate;
    if (!ts) return '';
    const num = typeof ts === 'string' ? parseFloat(ts) : ts;
    if (isNaN(num) || num === 0) return '';
    // If the number looks like an epoch (seconds since 1970), convert to ms
    const ms = num > 1e12 ? num : num * 1000;
    const d = new Date(ms);
    if (isNaN(d.getTime())) return '';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' });
  }

  const iconSize = 'h-3 w-3';
  const tabs: { id: LeftTab; label: string; icon: React.ReactNode }[] = [
    { id: 'chat', label: 'Chat', icon: <MessageSquare className={iconSize} /> },
    { id: 'files', label: 'Files', icon: <FolderTree className={iconSize} /> },
  ];

  return (
    <div className="h-full flex flex-col bg-brand-bg-panel border-r border-brand-border">
      {/* Header */}
      <div className="px-3 py-3 border-b border-brand-border">
        <ModelSelector
          selectedModel={selectedModel}
          onModelChange={onModelChange}
          models={models}
        />
      </div>

      {/* New Chat button */}
      <div className="px-3 py-2">
        <button
          onClick={onNewChat}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg bg-brand-bg-panel-alt border border-brand-border-strong text-brand-green-soft text-[12px] font-medium hover:bg-brand-border/60 hover:text-brand-green transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          New Session
          <span className="ml-auto text-[9px] opacity-60">⌘N</span>
        </button>
      </div>

      {/* Tab switcher */}
      <div className={`flex justify-center px-1 gap-2 border-b border-brand-border items-center`}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center ${isCompact ? 'p-2.5' : 'gap-1.5 px-2.5 py-1.5'} text-[10px] font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab.id
                ? 'text-brand-green border-brand-green'
                : 'text-brand-green-muted border-transparent hover:text-brand-green-soft'
            }`}
            title={isCompact ? tab.label : undefined}
          >
            {tab.icon}
            {!isCompact && tab.label}
          </button>
        ))}
        {/* Three-dot overflow menu for additional panels */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              className="p-2 text-brand-green-muted hover:text-brand-green-soft transition-colors"
              title="More panels"
              data-testid="left-panel-more-menu"
            >
              <MoreVertical className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="bottom" align="end" className="min-w-[140px]">
            <DropdownMenuItem
              onClick={() => window.dispatchEvent(new Event('localmind:focus-terminal'))}
              className="text-[11px] gap-2 text-brand-green-soft focus:text-brand-green"
            >
              <Terminal className="h-3.5 w-3.5" />
              Terminal
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => window.dispatchEvent(new Event('localmind:focus-agents'))}
              className="text-[11px] gap-2 text-brand-green-soft focus:text-brand-green"
            >
              <LayoutDashboard className="h-3.5 w-3.5" />
              Agents
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => window.dispatchEvent(new Event('localmind:focus-memory'))}
              className="text-[11px] gap-2 text-brand-green-soft focus:text-brand-green"
            >
              <Brain className="h-3.5 w-3.5" />
              Memory
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-brand-border" />
            <DropdownMenuItem
              onClick={() => window.dispatchEvent(new Event('localmind:open-settings'))}
              className="text-[11px] gap-2 text-brand-green-soft focus:text-brand-green"
            >
              <Settings className="h-3.5 w-3.5" />
              Settings
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {activeTab === 'chat' && (
          <div className="p-2">
            {/* Multi-select toolbar */}
            {sessionList.length > 0 && (
              <div className="mb-1 flex items-center gap-1 px-1 min-h-[24px]">
                {!selectionMode ? (
                  <button
                    onClick={() => setSelectionMode(true)}
                    className="ml-auto flex items-center gap-1 px-1.5 py-1 rounded text-[10px] text-brand-green-muted hover:text-brand-green-soft hover:bg-brand-border/50 transition-colors"
                    title="Select multiple chats"
                    data-testid="select-chats"
                  >
                    <ListChecks className="h-3 w-3" />
                    {!isCompact && 'Select'}
                  </button>
                ) : (
                  <>
                    <button
                      onClick={toggleSelectAll}
                      className="flex items-center gap-1 px-1.5 py-1 rounded text-[10px] text-brand-green-soft hover:bg-brand-border/50 transition-colors"
                      title={allSelected ? 'Clear selection' : 'Select all'}
                    >
                      {allSelected ? (
                        <CheckSquare className="h-3 w-3 text-brand-green" />
                      ) : (
                        <Square className="h-3 w-3" />
                      )}
                      {!isCompact && (allSelected ? 'None' : 'All')}
                    </button>
                    <span className="text-[10px] text-brand-green-muted" data-testid="selected-count">
                      {selectedCount} selected
                    </span>
                    {/* Copy-action feedback flash (copy happens async; the menu closes immediately) */}
                    {copyState !== 'idle' && (
                      <span
                        data-testid="copy-feedback"
                        className={`text-[10px] ${copyState === 'copied' ? 'text-brand-green' : 'text-brand-red'}`}
                      >
                        {copyState === 'copied' ? '✓ Copied' : '✗ Clipboard blocked'}
                      </span>
                    )}
                    <button
                      onClick={exitSelection}
                      className="ml-auto p-1 rounded text-brand-green-muted hover:text-brand-green-soft hover:bg-brand-border/50 transition-colors"
                      title="Done"
                      aria-label="Exit selection"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Bulk actions */}
            {selectionMode && selectedCount > 0 && !confirmBulkDelete && (
              <div className="mb-2 flex items-center gap-1.5 px-1">
                <button
                  onClick={() => { setConfirmBulkDelete(true); setExportMenuOpen(false); }}
                  className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-brand-red/10 text-brand-red hover:bg-brand-red/20 transition-colors"
                  data-testid="bulk-delete"
                >
                  <Trash2 className="h-3 w-3" /> Delete
                </button>
                <div className="relative">
                  <button
                    onClick={() => { setCopyMenuOpen((o) => !o); setExportMenuOpen(false); }}
                    className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-brand-green/10 text-brand-green hover:bg-brand-green/20 transition-colors"
                    data-testid="bulk-copy"
                  >
                    <ClipboardCopy className="h-3 w-3" /> Copy
                  </button>
                  {copyMenuOpen && (
                    <div className="absolute left-0 top-full mt-1 z-10 min-w-[120px] rounded-md border border-brand-border bg-brand-bg-panel shadow-lg overflow-hidden">
                      <button
                        onClick={() => handleCopy('markdown')}
                        className="block w-full text-left px-3 py-1.5 text-[10px] text-brand-green-soft hover:bg-brand-border/60 transition-colors"
                        data-testid="copy-markdown"
                      >
                        Markdown
                      </button>
                      <button
                        onClick={() => handleCopy('json')}
                        className="block w-full text-left px-3 py-1.5 text-[10px] text-brand-green-soft hover:bg-brand-border/60 transition-colors"
                        data-testid="copy-json"
                      >
                        JSON
                      </button>
                    </div>
                  )}
                </div>
                <div className="relative">
                  <button
                    onClick={() => setExportMenuOpen((o) => !o)}
                    className="flex items-center gap-1 px-2 py-1 rounded text-[10px] bg-brand-green/10 text-brand-green hover:bg-brand-green/20 transition-colors"
                    data-testid="bulk-export"
                  >
                    <Download className="h-3 w-3" /> Export
                  </button>
                  {exportMenuOpen && (
                    <div className="absolute left-0 top-full mt-1 z-10 min-w-[120px] rounded-md border border-brand-border bg-brand-bg-panel shadow-lg overflow-hidden">
                      <button
                        onClick={() => handleExport('markdown')}
                        className="block w-full text-left px-3 py-1.5 text-[10px] text-brand-green-soft hover:bg-brand-border/60 transition-colors"
                        data-testid="export-markdown"
                      >
                        Markdown (.md)
                      </button>
                      <button
                        onClick={() => handleExport('json')}
                        className="block w-full text-left px-3 py-1.5 text-[10px] text-brand-green-soft hover:bg-brand-border/60 transition-colors"
                        data-testid="export-json"
                      >
                        JSON (.json)
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Bulk delete confirmation */}
            {selectionMode && confirmBulkDelete && (
              <div className="mb-2 p-2 rounded bg-brand-border border border-brand-red/30">
                <div className="text-[10px] text-brand-green-soft mb-2">
                  Delete {selectedCount} chat{selectedCount === 1 ? '' : 's'}? This can&apos;t be undone.
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    onClick={handleBulkDelete}
                    className="px-2 py-1 text-[10px] rounded bg-brand-red/10 text-brand-red hover:bg-brand-red/20"
                    data-testid="bulk-delete-confirm"
                  >
                    Delete {selectedCount}
                  </button>
                  <button
                    onClick={() => setConfirmBulkDelete(false)}
                    className="px-2 py-1 text-[10px] rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="space-y-0.5">
            {(!sessions || sessions.length === 0) && (
              <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
                No sessions yet. Start a new chat!
              </div>
            )}
            {sessionList.map((session) => {
              const isSelected = selectedIds.has(session.id);
              return (
              <div
                key={session.id}
                data-testid="session-row"
                onClick={() => (selectionMode ? toggleSelected(session.id) : onSelectSession(session.id))}
                className={`px-2.5 py-2 rounded cursor-pointer transition-colors group ${
                  selectionMode && isSelected
                    ? 'bg-brand-green/10 border border-brand-green/30'
                    : session.id === currentSessionId
                    ? 'bg-brand-border border border-brand-green/20'
                    : 'hover:bg-brand-border/50'
                }`}
              >
                <div className="flex items-center gap-2 mb-0.5">
                  {selectionMode && (
                    isSelected ? (
                      <CheckSquare className="h-3.5 w-3.5 text-brand-green shrink-0" />
                    ) : (
                      <Square className="h-3.5 w-3.5 text-brand-green-muted shrink-0" />
                    )
                  )}
                  <MessageSquare className="h-3 w-3 text-brand-green-muted shrink-0" />
                  <span className="text-[11px] text-brand-green-soft font-medium truncate flex-1 min-w-0" title={session.title}>
                    {session.title}
                  </span>
                  {!selectionMode && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmDeleteId(session.id);
                      }}
                      className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-brand-red/10 text-brand-green-muted hover:text-brand-red transition-all"
                      title="Delete session"
                    >
                      <Trash2 className="h-2.5 w-2.5" />
                    </button>
                  )}
                </div>
                {!selectionMode && confirmDeleteId === session.id && (
                  <div className="mt-2 p-2 rounded bg-brand-border border border-brand-red/30">
                    <div className="text-[10px] text-brand-green-soft mb-2">Delete this chat?</div>
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(session.id);
                          setConfirmDeleteId(null);
                        }}
                        className="px-2 py-1 text-[10px] rounded bg-brand-red/10 text-brand-red hover:bg-brand-red/20"
                      >
                        Delete
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(null);
                        }}
                        className="px-2 py-1 text-[10px] rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
                <div className="pl-5 flex items-center gap-2">
                  <span
                    className="text-[10px] text-brand-green-muted truncate flex-1 min-w-0"
                    title={stripMarkdownToPreview(session.lastMessage)}
                  >
                    {stripMarkdownToPreview(session.lastMessage)}
                  </span>
                  <span className="text-[9px] text-brand-green-muted shrink-0">{formatTimestamp(session.timestamp, session.formattedDate)}</span>
                </div>
                <div className="pl-5 mt-0.5 flex items-center gap-1">
                  <span className="text-[9px] text-brand-green-muted">{session.messageCount} msgs</span>
                  {!selectionMode && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleSessionFiles(session.id);
                      }}
                      className="ml-auto flex items-center gap-0.5 px-1 py-0.5 rounded text-[9px] text-brand-green-muted hover:text-brand-green hover:bg-brand-border/50 transition-colors"
                      title="Show this chat's files"
                      data-testid={`session-files-toggle-${session.id}`}
                    >
                      {expandedSessionFiles[session.id] ? (
                        <ChevronDown className="h-2.5 w-2.5" />
                      ) : (
                        <ChevronRight className="h-2.5 w-2.5" />
                      )}
                      <FolderTree className="h-2.5 w-2.5" />
                      Files
                    </button>
                  )}
                </div>
                {!selectionMode && expandedSessionFiles[session.id] && (
                  <div className="mt-1 pl-5" data-testid={`session-files-${session.id}`}>
                    {loadingSessionFiles[session.id] ? (
                      <div className="flex items-center gap-1.5 px-1 py-1 text-[10px] text-brand-green-muted">
                        <Loader2 className="h-2.5 w-2.5 animate-spin" />
                        Loading files…
                      </div>
                    ) : (
                      <SessionFileList
                        entries={expandedSessionFiles[session.id]}
                        onOpen={(path) => setPreviewPath(path)}
                      />
                    )}
                  </div>
                )}
              </div>
              );
            })}
            </div>
          </div>
        )}

        {activeTab === 'files' && (
          <FilesPanel
            key={currentSessionId ?? 'none'}
            sessionId={currentSessionId}
            files={files}
            fileDiffs={fileDiffs}
            onOpen={setPreviewPath}
            onFilesChanged={onFilesChanged}
            isStreaming={isStreaming}
          />
        )}
      </div>

      {/* File preview dialog — opened by clicking a session artifact */}
      <FilePreviewDialog path={previewPath} onClose={() => setPreviewPath(null)} diffs={fileDiffs} />
    </div>
  );
}

function _formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Compact per-session artifact list (flat entries, folder depth indent). */
function SessionFileList({ entries, onOpen }: { entries: SessionFileEntry[]; onOpen: (path: string) => void }) {
  if (!entries || entries.length === 0) {
    return (
      <div className="px-1 py-1 text-[10px] text-brand-green-faint italic">
        No files yet — artifacts will appear here.
      </div>
    );
  }
  const sorted = [...entries].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
    return a.relPath.localeCompare(b.relPath);
  });
  return (
    <div className="space-y-0.5">
      {sorted.map((entry) => {
        const depth = entry.relPath.split(/[\\/]/).length - 1;
        if (entry.type === 'folder') {
          return (
            <div
              key={entry.relPath}
              className="flex items-center gap-1.5 px-1.5 py-0.5 rounded text-brand-amber"
              style={{ paddingLeft: `${depth * 10 + 6}px` }}
              title={entry.relPath}
            >
              <FolderIcon className="h-3 w-3 shrink-0" />
              <span className="text-[10px] text-brand-green-soft truncate">{entry.name}</span>
            </div>
          );
        }
        return (
          <button
            key={entry.relPath}
            onClick={() => onOpen(entry.path)}
            className="flex items-center gap-1.5 w-full text-left px-1.5 py-0.5 rounded hover:bg-brand-border/50 transition-colors group"
            style={{ paddingLeft: `${depth * 10 + 6}px` }}
            title={entry.path}
          >
            <FileIcon className="h-3 w-3 shrink-0 text-brand-green-muted" />
            <span className="text-[10px] text-brand-green-soft truncate flex-1 min-w-0 group-hover:text-brand-green transition-colors">
              {entry.name}
            </span>
            <span className="text-[9px] text-brand-green-faint shrink-0">{_formatFileSize(entry.size)}</span>
          </button>
        );
      })}
    </div>
  );
}
