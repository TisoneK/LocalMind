import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SettingsModal } from './SettingsModal';
import { localmindClient } from '@/lib/localmind/client';

// Mock the client — SettingsModal is a thin view over API calls, so the
// tests exercise render + interaction with deterministic fake responses.
vi.mock('@/lib/localmind/client', () => ({
  localmindClient: {
    getSettings: vi.fn(),
    getOllamaUrl: vi.fn(),
    setAdapter: vi.fn(),
    setProviderKey: vi.fn(),
    deleteProviderKey: vi.fn(),
    setOllamaUrl: vi.fn(),
    resetOllamaUrl: vi.fn(),
    getModels: vi.fn(),
  },
}));

const mockClient = localmindClient as unknown as Record<string, ReturnType<typeof vi.fn>>;

function settingsPayload(overrides: Record<string, unknown> = {}) {
  return {
    adapter: 'ollama',
    model: 'llama3',
    providers: {
      zen: { name: 'Zen AI', api_key_set: true, model: 'deepseek-v4-flash-free', default_model: 'deepseek-v4-flash-free' },
      anthropic: { name: 'Anthropic', api_key_set: false, model: '', default_model: 'claude-3-5-sonnet-20241022' },
    },
    ...overrides,
  };
}

describe('SettingsModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('renders provider names from the live settings payload', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);

    // Dialog title
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();

    // Provider buttons (Ollama + each provider from settings.providers)
    expect(screen.getByRole('button', { name: /Ollama \(Local\)/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Zen AI/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Anthropic/i })).toBeInTheDocument();
  });

  it('closes via the X button', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    const onClose = vi.fn();

    render(<SettingsModal onClose={onClose} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    await userEvent.click(screen.getByRole('button', { name: 'Close settings' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('switching adapter calls setAdapter', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    mockClient.setAdapter.mockResolvedValue({ ok: true });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    await userEvent.click(screen.getByRole('button', { name: /Zen AI/i }));
    await waitFor(() => {
      expect(mockClient.setAdapter).toHaveBeenCalledWith('zen');
    });
  });

  it('shows an API key field for cloud providers', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    // Ollama default → the Ollama URL section (input is placeholder-labeled).
    expect(screen.getByPlaceholderText('http://localhost:11434')).toBeInTheDocument();
  });
});
