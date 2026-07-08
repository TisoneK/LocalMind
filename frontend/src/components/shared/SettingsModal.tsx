'use client';

import { useState, useEffect, useCallback } from 'react';
import { X, Server, Key, Loader2, CheckCircle2, AlertCircle, Trash2 } from 'lucide-react';
import { localmindClient } from '@/lib/localmind/client';

// ── Provider definitions (mirrors backend PROVIDER_INFO in config.py) ──

interface ProviderDef {
  id: string;
  name: string;
  defaultModel: string;
}

const PROVIDERS: ProviderDef[] = [
  { id: 'openai', name: 'OpenAI', defaultModel: 'gpt-4o-mini' },
  { id: 'anthropic', name: 'Anthropic', defaultModel: 'claude-3-5-sonnet-20241022' },
  { id: 'openrouter', name: 'OpenRouter', defaultModel: 'openrouter/auto' },
  { id: 'deepseek', name: 'DeepSeek', defaultModel: 'deepseek-chat' },
  { id: 'groq', name: 'Groq', defaultModel: 'llama-3.1-70b-versatile' },
  { id: 'together', name: 'Together AI', defaultModel: 'meta-llama/Llama-3.1-70B-Instruct-Turbo' },
  { id: 'fireworks', name: 'Fireworks AI', defaultModel: 'accounts/fireworks/models/llama-v3-70b-instruct' },
  { id: 'deepinfra', name: 'DeepInfra', defaultModel: 'meta-llama/Llama-3.1-70B-Instruct' },
  { id: 'mistral', name: 'Mistral AI', defaultModel: 'mistral-large-latest' },
  { id: 'cohere', name: 'Cohere', defaultModel: 'command-r-plus' },
  { id: 'vercel', name: 'Vercel AI Gateway', defaultModel: 'gpt-4o-mini' },
  { id: 'cloudflare', name: 'Cloudflare AI Gateway', defaultModel: '@cf/meta/llama-3.1-70b-instruct' },
  { id: 'lite-llm', name: 'LiteLLM Proxy', defaultModel: 'gpt-4' },
  { id: 'zen', name: 'Zen AI', defaultModel: 'gpt-4o-mini' },
];

interface SettingsModalProps {
  onClose: () => void;
  onSave: () => void;
}

type Status = 'idle' | 'saving' | 'success' | 'error';

