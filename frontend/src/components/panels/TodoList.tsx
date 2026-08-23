'use client';

import { Fragment, useState } from 'react';
import { Check, Plus, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { ActionItem, TodoItem } from '@/types';
import { useEnterMotion } from '@/lib/localmind/motion';

interface TodoListProps {
  todos: TodoItem[];
  /** Actions for this session — used for the per-todo count badge AND to
   *  detect which plan step is currently executing (running actions →
   *  the "active" todo, highlighted like the reference agent). */
  actions?: ActionItem[];
  onToggle?: (id: string, completed: boolean) => void;
  onAdd?: (text: string) => void;
}

export function TodoList({ todos, actions = [], onToggle, onAdd }: TodoListProps) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  const [newTodoText, setNewTodoText] = useState('');
  const [showInput, setShowInput] = useState(false);

  // B-2026-08-23-8: sub-goal rows (plan-{i}-sub-{j}) are ordered guidance
  // nested under their parent goal — rendered indented, never counted in
  // the denominator (the parent plan rows own the n/n contract).
  const isSubRow = (id: string) => /^plan-\d+-sub-\d+$/.test(id);
  const parentRows = todos.filter((t) => !isSubRow(t.id));
  const completed = parentRows.filter((t) => t.completed).length;
  const total = parentRows.length;
  // B-2026-08-23-11: the visible label is the short title when present.
  // The full content (paths/commands) is preserved for the tooltip and
  // the agent context (todos are persisted with it).
  const displayText = (t: TodoItem) => t.title || t.text;
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

  // Per-todo action counts: how many actions each plan step owns, and how
  // many are still running — so "one todo → many actions" stays visible
  // without duplicating the execution trace.
  const countByTodo = new Map<string, { total: number; running: number }>();
  for (const a of actions) {
    if (!a.todoId) continue;
    const entry = countByTodo.get(a.todoId) ?? { total: 0, running: 0 };
    entry.total += 1;
    if (
      a.status === 'running' ||
      a.status === 'started' ||
      a.status === 'in_progress'
    ) {
      entry.running += 1;
    }
    countByTodo.set(a.todoId, entry);
  }

  const handleAddTodo = () => {
    const text = newTodoText.trim();
    if (!text) return;
    onAdd?.(text);
    setNewTodoText('');
    setShowInput(false);
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

      {/* Progress bar — animates as steps complete */}
      {total > 0 && (
        <div className="h-1 bg-brand-border rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-brand-green rounded-full"
            initial={false}
            animate={{ width: `${percentage}%` }}
            transition={reduceMotion ? { duration: 0 } : { duration: 0.5, ease: 'easeOut' }}
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

      {/* Todo items — plan + completion state only */}
      <div className="space-y-0.5 max-h-48 overflow-y-auto custom-scrollbar">
        {todos.length === 0 && !showInput && (
          <div className="text-[10px] text-brand-green-faint px-1.5 py-1 italic">
            No tasks yet — click + to add one
          </div>
        )}
        <AnimatePresence initial={false}>
          {todos.map((todo) => {
            // B-2026-08-23-8: skip sub-goal rows here — they render
            // nested right under their parent below.
            if (isSubRow(todo.id)) return null;
            const counts = countByTodo.get(todo.id);
            const isActive =
              !todo.completed &&
              (todo.status === 'running' ||
                todo.status === 'started' ||
                todo.status === 'in_progress' ||
                (counts?.running ?? 0) > 0);
            const subRows = todos.filter(
              (t) => isSubRow(t.id) && t.id.startsWith(`${todo.id}-`)
            );
            return (
              <Fragment key={todo.id}>
              <motion.div
                key={todo.id}
                layout={!reduceMotion}
                {...enter({ x: -6 })}
                exit={reduceMotion ? undefined : { opacity: 0, x: -6 }}
                data-testid="todo-row"
                data-active={isActive || undefined}
                className={`flex items-center gap-2 px-1.5 py-1 rounded transition-colors group cursor-pointer ${
                  isActive
                    ? 'bg-brand-amber/[0.07] ring-1 ring-inset ring-brand-amber/25'
                    : 'hover:bg-brand-border/30'
                }`}
                onClick={() => onToggle?.(todo.id, !todo.completed)}
                title={todo.completed ? 'Mark as not done' : 'Mark as done'}
              >
                {todo.completed ? (
                  <motion.div
                    initial={reduceMotion ? false : { scale: 0.4, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ duration: 0.2, ease: 'easeOut' }}
                    className="w-3.5 h-3.5 rounded border border-brand-green bg-brand-green/20 flex items-center justify-center shrink-0"
                  >
                    <Check className="h-2.5 w-2.5 text-brand-green" />
                  </motion.div>
                ) : isActive ? (
                  <div className="w-3.5 h-3.5 flex items-center justify-center shrink-0" title="In progress">
                    <Loader2 className={`h-3 w-3 text-brand-amber ${reduceMotion ? '' : 'animate-spin'}`} />
                  </div>
                ) : (
                  <div className="w-3.5 h-3.5 rounded border border-brand-border bg-transparent group-hover:border-brand-green-muted transition-colors shrink-0" />
                )}
                <span
                  className={`text-[11px] leading-tight flex-1 ${
                    todo.completed
                      ? 'text-brand-green-muted line-through'
                      : isActive
                        ? 'text-brand-amber-soft font-medium'
                        : 'text-brand-green-soft'
                  }`}
                >
                <span
                  className="truncate"
                  title={
                    todo.content && todo.content !== displayText(todo)
                      ? todo.content
                      : undefined
                  }
                >
                  {displayText(todo)}
                </span>
              </span>
                {counts && counts.total > 0 && (
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono shrink-0 ${
                      counts.running > 0
                        ? 'bg-brand-amber/15 text-brand-amber'
                        : 'bg-brand-border text-brand-green-muted'
                    }`}
                    title={`${counts.total} action${counts.total === 1 ? '' : 's'} under this task (see Actions tab)`}
                  >
                    {counts.running > 0 ? `${counts.running}▶` : `${counts.total}✓`}
                  </span>
                )}
              </motion.div>
              {/* B-2026-08-23-8: sub-goal route rows — ordered guidance
                  nested under the parent goal, informational only (no
                  checkbox, no action badge), never counted in n/n. */}
              {subRows.map((sub) => (
                <div
                  key={sub.id}
                  data-testid="todo-subrow"
                  data-completed={sub.completed || undefined}
                  className="flex items-center gap-1.5 pl-5 ml-1.5 py-0.5 border-l border-brand-border/60"
                  title="Sub-goal — part of the goal route"
                >
                  <span
                    className={`text-[9px] shrink-0 ${
                      sub.completed ? 'text-brand-green' : 'text-brand-green-faint'
                    }`}
                  >
                    {sub.completed ? '✓' : '↳'}
                  </span>
                  <span
                    className={`text-[10px] leading-tight ${
                      sub.completed
                        ? 'text-brand-green-muted line-through'
                        : 'text-brand-green-muted/80'
                    }`}
                  >
                    {displayText(sub)}
                  </span>
                </div>
              ))}
              </Fragment>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
