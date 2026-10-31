import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RecoveryBoundary } from './RecoveryBoundary';

function Boom(): never {
  throw new Error('kaboom');
}

/** jsdom marks Location unforgeable — spying on reload fails. Replace the
 *  whole location object instead; a fresh jsdom environment serves each test file. */
function stubLocationReload(): ReturnType<typeof vi.fn> {
  const reload = vi.fn();
  const w = window as unknown as { location: { reload: () => void } };
  Reflect.deleteProperty(w, 'location');
  Object.defineProperty(w, 'location', { value: { reload }, writable: true, configurable: true });
  return reload;
}

describe('RecoveryBoundary', () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
    vi.unstubAllGlobals();
  });

  it('renders children normally', () => {
    render(
      <RecoveryBoundary label="The side panel">
        <span>healthy</span>
      </RecoveryBoundary>,
    );
    expect(screen.getByText('healthy')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('replaces only its region with a crash card naming the region', () => {
    render(
      <div>
        <span>rest of the app</span>
        <RecoveryBoundary label="The side panel">
          <Boom />
        </RecoveryBoundary>
      </div>,
    );
    expect(screen.getByText('rest of the app')).toBeInTheDocument();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('The side panel hit a problem');
    expect(alert).toHaveTextContent('kaboom');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('Try again remounts the subtree without a page reload', () => {
    const reload = stubLocationReload();
    const { rerender } = render(
      <RecoveryBoundary label="The side panel">
        <Boom />
      </RecoveryBoundary>,
    );
    // The fix has landed upstream (rerender with healthy children) — Try again is enough.
    rerender(
      <RecoveryBoundary label="The side panel">
        <span>healthy again</span>
      </RecoveryBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText('healthy again')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(reload).not.toHaveBeenCalled();
  });

  it('says so when the region crashes twice in a row', () => {
    render(
      <RecoveryBoundary label="The side panel">
        <Boom />
      </RecoveryBoundary>,
    );
    expect(screen.queryByText(/This keeps happening here/)).toBeNull();
    // Try again with the child still broken: an immediate re-crash is the second one.
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(screen.getByText(/This keeps happening here/)).toBeInTheDocument();
  });

  it('Copy details writes a paste-ready report to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(
      <RecoveryBoundary label="The side panel">
        <Boom />
      </RecoveryBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Copy details' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument());
    expect(writeText).toHaveBeenCalledOnce();
    expect(writeText.mock.calls[0][0]).toContain('Error: kaboom');
    expect(writeText.mock.calls[0][0]).toContain('Component stack:');
  });

  it('lays the report out by hand when the clipboard refuses', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
    });
    render(
      <RecoveryBoundary label="The side panel">
        <Boom />
      </RecoveryBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Copy details' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copy details' })).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent('LocalMind crash report');
  });

  it('Full reload is the last resort and reloads the page', () => {
    const reload = stubLocationReload();
    render(
      <RecoveryBoundary label="The side panel">
        <Boom />
      </RecoveryBoundary>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Full reload' }));
    expect(reload).toHaveBeenCalledOnce();
  });
});
