'use client';

import { useState } from 'react';
import {
  Check,
  Plus,
  ChevronDown,
  ChevronRight,
  Terminal,
  FileText,
  FilePen,
  Search,
  Code2,
  Globe,
  Brain,
  Cpu,
  GitBranch,
  Wrench,
} from 'lucide-react';
import { ActionItem, TodoItem, ToolStatus } from '@/types';

interface TodoListProps {
  todos: TodoItem[];
  /** All actions for this session — grouped under their owning todo via todoId. */
  actions?: ActionItem[];
  onToggle?: (id: string, completed: boolean) => void;
  onAdd?: (text: string) => void;
}

/** Map a tool name to a lucide icon element for the action sub-timeline.
 *  Returns an element (not a component) so nothing is created during render. */
function toolIcon(type: string) {
  const cls = 'h-3 w-3 text-brand-green-muted mt-[1px] shrink-0';
  switch (type) {
    case 'shell':
      return <Terminal className={cls} />;
    case 'git':
      return <GitBranch className={cls} />;
    case 'file_write':
      return <FilePen className={cls} />;
    case 'file_read':
    case 'file_task':
      return <FileText className={cls} />;
    case 'grep':
      return <Search className={cls} />;
    case 'code_exec':
      return <Code2 className={cls} />;
    case 'web_search':
      return <Globe className={cls} />;
    case 'memory_op':
      return <Brain className={cls} />;
    case 'sysinfo':
      return <Cpu className={cls} />;
    default:
      return <Wrench className={cls} />;
  }
}

function statusColor(status: ToolStatus | undefined): string {
  switch (status) {
    case 'done':
      return 'bg-brand-green';
    case 'failed':
      return 'bg-brand-red';
    case 'running':
    case 'started':
    case 'in_progress':
      return 'bg-brand-amber animate-pulse';
    default:
      return 'bg-brand-green-muted/40';
  }
}

function formatDuration(sec?: number): string {
  if (sec === undefined || sec === null) return '';
  if (sec < 1) return `${Math.round(sec * 1000)}ms`;
  return `${sec.toFixed(1)}s`;
}

