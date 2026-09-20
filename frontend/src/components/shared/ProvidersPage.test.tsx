import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ProvidersPage, providerHealth, splitProviders } from './ProvidersPage';
import { localmindClient } from '@/lib/localmind/client';

const conn = (over: Record<string, unknown> = {}) => ({
  id: 'deepseek',
  name: 'DeepSeek',
  kind: 'openai-compat',
  base_url: 'https://api.deepseek.com/v1',
  model: 'deepseek-chat',
  protocol: 'openai',
  capabilities: {},
  enabled: true,
  fallback_to: '',
  extra_models: [],
  hidden_models: [],
  preset: true,
  api_key_set: true,
  ...over,
});

const list = [
  conn(),
  conn({ id: 'atria', name: 'Atria-Dawn', preset: false, base_url: 'http://localhost:4000/v1', api_key_set: true }),
  conn({ id: 'openai', name: 'OpenAI', api_key_set: false }),
  conn({ id: 'ollama', name: 'Ollama (local)', kind: 'ollama', api_key_set: false }),
];

function setup(conns = list, active = 'deepseek') {
  vi.spyOn(localmindClient, 'getSettings').mockResolvedValue({ adapter: active, connections: conns } as never);
  vi.spyOn(localmindClient, 'getModels').mockResolvedValue({
    current: 'deepseek-chat',
    provider: 'deepseek',
    models: [
      { id: 'deepseek-chat', name: 'deepseek-chat', provider: 'deepseek' },
      { id: 'deepseek-flash', name: 'deepseek-flash', provider: 'deepseek' },
    ],
  } as never);
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.restoreAllMocks());

describe('provider grouping', () => {
  it('reads health from the switch and the key', () => {
    expect(providerHealth({ enabled: false, api_key_set: true, kind: 'openai-compat' })).toBe('off');
    expect(providerHealth({ enabled: true, api_key_set: false, kind: 'openai-compat' })).toBe('needs-key');
    expect(providerHealth({ enabled: true, api_key_set: false, kind: 'ollama' })).toBe('ready');
  });

  it('puts what you have set up first and the rest of the built-ins under More', () => {
    const { mine, more } = splitProviders(list as never, 'deepseek');
    expect(mine.map((c) => c.id)).toEqual(['deepseek', 'atria', 'ollama']);
    expect(more.map((c) => c.id)).toEqual(['openai']);
  });
});

describe('ProvidersPage', () => {
  it('lists providers on the left and shows the selected one on the right', async () => {
    setup();
    render(<ProvidersPage />);
    const detail = await screen.findByTestId('provider-detail');
    expect(within(detail).getByText('DeepSeek')).toBeInTheDocument();
    expect(within(detail).getByLabelText('Base URL')).toHaveValue('https://api.deepseek.com/v1');
    expect(screen.getByText('Your providers')).toBeInTheDocument();
    expect(screen.getByText('More providers')).toBeInTheDocument();
    // The model list comes from the provider, with a switch per model.
    expect(await screen.findByText('deepseek-flash')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Show deepseek-flash in the model picker' })).toHaveAttribute('aria-checked', 'true');
  });

  it('turning a model off saves it as hidden', async () => {
    setup();
    const save = vi.spyOn(localmindClient, 'saveConnection').mockResolvedValue({ connection: conn() as never, message: 'ok' });
    render(<ProvidersPage />);
    fireEvent.click(await screen.findByRole('switch', { name: 'Show deepseek-flash in the model picker' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ id: 'deepseek', hidden_models: ['deepseek-flash'] }));
  });

  it('adds a model by hand', async () => {
    setup();
    const save = vi.spyOn(localmindClient, 'saveConnection').mockResolvedValue({ connection: conn() as never, message: 'ok' });
    render(<ProvidersPage />);
    const box = await screen.findByLabelText('Add a model id');
    fireEvent.change(box, { target: { value: 'my-finetune' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add model' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ id: 'deepseek', extra_models: ['my-finetune'] }));
  });

  it('saves a new key and reports whether it worked', async () => {
    setup();
    const setKey = vi.spyOn(localmindClient, 'setProviderKey').mockResolvedValue({ validated: true, validation_error: null, message: 'ok' });
    render(<ProvidersPage />);
    fireEvent.change(await screen.findByLabelText('API key'), { target: { value: 'sk-new' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save key' }));
    await waitFor(() => expect(setKey).toHaveBeenCalledWith('deepseek', 'sk-new'));
    expect(await screen.findByText('Key saved and working.')).toBeInTheDocument();
  });

  it('asks before deleting a custom provider and says what goes with it', async () => {
    setup();
    render(<ProvidersPage />);
    await screen.findByTestId('provider-detail');
    fireEvent.click(await screen.findByRole('button', { name: /Atria-Dawn/ }));
    const del = vi.spyOn(localmindClient, 'deleteConnection').mockResolvedValue({ connection: 'atria', deleted: true, adapter: 'deepseek', message: 'Deleted connection.' });
    fireEvent.click(await screen.findByRole('button', { name: /Delete provider/ }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/saved API key is removed/);
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(del).toHaveBeenCalledWith('atria'));
  });

  it('a preset is reset, not deleted, and keeps its key', async () => {
    setup();
    render(<ProvidersPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Reset to defaults/ }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent(/saved key stays/);
  });

  it('adds a custom provider from a name, an address and a model', async () => {
    setup();
    const create = vi.spyOn(localmindClient, 'saveConnection').mockResolvedValue({ connection: conn({ id: 'my-gateway' }) as never, message: 'ok' });
    render(<ProvidersPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Add provider/ }));
    const form = await screen.findByTestId('add-provider');
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'My gateway' } });
    fireEvent.change(within(form).getByLabelText('Base URL'), { target: { value: 'https://gw.example.com/v1' } });
    fireEvent.change(within(form).getByLabelText('Default model'), { target: { value: 'gw-1' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Add provider' }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({ id: 'my-gateway', name: 'My gateway', base_url: 'https://gw.example.com/v1', model: 'gw-1' }),
    );
  });

  it('will not add a provider whose name already exists', async () => {
    setup();
    render(<ProvidersPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Add provider/ }));
    const form = await screen.findByTestId('add-provider');
    fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'DeepSeek' } });
    fireEvent.change(within(form).getByLabelText('Base URL'), { target: { value: 'https://x.example/v1' } });
    fireEvent.change(within(form).getByLabelText('Default model'), { target: { value: 'm' } });
    expect(within(form).getByRole('button', { name: 'Add provider' })).toBeDisabled();
    expect(within(form).getByText(/already exists/)).toBeInTheDocument();
  });
});
