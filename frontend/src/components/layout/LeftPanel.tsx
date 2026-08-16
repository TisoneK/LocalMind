'use client';

import React, { useEffect, useState } from 'react';
import { Plus, MessageSquare, Zap, FolderTree, CheckSquare, Square, Cpu, Trash2, Loader2, Terminal, Globe, FileEdit, Brain, Download, X, ListChecks } from 'lucide-react';
import { Session, ActionItem, FileNode, TodoItem, ModelOption, ToolCall } from '@/types';
import type { ExportFormat } from '@/lib/localmind/exportChats';
import { ActionHistory } from '@/components/panels/ActionHistory';
import { FileExplorer } from '@/components/panels/FileExplorer';
import { TodoList } from '@/components/panels/TodoList';
// ADR-34 B-11: ObjectivesPanel import removed — the "Autonomous work" block
// is retired from the normal-chat sidebar. The component file is kept in tree
// for potential re-mount behind a flag.
import { isActiveToolStatus } from '@/lib/localmind/progress';
import { ModelSelector } from '@/components/shared/ModelSelector';

interface LeftPanelProps {
  sessions: Session[];
  actions: ActionItem[];
  files: FileNode[];
  todos: TodoItem[];
  // ADR-34 B-11: objective props are retired from the sidebar. The
  // useObjectives hook still runs in WorkspaceLayout for backend sync.
  activeToolCalls: ToolCall[];
  models: ModelOption[];
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
  onDeleteSessions: (sessionIds: string[]) => void | Promise<void>;
  onExportSessions: (sessionIds: string[], format: ExportFormat) => void | Promise<void>;
  onToggleTodo: (id: string, completed: boolean) => void;
  onAddTodo: (text: string) => void;
  onAbort?: () => void;
  /** Force the Chat tab to be active (e.g. right after "New Chat"). */
  forceChatTab?: boolean;
  /** Called after the Chat tab has been shown. */
  onChatTabShown?: () => void;
  width?: number;
}

type LeftTab = 'chat' | 'actions' | 'files';

