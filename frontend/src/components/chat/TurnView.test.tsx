import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
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
    // The live status line and the running step both name it.
    expect(screen.getAllByText('Running command').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('Plan 2/2')).toBeInTheDocument();
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

  it('explains a blocked shell call and opens Settings from the tip', () => {
    const onOpen = vi.fn();
    window.addEventListener('localmind:open-settings', onOpen);
    render(
      <TurnView
        message={{ toolCalls: [tool('a', { status: 'failed', output: 'Shell tool is disabled by configuration' })] }}
      />,
    );
    fireEvent.click(screen.getByText('Ran 1 tool · 1 failed'));
    expect(screen.getByTestId('shell-disabled-tip')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open Settings' }));
    expect(onOpen).toHaveBeenCalledTimes(1);
    window.removeEventListener('localmind:open-settings', onOpen);
  });

  it('opens the file preview from a written file path', () => {
    const onPreview = vi.fn();
    window.addEventListener('localmind:open-file-preview', onPreview);
    render(
      <TurnView
        message={{ toolCalls: [tool('a', { name: 'file_write', input: '/w/out.txt:\nhi', output: 'Wrote 2 bytes' })] }}
      />,
    );
    fireEvent.click(screen.getByText('Ran 1 tool'));
    fireEvent.click(screen.getByText('Created file'));
    fireEvent.click(screen.getByTitle('Preview /w/out.txt'));
    expect(onPreview).toHaveBeenCalledTimes(1);
    expect((onPreview.mock.calls[0][0] as CustomEvent).detail).toBe('/w/out.txt');
    window.removeEventListener('localmind:open-file-preview', onPreview);
  });

  it('keeps the total time in the header once the turn is done', () => {
    render(
      <TurnView
        message={{
          toolCalls: [tool('a'), tool('b')],
          performance: { latencyMs: 4800 } as never,
        }}
      />,
    );
    expect(screen.getByText(/Ran 2 tools · 4\.8s/)).toBeInTheDocument();
  });

  it('carries the live clock into the finished header when no measured latency exists yet', () => {
    const { rerender } = render(<TurnView isStreaming message={{ toolCalls: [tool('a', { status: 'running' })] }} />);
    rerender(<TurnView message={{ toolCalls: [tool('a')] }} />);
    // No measured latency and no elapsed time yet: nothing invented.
    expect(screen.queryByText(/·\s+\d/)).toBeNull();
  });
});

describe('TurnView outcome truth (§U item 3)', () => {
  it('a failed turn keeps the plan fraction but names the outcome on the pill', () => {
    const error = { code: 'payment_required', message: 'balance empty', retryable: false };
    render(
      <TurnView
        message={{ toolCalls: [tool('a')], error } as never}
        todos={[
          { id: 'plan-1', text: 'one', completed: true, order: 0 },
          { id: 'plan-2', text: 'two', completed: false, order: 1 },
          { id: 'plan-3', text: 'three', completed: false, order: 2 },
        ]}
      />,
    );
    expect(screen.getByText("1/3 plan · didn't finish")).toBeInTheDocument();
    // The header itself reads as failed (red X), not a green "Ran 1 tool".
    const view = screen.getByTestId('turn-view');
    expect(view).toHaveAttribute('data-state', 'failed');
  });

  it('a successful turn keeps the plain plan pill', () => {
    render(
      <TurnView
        message={{ toolCalls: [tool('a')] }}
        todos={[
          { id: 'plan-1', text: 'one', completed: true, order: 0 },
          { id: 'plan-2', text: 'two', completed: false, order: 1 },
        ]}
      />,
    );
    expect(screen.getByText('1/2 plan')).toBeInTheDocument();
  });

  it('expands a retried tool into its attempt ledger', () => {
    render(
      <TurnView
        message={{
          toolCalls: [
            tool('a', {
              retryCount: 2,
              retryAttempts: [
                { attempt: 1, error: 'connection refused', waited_ms: 500 },
                { attempt: 2, error: 'timeout', waited_ms: 1000 },
              ],
            }),
          ],
        }}
      />,
    );
    // Open the folded turn group, then the tool row itself.
    fireEvent.click(screen.getByText('Ran 1 tool'));
    expect(screen.getByText('2 retries')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Ran command'));
    const ledger = screen.getByTestId('retry-ledger');
    expect(ledger).toHaveTextContent('Attempt 1 failed: connection refused');
    expect(ledger).toHaveTextContent('Attempt 2 failed: timeout');
  });

  it('a first-try tool renders no retry ledger', () => {
    const { container } = render(<TurnView message={{ toolCalls: [tool('a')] }} />);
    fireEvent.click(screen.getByText('Ran 1 tool'));
    expect(container.querySelector('[data-testid="retry-ledger"]')).toBeNull();
  });
});
