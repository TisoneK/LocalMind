import { describe, expect, it, vi, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AppErrorBoundary } from './AppErrorBoundary';

function Boom(): never {
  throw new Error('kaboom');
}

describe('AppErrorBoundary', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('shows the error and a Reload button instead of a blank screen', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('kaboom');
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
  });

  it('renders children normally', () => {
    render(<AppErrorBoundary>hello</AppErrorBoundary>);
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('Copy details writes a paste-ready crash report', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(
      <AppErrorBoundary>
        <Boom />
      </AppErrorBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Copy details' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument());
    expect(writeText).toHaveBeenCalledOnce();
    expect(writeText.mock.calls[0][0]).toContain('Error: kaboom');
    expect(writeText.mock.calls[0][0]).toContain('Component stack:');
  });
});
