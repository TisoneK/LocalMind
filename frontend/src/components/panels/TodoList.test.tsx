/**
 * Tests for TodoList (Session 212 — realtime-alive-ui).
 *
 * The plan checklist shows completion state and, crucially, highlights the
 * step currently executing (a running action under it, or todo.status
 * running/in_progress) so the plan feels alive as work happens.
 */

import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TodoList } from './TodoList';
import type { TodoItem, ActionItem } from '../../types';

const todo = (overrides: Partial<TodoItem> = {}): TodoItem => ({
  id: 'p0',
  text: 'Do the thing',
  completed: false,
  ...overrides,
});

const action = (overrides: Partial<ActionItem> = {}): ActionItem => ({
  id: 'a0',
  name: 'shell',
  status: 'done',
  ...overrides,
} as ActionItem);

describe('TodoList', () => {
  it('shows an empty-state hint with no todos', () => {
    render(<TodoList todos={[]} onAdd={() => {}} />);
    expect(screen.getByText(/No tasks yet/)).toBeInTheDocument();
  });

  it('renders todos with completion count', () => {
    render(
      <TodoList
        todos={[todo({ id: 'p0', text: 'Step one', completed: true }), todo({ id: 'p1', text: 'Step two' })]}
      />,
    );
    expect(screen.getByText('Step one')).toBeInTheDocument();
    expect(screen.getByText('Step two')).toBeInTheDocument();
    expect(screen.getByText('1/2')).toBeInTheDocument();
  });

  it('highlights the active step when it has a running action', () => {
    render(
      <TodoList
        todos={[todo({ id: 'p0', text: 'Running step' }), todo({ id: 'p1', text: 'Later step' })]}
        actions={[action({ id: 'a1', status: 'running', todoId: 'p0' })]}
      />,
    );
    const rows = screen.getAllByTestId('todo-row');
    const activeRow = rows.find((r) => r.getAttribute('data-active') === 'true');
    expect(activeRow).toBeTruthy();
    expect(activeRow!).toHaveTextContent('Running step');
  });

  it('highlights the active step from todo.status', () => {
    render(<TodoList todos={[todo({ id: 'p0', text: 'In-flight', status: 'in_progress' })]} />);
    const row = screen.getByTestId('todo-row');
    expect(row.getAttribute('data-active')).toBe('true');
  });

  it('does not mark a completed step as active', () => {
    render(
      <TodoList
        todos={[todo({ id: 'p0', text: 'Done step', completed: true, status: 'running' })]}
      />,
    );
    const row = screen.getByTestId('todo-row');
    expect(row.getAttribute('data-active')).toBeNull();
  });

  it('toggles a todo on click', () => {
    const toggled: Array<[string, boolean]> = [];
    render(
      <TodoList
        todos={[todo({ id: 'p0', text: 'Toggle me' })]}
        onToggle={(id, c) => toggled.push([id, c])}
      />,
    );
    fireEvent.click(screen.getByText('Toggle me'));
    expect(toggled).toEqual([['p0', true]]);
  });
});