/** One tool execution under a todo — own state so hooks stay at component top. */
function ActionRow({ action }: { action: ActionItem }) {
  const [showCmd, setShowCmd] = useState(false);
  const isRunning =
    action.status === 'running' ||
    action.status === 'started' ||
    action.status === 'in_progress' ||
    action.status === 'pending';
  return (
    <div
      className="flex items-start gap-1.5 px-1.5 py-0.5 rounded hover:bg-brand-border/30 transition-colors cursor-pointer"
      onClick={() => setShowCmd(!showCmd)}
      title={showCmd ? 'Hide command' : 'Show command'}
    >
      <span className={`mt-1 h-1.5 w-1.5 rounded-full shrink-0 ${statusColor(action.status)}`} />
      {toolIcon(action.type)}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span
            className={`text-[10px] truncate ${
              action.status === 'failed'
                ? 'text-brand-red'
                : isRunning
                  ? 'text-brand-amber'
                  : 'text-brand-green-soft'
            }`}
          >
            {action.label || action.type.replace(/_/g, ' ')}
          </span>
          {action.duration !== undefined && (
            <span className="text-[9px] text-brand-green-faint font-mono shrink-0">
              {formatDuration(action.duration)}
            </span>
          )}
        </div>
        {showCmd && (action.input || action.output || action.error) && (
          <div className="mt-0.5 space-y-0.5">
            {action.input && (
              <pre className="text-[9px] font-mono text-brand-green-muted bg-brand-bg-rail rounded px-1.5 py-1 overflow-x-auto custom-scrollbar whitespace-pre-wrap break-all">
                {action.input}
              </pre>
            )}
            {action.error && (
              <pre className="text-[9px] font-mono text-brand-red bg-brand-bg-rail rounded px-1.5 py-1 overflow-x-auto custom-scrollbar whitespace-pre-wrap break-all">
                {action.error}
              </pre>
            )}
            {action.output && (
              <pre className="text-[9px] font-mono text-brand-green-muted bg-brand-bg-rail rounded px-1.5 py-1 overflow-x-auto custom-scrollbar whitespace-pre-wrap break-all max-h-24">
                {action.output}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function TodoList({ todos, actions = [], onToggle, onAdd }: TodoListProps) {
  const [newTodoText, setNewTodoText] = useState('');
  const [showInput, setShowInput] = useState(false);
  // Expanded todos — keyed by todo id.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const completed = todos.filter((t) => t.completed).length;
  const total = todos.length;
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

  // One todo owns MANY actions: group the session's actions under their todo.
  const actionsByTodo = new Map<string, ActionItem[]>();
  for (const a of actions) {
    if (!a.todoId) continue;
    const list = actionsByTodo.get(a.todoId) ?? [];
    list.push(a);
    actionsByTodo.set(a.todoId, list);
  }

  const handleAddTodo = () => {
    const text = newTodoText.trim();
    if (!text) return;
    onAdd?.(text);
    setNewTodoText('');
    setShowInput(false);
  };

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-2">
      {/* Header — always show so the + button is accessible even with 0 todos */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium text-brand-green-soft">Tasks</span>
          {total > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-brand-border text-brand-green font-mono">
              {completed}/{total}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {total > 0 && <span className="text-[10px] text-brand-green-muted">{percentage}%</span>}
          {onAdd && (
            <button
              onClick={() => setShowInput(!showInput)}
              className="p-0.5 rounded text-brand-green-muted hover:text-brand-green hover:bg-brand-border transition-colors"
              title="Add task"
            >
              <Plus className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Progress bar — only show when there are tasks */}
      {total > 0 && (
        <div className="h-1 bg-brand-border rounded-full overflow-hidden">
          <div
            className="h-full bg-brand-green rounded-full transition-all duration-500"
            style={{ width: `${percentage}%` }}
          />
        </div>
      )}

      {/* Add todo input */}
      {showInput && onAdd && (
        <div className="flex items-center gap-1.5 px-1.5">
          <input
            type="text"
            value={newTodoText}
            onChange={(e) => setNewTodoText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleAddTodo();
              if (e.key === 'Escape') {
                setShowInput(false);
                setNewTodoText('');
              }
            }}
            placeholder="New task..."
            className="flex-1 bg-brand-bg-rail border border-brand-border rounded px-2 py-1 text-[11px] text-brand-green-soft placeholder:text-brand-green-muted outline-none focus:border-brand-green/30"
            autoFocus
          />
          <button
            onClick={handleAddTodo}
            className="px-2 py-1 rounded bg-brand-green/10 text-brand-green text-[10px] hover:bg-brand-green/20 transition-colors"
          >
            Add
          </button>
        </div>
      )}

      {/* Todo items */}
      <div className="space-y-0.5 max-h-56 overflow-y-auto custom-scrollbar">
        {todos.length === 0 && !showInput && (
          <div className="text-[10px] text-brand-green-faint px-1.5 py-1 italic">
            No tasks yet — click + to add one
          </div>
        )}
        {todos.map((todo) => {
          const todoActions = (actionsByTodo.get(todo.id) ?? []).sort(
            (a, b) => (a.iteration ?? Number.MAX_SAFE_INTEGER) - (b.iteration ?? Number.MAX_SAFE_INTEGER)
          );
          const runningCount = todoActions.filter(
            (a) => a.status === 'running' || a.status === 'started' || a.status === 'in_progress'
          ).length;
          const isOpen = expanded.has(todo.id);

          return (
            <div key={todo.id} className="group">
              <div
                className="flex items-center gap-1.5 px-1.5 py-1 rounded hover:bg-brand-border/30 transition-colors cursor-pointer"
                onClick={() => onToggle?.(todo.id, !todo.completed)}
                title={todo.completed ? 'Mark as not done' : 'Mark as done'}
              >
                {todo.completed ? (
                  <div className="w-3.5 h-3.5 rounded border border-brand-green bg-brand-green/20 flex items-center justify-center shrink-0">
                    <Check className="h-2.5 w-2.5 text-brand-green" />
                  </div>
                ) : (
                  <div className="w-3.5 h-3.5 rounded border border-brand-border bg-transparent group-hover:border-brand-green-muted transition-colors shrink-0" />
                )}
                <span
                  className={`text-[11px] leading-tight flex-1 ${
                    todo.completed
                      ? 'text-brand-green-muted line-through'
                      : 'text-brand-green-soft'
                  }`}
                >
                  {todo.text}
                </span>
                {todoActions.length > 0 && (
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono shrink-0 ${
                      runningCount > 0
                        ? 'bg-brand-amber/15 text-brand-amber'
                        : 'bg-brand-border text-brand-green-muted'
                    }`}
                    title={`${todoActions.length} action${todoActions.length === 1 ? '' : 's'} under this task`}
                  >
                    {runningCount > 0 ? `${runningCount}▶` : `${todoActions.length}✓`}
                  </span>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleExpand(todo.id);
                  }}
                  className="p-0.5 rounded text-brand-green-muted hover:text-brand-green hover:bg-brand-border transition-colors shrink-0"
                  title={isOpen ? 'Collapse actions' : 'Show actions'}
                >
                  {isOpen ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )}
                </button>
              </div>

              {/* Nested action sub-timeline — the many actions under THIS todo */}
              {isOpen && todoActions.length > 0 && (
                <div className="ml-4 pl-2.5 border-l border-brand-border/70 space-y-0.5 py-0.5">
                  {todoActions.map((action) => (
                    <ActionRow key={action.id} action={action} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
