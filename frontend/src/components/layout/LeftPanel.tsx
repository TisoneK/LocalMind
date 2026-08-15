'use client';

import React, { useEffect, useState } from 'react';
import { Plus, MessageSquare, Zap, FolderTree, CheckSquare, Cpu, Trash2, Loader2, CheckCircle2, XCircle, Terminal, Globe, FileEdit, Brain } from 'lucide-react';
import { Session, ActionItem, FileNode, TodoItem, ModelOption, ToolCall } from '@/types';
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
  onToggleTodo: (id: string, completed: boolean) => void;
  onAddTodo: (text: string) => void;
  onAbort?: () => void;
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
  onToggleTodo,
  onAddTodo,
  onAbort,
  width = 280,
}: LeftPanelProps) {
  const [activeTab, setActiveTab] = useState<LeftTab>('chat');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const isCompact = width < 220;

  // Tool progress belongs in Actions, not in the chat transcript. The chat
  // hook emits this event as soon as the backend announces a tool call.
  useEffect(() => {
    const showActions = () => setActiveTab('actions');
    window.addEventListener('localmind:tool-call-started', showActions);
    return () => window.removeEventListener('localmind:tool-call-started', showActions);
  }, []);

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
          <div className="p-2 space-y-0.5">
            {(!sessions || sessions.length === 0) && (
              <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
                No sessions yet. Start a new chat!
              </div>
            )}
            {Array.isArray(sessions) && sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={`px-2.5 py-2 rounded cursor-pointer transition-colors group ${
                  session.id === currentSessionId
                    ? 'bg-brand-border border border-brand-green/20'
                    : 'hover:bg-brand-border/50'
                }`}
              >
                <div className="flex items-center gap-2 mb-0.5">
                  <MessageSquare className="h-3 w-3 text-brand-green-muted shrink-0" />
                  <span className="text-[11px] text-brand-green-soft font-medium truncate flex-1 min-w-0" title={session.title}>
                    {session.title}
                  </span>
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
                </div>
                {confirmDeleteId === session.id && (
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
            ))}
          </div>
        )}

        {activeTab === 'actions' && (
          <div className="p-2">
            {/* Live tool calls — show ALL tool calls regardless of status (running, done, failed) */}
            {activeToolCalls.length > 0 ? (
              <div className="space-y-1">
                {activeToolCalls.map((tc) => {
                  const iconMap: Record<string, React.ReactNode> = {
                    file_write: <FileEdit className="h-3 w-3" />,
                    file_task: <FileEdit className="h-3 w-3" />,
                    edit_file: <FileEdit className="h-3 w-3" />,
                    shell: <Terminal className="h-3 w-3" />,
                    code_exec: <Terminal className="h-3 w-3" />,
                    web_search: <Globe className="h-3 w-3" />,
                    memory_op: <Brain className="h-3 w-3" />,
                    sysinfo: <Zap className="h-3 w-3" />,
                  };
                  const statusIcon = isActiveToolStatus(tc.status)
                    ? <Loader2 className="h-3 w-3 animate-spin text-brand-amber" />
                    : tc.status === 'done'
                      ? <CheckCircle2 className="h-3 w-3 text-brand-green" />
                      : <XCircle className="h-3 w-3 text-brand-red" />;
                  const displayLabel = tc.label || tc.name.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
                  const durationStr = tc.duration !== undefined
                    ? (tc.duration >= 1000 ? `${(tc.duration / 1000).toFixed(1)}s` : `${tc.duration}ms`)
                    : '';
                  return (
                    <div key={tc.id} className="flex items-center gap-1.5 min-w-0 px-2 py-1 rounded hover:bg-brand-border/50">
                      <span className="text-brand-green-muted">{iconMap[tc.name] || <Terminal className="h-3 w-3" />}</span>
                      <span className="text-[10px] text-brand-green-soft font-mono truncate flex-1 min-w-0" title={displayLabel}>
                        {displayLabel}
                      </span>
                      {tc.timestamp && <span className="text-[8px] text-brand-green-muted/60 shrink-0">{tc.timestamp}</span>}
                      {durationStr && <span className="text-[9px] text-brand-green-muted shrink-0">{durationStr}</span>}
                      {statusIcon}
                    </div>
                  );
                })}
              </div>
            ) : actions.length > 0 ? (
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
