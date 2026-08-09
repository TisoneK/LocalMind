'use client';

import { useState } from 'react';
import { Check, Plus } from 'lucide-react';
import { TodoItem } from '@/types';

interface TodoListProps {
  todos: TodoItem[];
  onToggle?: (id: string, completed: boolean) => void;
  onAdd?: (text: string) => void;
}

export function TodoList({ todos, onToggle, onAdd }: TodoListProps) {
  const [newTodoText, setNewTodoText] = useState('');
  const [showInput, setShowInput] = useState(false);

  const completed = todos.filter((t) => t.completed).length;
  const total = todos.length;
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

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
      <div className="space-y-0.5 max-h-48 overflow-y-auto custom-scrollbar">
        {todos.length === 0 && !showInput && (
          <div className="text-[10px] text-brand-green-faint px-1.5 py-1 italic">
            No tasks yet — click + to add one
          </div>
        )}
        {todos.map((todo) => (
          <div
            key={todo.id}
            className="flex items-center gap-2 px-1.5 py-1 rounded hover:bg-brand-border/30 transition-colors group cursor-pointer"
            onClick={() => onToggle?.(todo.id, !todo.completed)}
          >
            {todo.completed ? (
              <div className="w-3.5 h-3.5 rounded border border-brand-green bg-brand-green/20 flex items-center justify-center shrink-0">
                <Check className="h-2.5 w-2.5 text-brand-green" />
              </div>
            ) : (
              <div className="w-3.5 h-3.5 rounded border border-brand-border bg-transparent group-hover:border-brand-green-muted transition-colors shrink-0" />
            )}
            <span
              className={`text-[11px] leading-tight ${
                todo.completed
                  ? 'text-brand-green-muted line-through'
                  : 'text-brand-green-soft'
              }`}
            >
              {todo.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
