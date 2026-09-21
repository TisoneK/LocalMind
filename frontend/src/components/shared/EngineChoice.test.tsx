/** The engine choice in Settings: it reflects the saved engine and announces a change to the app. */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EngineChoice } from './EngineChoice';
import { localmindClient } from '@/lib/localmind/client';

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: { getSettings: vi.fn(), setEngine: vi.fn() },
}));

const mockClient = localmindClient as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  mockClient.getSettings.mockResolvedValue({ engine: 'classic' });
  mockClient.setEngine.mockResolvedValue({ engine: 'state', message: 'Engine set to state' });
});

describe('EngineChoice', () => {
  it('starts on Classic and explains what the chosen engine does', async () => {
    render(<EngineChoice />);
    await waitFor(() => expect(screen.getByRole('radio', { name: 'Classic' })).toHaveAttribute('aria-checked', 'true'));
    expect(screen.getByRole('radio', { name: 'State (experimental)' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText(/parent agent/)).toBeInTheDocument();
  });

  it('saves State and tells the app so the explorer can take over without a reload', async () => {
    const seen: string[] = [];
    window.addEventListener('localmind:engine-changed', (e) => seen.push((e as CustomEvent<{ engine: string }>).detail.engine));
    render(<EngineChoice />);
    await waitFor(() => expect(mockClient.getSettings).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('radio', { name: 'State (experimental)' }));

    expect(mockClient.setEngine).toHaveBeenCalledWith('state');
    await waitFor(() => expect(screen.getByRole('radio', { name: 'State (experimental)' })).toHaveAttribute('aria-checked', 'true'));
    expect(seen).toEqual(['state']);
    expect(screen.getByText(/game tree instead of a chat/)).toBeInTheDocument();
  });

  it('reflects an engine chosen earlier', async () => {
    mockClient.getSettings.mockResolvedValue({ engine: 'state' });
    render(<EngineChoice />);
    await waitFor(() => expect(screen.getByRole('radio', { name: 'State (experimental)' })).toHaveAttribute('aria-checked', 'true'));
  });
});
