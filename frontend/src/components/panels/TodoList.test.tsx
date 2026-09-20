/**
 * Tests for TodoList.
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

  it('renders sub-goal rows nested under their parent without counting them', () => {
    // plan-{i}-sub-{j} rows are ordered guidance under the
    // parent goal — indented, informational, never part of the n/n
    // denominator (the parent plan rows own the fixed count).
    render(
      <TodoList
        todos={[
          todo({ id: 'plan-0', text: 'file exists at a.txt with content' }),
          todo({ id: 'plan-0-sub-0', text: 'check whether a.txt already exists' }),
          todo({ id: 'plan-0-sub-1', text: 'write a.txt with the full content' }),
          todo({ id: 'plan-0-sub-2', text: 'verify a.txt exists with the expected content' }),
          todo({ id: 'plan-1', text: 'folder created at path-test' }),
        ]}
      />,
    );
    // Parents render as rows; sub-goals render as sub-rows.
    expect(screen.getAllByTestId('todo-row')).toHaveLength(2);
    expect(screen.getAllByTestId('todo-subrow')).toHaveLength(3);
    expect(screen.getByText('write a.txt with the full content')).toBeInTheDocument();
    // The denominator stays 0/2 (sub-goals don't count).
    expect(screen.getByText('0/2')).toBeInTheDocument();
  });

  it('marks sub-goal rows complete with their parent and keeps 1/2', () => {
    render(
      <TodoList
        todos={[
          todo({ id: 'plan-0', text: 'file exists at a.txt with content', completed: true }),
          todo({ id: 'plan-0-sub-0', text: 'check whether a.txt already exists', completed: true }),
          todo({ id: 'plan-0-sub-1', text: 'write a.txt with the full content', completed: true }),
          todo({ id: 'plan-1', text: 'folder created at path-test' }),
        ]}
      />,
    );
    const subrows = screen.getAllByTestId('todo-subrow');
    expect(subrows).toHaveLength(2);
    expect(subrows.every((r) => r.getAttribute('data-completed') !== undefined)).toBe(true);
    expect(screen.getByText('1/2')).toBeInTheDocument();
  });
});

describe('TodoList when the turn is over', () => {
  it('marks an unchecked task as not finished instead of leaving an empty checkbox', () => {
    const todos = [
      { id: 'plan-0', text: 'Read the file', completed: true },
      { id: 'plan-1', text: 'Run ls', completed: false },
    ] as never;
    const { rerender } = render(<TodoList todos={todos} />);
    expect(screen.queryByTestId('todo-unfinished')).toBeNull();
    rerender(<TodoList todos={todos} settled />);
    expect(screen.getAllByTestId('todo-unfinished')).toHaveLength(1);
  });
});

describe('TodoList failed steps', () => {
  it('shows a step that did not work as failed, not as unfinished work', () => {
    const todos = [
      { id: 'syn-0', text: 'Fetch livescore.com — didn\'t work', completed: false, status: 'failed', order: 0 },
      { id: 'syn-1', text: 'Fetch espn.com', completed: true, order: 1 },
    ] as never;
    render(<TodoList todos={todos} settled />);
    expect(screen.getAllByTestId('todo-failed')).toHaveLength(1);
    expect(screen.queryByTestId('todo-unfinished')).toBeNull();
  });
});
