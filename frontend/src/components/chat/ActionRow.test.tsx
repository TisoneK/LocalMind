import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import { ActionRows } from './ActionRow';
import type { ToolCall } from '@/types';

const call = (o: Partial<ToolCall> = {}): ToolCall => ({
  id: 't1',
  name: 'shell',
  label: 'Running command',
  status: 'done',
  input: 'echo hello',
  output: 'hello',
  duration: 500,
  ...o,
});

describe('ActionRows', () => {
  it('renders each action as its own row, collapsed by default', () => {
    render(
      <ActionRows
        toolCalls={[call({ id: 'a', label: 'Running command' }), call({ id: 'b', name: 'web_search', label: 'Searching web' })]}
      />,
    );
    // Two independent rows.
    expect(document.querySelectorAll('[data-tool-row]')).toHaveLength(2);
    // Collapsed: bodies (the command output) are NOT in the DOM yet.
    expect(screen.queryByText('hello')).not.toBeInTheDocument();
    // Headers use the verb + label.
    expect(screen.getByText('Running command')).toBeInTheDocument();
    expect(screen.getByText('Searching web')).toBeInTheDocument();
  });

  it('expands a row on click and collapses it again', () => {
    render(<ActionRows toolCalls={[call({ id: 'a' })]} />);
    const header = screen.getByRole('button');
    expect(header).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(header);
    expect(header).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('hello')).toBeInTheDocument(); // body now shown
    fireEvent.click(header);
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('hello')).not.toBeInTheDocument();
  });

  it('renders a diff-style body when the output looks like a unified diff', () => {
    const diff = 'ctx line\n- removed line\n+ added line';
    render(<ActionRows toolCalls={[call({ id: 'a', name: 'edit_file', label: 'Editing file', output: diff })]} />);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByText('- removed line')).toHaveClass('bg-brand-gh-red-bg');
    expect(screen.getByText('+ added line')).toHaveClass('bg-brand-gh-green-bg');
  });

  it('opens and reveals the matching row when a focus signal arrives', () => {
    const calls = [call({ id: 'a' }), call({ id: 'b', label: 'Second' })];
    const { rerender } = render(<ActionRows toolCalls={calls} focusSignal={null} />);
    expect(screen.queryByText('hello')).not.toBeInTheDocument();
    rerender(<ActionRows toolCalls={calls} focusSignal={{ toolId: 'b', at: 1 }} />);
    // Row "b" is now open (its body renders). Row "a" stays collapsed.
    const rowB = document.querySelector('[data-tool-row="b"]') as HTMLElement;
    expect(within(rowB).getByText('hello')).toBeInTheDocument();
  });

  it('is not expandable when the action has no body detail', () => {
    render(<ActionRows toolCalls={[call({ id: 'a', reasoning: '', input: '', output: '', error: '' })]} />);
    const header = screen.getByRole('button');
    expect(header).toBeDisabled();
    fireEvent.click(header);
    expect(header).toHaveAttribute('aria-expanded', 'false');
  });
});
