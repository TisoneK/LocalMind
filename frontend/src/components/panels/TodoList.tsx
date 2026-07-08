'use client';

import { useState } from 'react';
import { Check, Circle, Plus } from 'lucide-react';
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
      {/* Progress header — only show stats when there are tasks */}
      {total > 0 && (
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-[#d4e8d4]">Tasks</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#1a2a1a] text-[#39d353] font-mono">
              {completed}/{total}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[#8ab08a]">{percentage}%</span>
            {onAdd && (
              <button
                onClick={() => setShowInput(!showInput)}
                className="p-0.5 rounded text-[#8ab08a] hover:text-[#39d353] hover:bg-[#1a2a1a] transition-colors"
                title="Add task"
              >
                <Plus className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Progress bar — only show when there are tasks */}
      {total > 0 && (
        <div className="h-1 bg-[#1a2a1a] rounded-full overflow-hidden">
          <div
            className="h-full bg-[#39d353] rounded-full transition-all duration-500"
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
            className="flex-1 bg-[#111a11] border border-[#1a2a1a] rounded px-2 py-1 text-[11px] text-[#d4e8d4] placeholder:text-[#8ab08a] outline-none focus:border-[#39d353]/30"
            autoFocus
          />
          <button
            onClick={handleAddTodo}
            className="px-2 py-1 rounded bg-[#39d353]/10 text-[#39d353] text-[10px] hover:bg-[#39d353]/20 transition-colors"
          >
            Add
          </button>
        </div>
      )}

      {/* Todo items */}
      <div className="space-y-0.5 max-h-48 overflow-y-auto custom-scrollbar">
        {todos.length === 0 && !showInput && (
          <div className="text-[10px] text-[#5a7a5a] px-1.5 py-1 italic">
            No tasks yet — click + to add one
          </div>
        )}
        {todos.map((todo) => (
          <div
            key={todo.id}
            className="flex items-center gap-2 px-1.5 py-1 rounded hover:bg-[#1a2a1a]/30 transition-colors group cursor-pointer"
            onClick={() => onToggle?.(todo.id, !todo.completed)}
          >
            {todo.completed ? (
              <div className="w-3.5 h-3.5 rounded border border-[#39d353] bg-[#39d353]/20 flex items-center justify-center shrink-0">
                <Check className="h-2.5 w-2.5 text-[#39d353]" />
              </div>
            ) : (
              <div className="w-3.5 h-3.5 rounded border border-[#1a2a1a] bg-transparent group-hover:border-[#8ab08a] transition-colors shrink-0" />
            )}
            <span
              className={`text-[11px] leading-tight ${
                todo.completed
                  ? 'text-[#8ab08a] line-through'
                  : 'text-[#d4e8d4]'
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
