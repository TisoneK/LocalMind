import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ErrorMessage } from './ErrorMessage';
import type { ModelError } from '@/types';

const RATE_LIMIT: ModelError = {
  status: 'error',
  source: 'model_provider',
  provider: 'zen',
  code: 'rate_limit',
  message: 'The model provider has temporarily reached its usage limit. Try again in a few minutes or switch to another model.',
  retryable: true,
  raw: 'zen returned 429: {"type":"error"}',
};

describe('ErrorMessage (ADR-20)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the friendly headline + message — never the raw payload', () => {
    render(<ErrorMessage error={RATE_LIMIT} />);

    expect(screen.getByText('Unable to get a response')).toBeInTheDocument();
    expect(screen.getByText(RATE_LIMIT.message)).toBeInTheDocument();
    // Raw provider JSON is NOT visible by default — it sits inside the
    // collapsed <details> (in the DOM but never rendered visually).
    const raw = screen.getByText(/zen returned 429/);
    expect(raw.closest('details')).not.toHaveAttribute('open');
  });

  it('shows provider, status label and retryable badge', () => {
    render(<ErrorMessage error={RATE_LIMIT} />);

    expect(screen.getByText('zen')).toBeInTheDocument();
    expect(screen.getByText('Rate limit reached')).toBeInTheDocument();
    expect(screen.getByText('Retryable')).toBeInTheDocument();
  });

  it('marks non-retryable errors as Not retryable', () => {
    render(
      <ErrorMessage
        error={{ ...RATE_LIMIT, code: 'auth_error', retryable: false }}
      />
    );
    expect(screen.getByText('Not retryable')).toBeInTheDocument();
    expect(screen.getByText('Authentication failed')).toBeInTheDocument();
  });

  it('Try again calls onRetry when provided, and is hidden without it', () => {
    const onRetry = vi.fn();
    const { unmount } = render(<ErrorMessage error={RATE_LIMIT} onRetry={onRetry} />);
    fireEvent.click(screen.getByText('Try again'));
    expect(onRetry).toHaveBeenCalledTimes(1);
    unmount();

    render(<ErrorMessage error={RATE_LIMIT} />);
    expect(screen.queryByText('Try again')).not.toBeInTheDocument();
  });

  it('Switch model dispatches localmind:open-model-selector', () => {
    const dispatchSpy = vi
      .spyOn(window, 'dispatchEvent')
      .mockImplementation(() => true);

    render(<ErrorMessage error={RATE_LIMIT} />);
    fireEvent.click(screen.getByText('Switch model'));

    const dispatched = dispatchSpy.mock.calls.find(
      ([event]) => event.type === 'localmind:open-model-selector'
    );
    expect(dispatched).toBeTruthy();
  });

  it('exposes the raw payload only inside the collapsed technical details', () => {
    render(<ErrorMessage error={RATE_LIMIT} />);

    const summary = screen.getByText('Technical details');
    expect(summary).toBeInTheDocument();
    // Expand it and the raw string appears.
    fireEvent.click(summary);
    expect(screen.getByText(/zen returned 429: {"type":"error"}/)).toBeInTheDocument();
  });
});
