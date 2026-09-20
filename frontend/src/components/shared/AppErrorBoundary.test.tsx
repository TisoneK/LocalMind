import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AppErrorBoundary } from './AppErrorBoundary';

function Boom(): never {
  throw new Error('kaboom');
}

describe('AppErrorBoundary', () => {
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
});
