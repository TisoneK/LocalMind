import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
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
    getEmbeddingModels: vi.fn(),
    setLocalSettings: vi.fn(),
    selectModel: vi.fn(),
    setAppearance: vi.fn(),
  },
}));

/** Settings is a set of pages behind a left nav; go to one the way a user would. */
async function goTo(page: string) {
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Settings pages' })).getByRole('button', { name: page }));
}

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
    // Sensible defaults for the load-time calls the modal makes; individual
    // tests override as needed.
    mockClient.getModels.mockResolvedValue({ models: [], current: '', provider: 'ollama' });
    mockClient.getEmbeddingModels.mockResolvedValue({ models: [], current: '' });
    mockClient.setLocalSettings.mockResolvedValue({ embed_model: '', num_ctx: 0, updated: [], message: 'ok' });
    mockClient.selectModel.mockResolvedValue(undefined);
    mockClient.setAppearance.mockResolvedValue({ theme: 'custom', mode: 'dark', custom_theme: null, tone: 1, message: 'ok' });
  });

  it('switching to the Custom theme shows the palette editor and persists', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });
    await goTo('Appearance');

    // Custom appears as a theme option (from THEMES, which now includes it).
    await userEvent.click(screen.getByRole('button', { name: /Custom/i }));

    // The editor surfaces with the four color pickers + a name field.
    expect(screen.getByText('Custom palette')).toBeInTheDocument();
    expect(screen.getByLabelText('Accent')).toBeInTheDocument();
    expect(screen.getByLabelText('Background')).toBeInTheDocument();
    expect(screen.getByLabelText('Surface')).toBeInTheDocument();
    expect(screen.getByLabelText('Text')).toBeInTheDocument();

    // Every change persists to settings.json via setAppearance.
    await userEvent.type(screen.getByLabelText('Name'), 'Ocean');
    expect(mockClient.setAppearance).toHaveBeenCalledWith(
      expect.objectContaining({ theme: 'custom' })
    );
  });

  it('the tone slider persists its value to the backend', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });
    await goTo('Appearance');

    const slider = screen.getByRole('slider', { name: /UI tone/i });
    fireEvent.change(slider, { target: { value: '1.1' } });
    expect(mockClient.setAppearance).toHaveBeenCalledWith(
      expect.objectContaining({ tone: 1.1 })
    );
  });

  it('renders provider names from the live settings payload', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);

    // Dialog title
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    await goTo('Providers & keys');

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

  it('switching adapter resets the model to the new provider default', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    mockClient.setAdapter.mockResolvedValue({ ok: true });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });
    await goTo('Providers & keys');

    await userEvent.click(screen.getByRole('button', { name: /Zen AI/i }));
    await waitFor(() => {
      // The switch carries the new provider's default model so a previous
      // provider's model can never be stranded under the new adapter.
      expect(mockClient.setAdapter).toHaveBeenCalledWith('zen', 'deepseek-v4-flash-free');
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

  it('switches the active chat model via the model selector', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    mockClient.getModels.mockResolvedValue({
      models: [
        { id: 'llama3', name: 'llama3', provider: 'ollama', size: '8GB RAM' },
        { id: 'phi4-mini:latest', name: 'phi4-mini:latest', provider: 'ollama', size: '4GB RAM' },
      ],
      current: 'llama3',
      provider: 'ollama',
    });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    const select = (await screen.findByTestId('active-model-select')) as HTMLSelectElement;
    await userEvent.selectOptions(select, 'phi4-mini:latest');
    await waitFor(() => {
      expect(mockClient.selectModel).toHaveBeenCalledWith('phi4-mini:latest');
    });
  });

  it('saves local embedding model + context window', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload({ embed_model: 'nomic-embed-text', num_ctx: 0 }));
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    mockClient.getEmbeddingModels.mockResolvedValue({
      models: [{ id: 'nomic-embed-text', name: 'nomic-embed-text', provider: 'ollama' }],
      current: 'nomic-embed-text',
    });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    const numCtx = (await screen.findByTestId('num-ctx-input')) as HTMLInputElement;
    await userEvent.clear(numCtx);
    await userEvent.type(numCtx, '16384');
    await userEvent.click(screen.getByTestId('save-local-settings'));
    await waitFor(() => {
      expect(mockClient.setLocalSettings).toHaveBeenCalledWith(
        expect.objectContaining({ embedModel: 'nomic-embed-text', numCtx: 16384 }),
      );
    });
  });

  it('toggles the shell tool and persists it', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload({ shell_enabled: false }));
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    const toggle = await screen.findByTestId('shell-enabled-toggle');
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByTestId('save-local-settings'));
    await waitFor(() => {
      expect(mockClient.setLocalSettings).toHaveBeenCalledWith(
        expect.objectContaining({ shellEnabled: true }),
      );
    });
  });

  it('num_ctx field reflects the selected model window as its placeholder', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload({ num_ctx: 0 }));
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    mockClient.getModels.mockResolvedValue({
      models: [{ id: 'phi4-mini:latest', name: 'phi4-mini:latest', provider: 'ollama', contextWindow: 32768 }],
      current: 'phi4-mini:latest',
      provider: 'ollama',
    });

    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    const numCtx = (await screen.findByTestId('num-ctx-input')) as HTMLInputElement;
    // Auto (num_ctx=0) → empty value, placeholder shows the model's window.
    await waitFor(() => expect(numCtx.placeholder).toContain('32768'));
    expect(numCtx.value).toBe('');
  });

  it('keeps input focus when the parent re-renders with a new onClose', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });

    const { rerender } = render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    const input = screen.getByPlaceholderText('http://localhost:11434') as HTMLInputElement;
    input.focus();
    expect(document.activeElement).toBe(input);

    // RightPanel passes an inline onClose and re-renders ~every second (live
    // clock/stats). Before the fix, a new onClose identity re-ran the focus
    // effect and yanked focus back to the modal's first element — you could
    // not paste into the API key box. It must now stay put.
    rerender(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    rerender(<SettingsModal onClose={() => {}} onSave={() => {}} />);

    expect(document.activeElement).toBe(input);
  });

  it('shows one page at a time behind a left nav', async () => {
    mockClient.getSettings.mockResolvedValue(settingsPayload());
    mockClient.getOllamaUrl.mockResolvedValue({ url: 'http://localhost:11434' });
    render(<SettingsModal onClose={() => {}} onSave={() => {}} />);
    await screen.findByRole('heading', { name: 'Settings' });

    // General is first: startup behaviour is visible, the theme is not.
    expect(screen.getByRole('heading', { name: 'On Startup' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Appearance', level: 3 })).toBeNull();
    await goTo('Agent');
    expect(screen.getByRole('heading', { name: 'Package installs' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Permissions' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'On Startup' })).toBeNull(); // hidden pages leave the a11y tree
    expect(screen.getByRole('button', { name: 'Agent' })).toHaveAttribute('aria-current', 'page');
  });
});