export function SettingsModal({ onClose, onSave }: SettingsModalProps) {
  const [adapter, setAdapter] = useState('ollama');
  const [model, setModel] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434');
  const [providerKeys, setProviderKeys] = useState<Record<string, boolean>>({});
  const [newKeyProvider, setNewKeyProvider] = useState('');
  const [newKeyValue, setNewKeyValue] = useState('');
  const [newKeyModel, setNewKeyModel] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);

  // Load current settings on mount
  useEffect(() => {
    (async () => {
      try {
        const settings = await localmindClient.getSettings();
        setAdapter(settings.adapter);
        setModel(settings.model);
        // Build provider key status from providers object
        const keyStatus: Record<string, boolean> = {};
        if (settings.providers) {
          for (const [id, info] of Object.entries(settings.providers) as [string, any][]) {
            keyStatus[id] = info?.api_key_set ?? false;
          }
        }
        setProviderKeys(keyStatus);
        // Load Ollama URL if using ollama adapter
        if (settings.adapter === 'ollama') {
          try {
            const urlInfo = await localmindClient.getOllamaUrl();
            setOllamaUrl(urlInfo.url);
          } catch {
            // Non-fatal: ollama routes may 501 for cloud adapters
          }
        }
      } catch (err) {
        setStatus('error');
        setMessage(err instanceof Error ? err.message : 'Failed to load settings');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleAdapterSwitch = useCallback(async (newAdapter: string) => {
    setAdapter(newAdapter);
    setStatus('saving');
    setMessage(`Switching to ${newAdapter}...`);
    try {
      await localmindClient.setAdapter(newAdapter);
      setStatus('success');
      setMessage(`Switched to ${newAdapter} adapter`);
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to switch adapter');
    }
  }, [onSave]);

  const handleSaveKey = useCallback(async () => {
    if (!newKeyProvider || !newKeyValue.trim()) {
      setStatus('error');
      setMessage('Select a provider and enter an API key');
      return;
    }
    setStatus('saving');
    setMessage(`Saving key for ${newKeyProvider}...`);
    try {
      await localmindClient.setProviderKey(newKeyProvider, newKeyValue.trim(), newKeyModel || undefined);
      setProviderKeys((prev) => ({ ...prev, [newKeyProvider]: true }));
      setNewKeyValue('');
      setNewKeyModel('');
      setStatus('success');
      setMessage(`API key saved for ${newKeyProvider}`);
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to save API key');
    }
  }, [newKeyProvider, newKeyValue, newKeyModel, onSave]);

  const handleDeleteKey = useCallback(async (provider: string) => {
    setStatus('saving');
    setMessage(`Removing key for ${provider}...`);
    try {
      await localmindClient.deleteProviderKey(provider);
      setProviderKeys((prev) => ({ ...prev, [provider]: false }));
      setStatus('success');
      setMessage(`API key removed for ${provider}`);
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to delete API key');
    }
  }, []);

  const handleSaveOllamaUrl = useCallback(async () => {
    setStatus('saving');
    setMessage('Validating Ollama URL...');
    try {
      const result = await localmindClient.setOllamaUrl(ollamaUrl);
      if (result.reachable) {
        setStatus('success');
        setMessage(`Ollama URL updated: ${result.url}`);
        onSave();
      } else {
        setStatus('error');
        setMessage(`URL saved but not reachable: ${result.message}`);
      }
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to update Ollama URL');
    }
  }, [ollamaUrl, onSave]);

  const handleResetOllamaUrl = useCallback(async () => {
    setStatus('saving');
    setMessage('Resetting Ollama URL...');
    try {
      await localmindClient.resetOllamaUrl();
      setOllamaUrl('http://localhost:11434');
      setStatus('success');
      setMessage('Ollama URL reset to localhost');
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to reset Ollama URL');
    }
  }, []);

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="flex items-center gap-3 text-[#8ab08a]">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Loading settings...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl border border-[#1a2a1a] bg-[#0d140d] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-[#1a2a1a] bg-[#0d140d] px-6 py-4">
          <h2 className="text-lg font-semibold text-[#d4e8d4]">Settings</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-[#8ab08a] hover:bg-[#1a2a1a] hover:text-[#d4e8d4] transition-colors"
            title="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-6 px-6 py-5">
          {/* Status message */}
          {status !== 'idle' && message && (
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                status === 'saving'
                  ? 'border-[#e8a420]/30 bg-[#e8a420]/5 text-[#e8a420]'
                  : status === 'success'
                  ? 'border-[#39d353]/30 bg-[#39d353]/5 text-[#39d353]'
                  : 'border-[#e05555]/30 bg-[#e05555]/5 text-[#e05555]'
              }`}
            >
              {status === 'saving' && <Loader2 className="h-4 w-4 animate-spin shrink-0" />}
              {status === 'success' && <CheckCircle2 className="h-4 w-4 shrink-0" />}
              {status === 'error' && <AlertCircle className="h-4 w-4 shrink-0" />}
              <span>{message}</span>
            </div>
          )}

          {/* ── Adapter Selection ── */}
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-[#d4e8d4]">
              <Server className="h-4 w-4 text-[#39d353]" />
              AI Provider
            </h3>
            <p className="mb-3 text-xs text-[#8ab08a]">
              Choose between local Ollama or a cloud provider. Cloud providers require an API key below.
            </p>
            <div className="grid grid-cols-3 gap-2">
              <button
                onClick={() => handleAdapterSwitch('ollama')}
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                  adapter === 'ollama'
                    ? 'border-[#39d353] bg-[#39d353]/10 text-[#39d353]'
                    : 'border-[#1a2a1a] text-[#8ab08a] hover:border-[#39d353]/30 hover:text-[#d4e8d4]'
                }`}
              >
                Ollama (Local)
              </button>
              {PROVIDERS.slice(0, 8).map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleAdapterSwitch(p.id)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    adapter === p.id
                      ? 'border-[#39d353] bg-[#39d353]/10 text-[#39d353]'
                      : 'border-[#1a2a1a] text-[#8ab08a] hover:border-[#39d353]/30 hover:text-[#d4e8d4]'
                  }`}
                >
                  {p.name}
                </button>
              ))}
            </div>
            {PROVIDERS.length > 8 && (
              <select
                value={adapter.startsWith('ollama') ? '' : adapter}
                onChange={(e) => e.target.value && handleAdapterSwitch(e.target.value)}
                className="mt-2 w-full rounded-lg border border-[#1a2a1a] bg-[#0a0f0a] px-3 py-2 text-sm text-[#d4e8d4] focus:border-[#39d353] outline-none"
              >
                <option value="">More providers...</option>
                {PROVIDERS.slice(8).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            {adapter !== 'ollama' && (
              <p className="mt-2 text-xs text-[#8ab08a]">
                Current model: <span className="font-mono text-[#d4e8d4]">{model || 'default'}</span>
              </p>
            )}
          </section>

          {/* ── Ollama URL Configuration ── */}
          {adapter === 'ollama' && (
            <section>
              <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-[#d4e8d4]">
                <Server className="h-4 w-4 text-[#39d353]" />
                Ollama Server URL
              </h3>
              <p className="mb-3 text-xs text-[#8ab08a]">
                Point LocalMind at a local or remote Ollama instance. The URL is validated before saving.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                  className="flex-1 rounded-lg border border-[#1a2a1a] bg-[#0a0f0a] px-3 py-2 text-sm text-[#d4e8d4] font-mono focus:border-[#39d353] outline-none"
                />
                <button
                  onClick={handleSaveOllamaUrl}
                  disabled={status === 'saving'}
                  className="rounded-lg border border-[#39d353]/30 bg-[#39d353]/10 px-4 py-2 text-sm font-medium text-[#39d353] hover:bg-[#39d353]/20 transition-colors disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  onClick={handleResetOllamaUrl}
                  disabled={status === 'saving'}
                  className="rounded-lg border border-[#1a2a1a] px-3 py-2 text-sm text-[#8ab08a] hover:text-[#d4e8d4] hover:border-[#39d353]/30 transition-colors disabled:opacity-50"
                  title="Reset to localhost"
                >
                  Reset
                </button>
              </div>
            </section>
          )}

          {/* ── API Key Management ── */}
          {adapter !== 'ollama' && (
            <section>
              <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-[#d4e8d4]">
                <Key className="h-4 w-4 text-[#39d353]" />
                API Keys
              </h3>
              <p className="mb-3 text-xs text-[#8ab08a]">
                Keys are stored locally in <code className="text-[#d4e8d4]">~/LocalMind/settings.json</code> with
                restricted file permissions. They never leave your machine.
              </p>

              {/* Stored keys list */}
              <div className="mb-4 space-y-1.5">
                {PROVIDERS.map((p) => {
                  const hasKey = providerKeys[p.id];
                  return (
                    <div
                      key={p.id}
                      className="flex items-center justify-between rounded-lg border border-[#1a2a1a] px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-[#d4e8d4]">{p.name}</span>
                        {hasKey ? (
                          <span className="flex items-center gap-1 text-xs text-[#39d353]">
                            <CheckCircle2 className="h-3 w-3" />
                            Key set
                          </span>
                        ) : (
                          <span className="text-xs text-[#8ab08a]">No key</span>
                        )}
                      </div>
                      {hasKey && (
                        <button
                          onClick={() => handleDeleteKey(p.id)}
                          disabled={status === 'saving'}
                          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-[#e05555] hover:bg-[#e05555]/10 transition-colors disabled:opacity-50"
                          title={`Remove ${p.name} API key`}
                        >
                          <Trash2 className="h-3 w-3" />
                          Remove
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Add new key */}
              <div className="rounded-lg border border-[#1a2a1a] p-3">
                <div className="mb-2 text-xs font-medium text-[#8ab08a]">Add or update a key:</div>
                <div className="space-y-2">
                  <select
                    value={newKeyProvider}
                    onChange={(e) => setNewKeyProvider(e.target.value)}
                    className="w-full rounded-lg border border-[#1a2a1a] bg-[#0a0f0a] px-3 py-2 text-sm text-[#d4e8d4] focus:border-[#39d353] outline-none"
                  >
                    <option value="">Select provider...</option>
                    {PROVIDERS.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <input
                    type="password"
                    value={newKeyValue}
                    onChange={(e) => setNewKeyValue(e.target.value)}
                    placeholder="API key"
                    className="w-full rounded-lg border border-[#1a2a1a] bg-[#0a0f0a] px-3 py-2 text-sm text-[#d4e8d4] font-mono focus:border-[#39d353] outline-none"
                  />
                  <input
                    type="text"
                    value={newKeyModel}
                    onChange={(e) => setNewKeyModel(e.target.value)}
                    placeholder={`Model (optional, default: ${
                      PROVIDERS.find((p) => p.id === newKeyProvider)?.defaultModel || ''
                    })`}
                    className="w-full rounded-lg border border-[#1a2a1a] bg-[#0a0f0a] px-3 py-2 text-sm text-[#d4e8d4] focus:border-[#39d353] outline-none"
                  />
                  <button
                    onClick={handleSaveKey}
                    disabled={status === 'saving' || !newKeyProvider || !newKeyValue.trim()}
                    className="w-full rounded-lg border border-[#39d353]/30 bg-[#39d353]/10 px-4 py-2 text-sm font-medium text-[#39d353] hover:bg-[#39d353]/20 transition-colors disabled:opacity-50"
                  >
                    Save Key
                  </button>
                </div>
              </div>
            </section>
          )}

          {/* ── Footer ── */}
          <div className="flex justify-end border-t border-[#1a2a1a] pt-4">
            <button
              onClick={onClose}
              className="rounded-lg border border-[#1a2a1a] px-4 py-2 text-sm text-[#8ab08a] hover:text-[#d4e8d4] hover:border-[#39d353]/30 transition-colors"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