export function LeftPanel({
  sessions,
  actions,
  files,
  todos,
  activeToolCalls,
  models,
  selectedModel,
  onModelChange,
  currentSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onDeleteSessions,
  onExportSessions,
  onToggleTodo,
  onAddTodo,
  onAbort,
  forceChatTab,
  onChatTabShown,
  width = 280,
}: LeftPanelProps) {
  const [activeTab, setActiveTab] = useState<LeftTab>('chat');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  // Multi-select chat management (mark → bulk delete / export).
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const isCompact = width < 220;

  const sessionList = Array.isArray(sessions) ? sessions : [];
  const selectedCount = selectedIds.size;
  const allSelected = sessionList.length > 0 && selectedCount === sessionList.length;

  const exitSelection = () => {
    setSelectionMode(false);
    setSelectedIds(new Set());
    setConfirmBulkDelete(false);
    setExportMenuOpen(false);
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

  // Tool progress belongs in Actions, not in the chat transcript. The chat
  // hook emits this event as soon as the backend announces a tool call.
  useEffect(() => {
    const showActions = () => setActiveTab('actions');
    window.addEventListener('localmind:tool-call-started', showActions);
    return () => window.removeEventListener('localmind:tool-call-started', showActions);
  }, []);

  // "New Chat" returns the sidebar to the Chat tab so the fresh conversation
  // (and its session list) is immediately visible instead of leaving the user
  // stranded on Actions/Files from the previous chat.
  useEffect(() => {
    if (forceChatTab && activeTab !== 'chat') {
      setActiveTab('chat');
      onChatTabShown?.();
    }
  }, [forceChatTab, activeTab, onChatTabShown]);

  // ADR-20 (Session 167): the error card's "Switch model" action dispatches
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
    { id: 'actions', label: 'Actions', icon: <Zap className={iconSize} /> },
    { id: 'files', label: 'Files', icon: <FolderTree className={iconSize} /> },
  ];

  return (
    <div className="h-full flex flex-col bg-brand-bg-base border-r border-brand-border">
      {/* Header */}
      <div className="px-3 py-3 border-b border-brand-border">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-6 h-6 rounded bg-brand-green/10 flex items-center justify-center">
            <Cpu className="h-3.5 w-3.5 text-brand-green" />
          </div>
          <span className="text-sm font-bold text-brand-green-soft tracking-tight">LocalMind</span>
          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-brand-green/10 text-brand-green font-mono">
            v0.5
          </span>
        </div>
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
          className="flex items-center gap-2 w-full px-3 py-1.5 rounded-md bg-brand-green/10 border border-brand-green/20 text-brand-green text-[11px] font-medium hover:bg-brand-green/20 transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
          New Chat
          <span className="ml-auto text-[9px] opacity-60">⌘N</span>
        </button>
      </div>

      {/* Tab switcher */}
      <div className={`flex justify-center px-1 gap-2 border-b border-brand-border`}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
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
                  <span className="text-[10px] text-brand-green-muted truncate flex-1 min-w-0" title={session.lastMessage}>
                    {session.lastMessage}
                  </span>
                  <span className="text-[9px] text-brand-green-muted shrink-0">{formatTimestamp(session.timestamp, session.formattedDate)}</span>
                </div>
                <div className="pl-5 mt-0.5">
                  <span className="text-[9px] text-brand-green-muted">{session.messageCount} msgs</span>
                </div>
              </div>
              );
            })}
            </div>
          </div>
        )}

        {activeTab === 'actions' && (
          <div className="p-2">
            {/* Live + persisted actions share one expandable-card list. The
                ActionHistory already renders a running state (spinner + pulse),
                so active/just-finished actions are full cards — not the old
                compact pills — matching the post-session history. */}
            {actions.length > 0 ? (
              <ActionHistory actions={actions} />
            ) : (
              <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
                Actions will appear here during execution.
              </div>
            )}
          </div>
        )}

        {activeTab === 'files' && (
          <div className="p-2">
            {files.length === 0 ? (
              <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
                Loading file tree...
              </div>
            ) : (
              <FileExplorer files={files} />
            )}
          </div>
        )}
      </div>

      {/* Running tasks indicator — compact, with cancel button */}
      {activeToolCalls.filter(tc => isActiveToolStatus(tc.status)).length > 0 && (
        <div className="border-t border-brand-border px-3 py-2">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Loader2 className="h-3 w-3 animate-spin text-brand-amber" />
            <span className="text-[10px] text-brand-amber font-medium">
              {activeToolCalls.filter(tc => isActiveToolStatus(tc.status)).length} task{activeToolCalls.filter(tc => isActiveToolStatus(tc.status)).length > 1 ? 's' : ''} running
            </span>
            {onAbort && (
              <button
                onClick={onAbort}
                className="ml-auto text-[9px] px-1.5 py-0.5 rounded border border-brand-red/30 bg-brand-red/10 text-brand-red hover:bg-brand-red/20 transition-colors"
                title="Cancel running tasks"
              >
                Cancel
              </button>
            )}
          </div>
          {activeToolCalls.filter(tc => isActiveToolStatus(tc.status)).map((tc) => {
            const iconMap: Record<string, React.ReactNode> = {
              file_write: <FileEdit className="h-3 w-3" />,
              file_task: <FileEdit className="h-3 w-3" />,
              shell: <Terminal className="h-3 w-3" />,
              code_exec: <Terminal className="h-3 w-3" />,
              web_search: <Globe className="h-3 w-3" />,
              memory_op: <Brain className="h-3 w-3" />,
            };
            const displayLabel = tc.label
              || tc.name.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
            return (
              <div key={tc.id} className="flex items-center gap-1.5 min-w-0 px-1 py-0.5">
                <span className="text-brand-amber">{iconMap[tc.name] || <Terminal className="h-3 w-3" />}</span>
                <span className="text-[10px] text-brand-green-soft font-mono truncate min-w-0 flex-1" title={displayLabel}>
                  {displayLabel}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* ADR-34 B-11: the "Autonomous work" / ObjectivesPanel block is
          removed from the normal-chat sidebar. Background objective
          persistence/API remains intact (useObjectives hook still runs,
          backend routes unchanged) — a separate product decision is
          required before re-surfacing or deleting the feature. */}

      {/* Todos — always show so users can add tasks even when the list is empty.
          Previously the `todos.length > 0` condition made it impossible to
          create the first todo via the UI (chicken-and-egg).
          Session 212 (realtime-alive-ui): keep an EXISTING plan visible while
          tools run so the user watches steps check off live; only the empty
          "add a task" state is hidden during active work to reduce clutter. */}
      {(activeToolCalls.filter(tc => isActiveToolStatus(tc.status)).length === 0 || todos.length > 0) && (
        <div className="border-t border-brand-border p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <CheckSquare className="h-3 w-3 text-brand-amber" />
            <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
              Todos
            </span>
            {todos.length > 0 && (
              <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded-full bg-brand-border text-brand-green-muted font-mono">
                {todos.filter(t => t.completed).length}/{todos.length}
              </span>
            )}
          </div>
          <TodoList todos={todos} actions={actions} onToggle={onToggleTodo} onAdd={onAddTodo} />
        </div>
      )}
    </div>
  );
}
