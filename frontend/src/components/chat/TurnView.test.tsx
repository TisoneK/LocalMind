import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TurnView } from './TurnView';
import type { ToolCall } from '@/types';

const tool = (id: string, over: Partial<ToolCall> = {}): ToolCall => ({
  id,
  name: 'shell',
  status: 'done',
  input: `cmd ${id}`,
  output: `out ${id}`,
  ...over,
});

describe('TurnView', () => {
  it('renders nothing for a plain finished reply', () => {
    const { container } = render(<TurnView message={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('is open with a live label while running', () => {
    render(
      <TurnView
        isStreaming
        message={{ toolCalls: [tool('a', { status: 'running' })] }}
        todos={[
          { id: '1', text: 'one', completed: true, order: 0 },
          { id: '2', text: 'two', completed: false, order: 1 },
        ]}
      />,
    );
    const view = screen.getByTestId('turn-view');
    expect(view).toHaveAttribute('data-state', 'running');
    expect(screen.getByText(/Working · 0s/)).toBeInTheDocument();
    expect(screen.getByText('Running command', { selector: 'span.text-brand-green-muted, span' })).toBeInTheDocument();
    expect(screen.getByText('Step 2/2')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Agent activity' })).toBeInTheDocument();
  });

  it('folds to a summary when finished and reopens on click', () => {
    render(<TurnView message={{ toolCalls: [tool('a'), tool('b', { status: 'failed' })] }} />);
    expect(screen.getByText('Ran 2 tools · 1 failed')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Agent activity' })).toBeNull();
    fireEvent.click(screen.getByText('Ran 2 tools · 1 failed'));
    expect(screen.getByRole('list', { name: 'Agent activity' })).toBeInTheDocument();
  });

  it('shows parallel tools side by side without a click', () => {
    render(
      <TurnView
        isStreaming
        message={{
          toolCalls: [
            tool('a', { iteration: 1, status: 'running' }),
            tool('b', { iteration: 1, status: 'running' }),
          ],
        }}
      />,
    );
    expect(screen.getByText('2 tools in parallel')).toBeInTheDocument();
    expect(screen.getByText('cmd a')).toBeInTheDocument();
    expect(screen.getByText('cmd b')).toBeInTheDocument();
  });
});
