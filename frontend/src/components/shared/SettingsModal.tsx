'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { X, Server, Key, Loader2, CheckCircle2, AlertCircle, Trash2, FileEdit, Palette, Sun, Moon, Monitor, Brain } from 'lucide-react';
import { localmindClient } from '@/lib/localmind/client';
import { useTheme, THEMES, type ModePref } from '@/hooks/useTheme';

// ── Provider definitions ──
// Only `id` and `name` (display label) are hardcoded here — these are
// stable UI strings. Model IDs are NEVER hardcoded: the live default for
// each provider comes from GET /api/settings (which reads the backend's
// PROVIDER_CONFIGS), and the full model list comes from GET /api/models?provider=...
// This way, when a provider deprecates a model, only the backend needs
// updating and the frontend follows automatically.

interface ProviderDef {
  id: string;
  name: string;
}

const PROVIDERS: ProviderDef[] = [
  { id: 'anthropic', name: 'Anthropic' },
  { id: 'cerebras', name: 'Cerebras (1M tokens/day free)' },
  { id: 'chutes', name: 'Chutes AI' },
  { id: 'cloudflare', name: 'Cloudflare AI Gateway' },
  { id: 'cohere', name: 'Cohere' },
  { id: 'deepinfra', name: 'DeepInfra' },
  { id: 'deepseek', name: 'DeepSeek' },
  { id: 'fireworks', name: 'Fireworks AI' },
  { id: 'gemini', name: 'Google Gemini' },
  { id: 'groq', name: 'Groq' },
  { id: 'lite-llm', name: 'LiteLLM Proxy' },
  { id: 'mistral', name: 'Mistral AI' },
  { id: 'openai', name: 'OpenAI' },
  { id: 'openrouter', name: 'OpenRouter' },
  { id: 'sambanova', name: 'SambaNova' },
  { id: 'together', name: 'Together AI' },
  { id: 'vercel', name: 'Vercel AI Gateway' },
  { id: 'zai', name: 'Z.ai (GLM-5.2 free)' },
  { id: 'zen', name: 'Zen AI' },
  { id: 'zenmux', name: 'ZenMux (paid — API access requires subscription)' },
];

// Shape of the per-provider info returned by GET /api/settings
interface ProviderInfo {
  name: string;
  api_key_set: boolean;
  model: string;
  default_model: string;
}

interface ModelOption {
  id: string;
  name: string;
  provider: string;
  size?: string;
}

interface SettingsModalProps {
  onClose: () => void;
  onSave: () => void;
}

type Status = 'idle' | 'saving' | 'success' | 'error';

const MODE_OPTIONS: { id: ModePref; label: string; icon: typeof Sun }[] = [
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'dark', label: 'Dark', icon: Moon },
  { id: 'system', label: 'System', icon: Monitor },
];

export function SettingsModal({ onClose, onSave }: SettingsModalProps) {
  const { theme, mode, setTheme, setMode } = useTheme();
  const [adapter, setAdapter] = useState('ollama');
  const [model, setModel] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434');
  const [providerKeys, setProviderKeys] = useState<Record<string, boolean>>({});
  // Live default models per provider — sourced from GET /api/settings.
  // Replaces the previously-hardcoded `defaultModel` field on PROVIDERS.
  const [providerDefaults, setProviderDefaults] = useState<Record<string, string>>({});
  const [newKeyProvider, setNewKeyProvider] = useState('');
  const [newKeyValue, setNewKeyValue] = useState('');
  const [newKeyModel, setNewKeyModel] = useState('');
  // Live model list for the currently-selected provider in the Add Key form.
  // Populated from GET /api/models?provider=... so users pick from a real
  // dropdown instead of typing a free-text model ID.
  const [providerModels, setProviderModels] = useState<ModelOption[]>([]);
  const [providerModelsLoading, setProviderModelsLoading] = useState(false);
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [bestOfNEnabled, setBestOfNEnabled] = useState(() => {
    try {
      return localStorage.getItem('localmind-best-of-n-editor') === '1';
    } catch {
      return false;
    }
  });
  // ADR-41 (Session 254): reasoning-model thinking policy — mirror of the
  // backend's Settings fields (GET /api/settings), saved via
  // POST /api/settings/thinking.
  const [thinking, setThinking] = useState<'enabled' | 'disabled'>('enabled');
  const [reasoningTimeout, setReasoningTimeout] = useState('180');
  const [reasoningPlanTimeout, setReasoningPlanTimeout] = useState('30');
  const [reasoningEffort, setReasoningEffort] = useState('');

  // Load current settings on mount
  useEffect(() => {
    (async () => {
      try {
        const settings = await localmindClient.getSettings();
        setAdapter(settings.adapter);
        setModel(settings.model);
        setThinking(settings.thinking === 'disabled' ? 'disabled' : 'enabled');
        setReasoningTimeout(String(settings.reasoning_timeout ?? 180));
        setReasoningPlanTimeout(String(settings.reasoning_plan_timeout ?? 30));
        setReasoningEffort(settings.reasoning_effort ?? '');
        // Build provider key status AND live default-model map from the
        // providers object returned by /api/settings. This is the single
        // source of truth for default models — no hardcoded values.
        const keyStatus: Record<string, boolean> = {};
        const defaults: Record<string, string> = {};
        if (settings.providers) {
          for (const [id, info] of Object.entries(settings.providers) as [string, ProviderInfo][]) {
            keyStatus[id] = info?.api_key_set ?? false;
            if (info?.default_model) {
              defaults[id] = info.default_model;
            }
          }
        }
        setProviderKeys(keyStatus);
        setProviderDefaults(defaults);
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

  // Save the reasoning-model thinking policy (ADR-41) via the backend.
  const handleSaveThinking = useCallback(async () => {
    const timeout = Number(reasoningTimeout);
    const planTimeout = Number(reasoningPlanTimeout);
    if (!Number.isFinite(timeout) || timeout < 45) {
      setStatus('error');
      setMessage('Reasoning timeout must be at least 45 seconds.');
      return;
    }
    if (!Number.isFinite(planTimeout) || planTimeout < 8) {
      setStatus('error');
      setMessage('Plan timeout must be at least 8 seconds.');
      return;
    }
    setStatus('saving');
    setMessage('Saving reasoning settings…');
    try {
      await localmindClient.setThinkingSettings({
        thinking,
        reasoningTimeout: timeout,
        reasoningPlanTimeout: planTimeout,
        reasoningEffort,
      });
      setStatus('success');
      setMessage('Reasoning settings saved — they apply to the next message.');
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to save reasoning settings');
    }
  }, [thinking, reasoningTimeout, reasoningPlanTimeout, reasoningEffort, onSave]);

  // When the user picks a provider in the Add Key form, fetch that
  // provider's live model list so the model field can be a dropdown
  // instead of a free-text input. If the provider has no saved key yet,
  // the backend returns just the default model — still enough to show
  // a useful dropdown. After the key is saved, re-fetching will return
  // the full live list.
  useEffect(() => {
    if (!newKeyProvider) {
      setProviderModels([]);
      return;
    }
    let cancelled = false;
    setProviderModelsLoading(true);
    localmindClient
      .getModels(newKeyProvider)
      .then((data) => {
        if (!cancelled) setProviderModels(data.models || []);
      })
      .catch(() => {
        // Non-fatal — the model field falls back to free-text input
        if (!cancelled) setProviderModels([]);
      })
      .finally(() => {
        if (!cancelled) setProviderModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [newKeyProvider]);

  const handleAdapterSwitch = useCallback(async (newAdapter: string) => {
    setAdapter(newAdapter);
    // Switch the shown model to the new provider's default so the UI never
    // displays (or leaves active) the previous provider's model — e.g.
    // keeping a Cerebras model under Gemini. The backend resolves the same
    // default authoritatively; this keeps the visible state in sync.
    const nextModel = providerDefaults[newAdapter] ?? '';
    setModel(nextModel);
    setStatus('saving');
    setMessage(`Switching to ${newAdapter}...`);
    try {
      await localmindClient.setAdapter(newAdapter, nextModel || undefined);
      setStatus('success');
      setMessage(`Switched to ${newAdapter} adapter`);
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to switch adapter');
    }
  }, [onSave, providerDefaults]);

  const handleSaveKey = useCallback(async () => {
    if (!newKeyProvider || !newKeyValue.trim()) {
      setStatus('error');
      setMessage('Select a provider and enter an API key');
      return;
    }
    setStatus('saving');
    setMessage(`Saving key for ${newKeyProvider}...`);
    try {
      const result = await localmindClient.setProviderKey(
        newKeyProvider,
        newKeyValue.trim(),
        newKeyModel || undefined,
      );
      setProviderKeys((prev) => ({ ...prev, [newKeyProvider]: true }));
      setNewKeyProvider('');  // close the inline form
      setNewKeyValue('');
      setNewKeyModel('');
      if (result.validated) {
        setStatus('success');
        setMessage(`API key saved and validated for ${newKeyProvider}`);
      } else {
        // Key saved but validation failed — warn the user but don't block.
        // The key may still work (health check can fail transiently).
        setStatus('error');
        setMessage(
          result.validation_error ||
          `Key saved for ${newKeyProvider}, but validation failed. It may still work — try sending a message.`,
        );
      }
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
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to delete API key');
    }
  }, [onSave]);

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

  // ── Accessibility: focus trap + Escape-to-close ──────────────────────
  // Trap focus inside the modal so Tab doesn't escape to elements behind
  // the backdrop. Close on Escape. Restore focus to the previously-focused
  // element when the modal closes.
  const modalRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  // Keep the latest onClose in a ref so the focus/keydown effect below can
  // run ONCE (empty deps) and never tear down on a parent re-render.
  // RightPanel passes an inline `onClose={() => setShowSettings(false)}`, so
  // its identity changes every parent render; a live clock/stats tick
  // re-renders the tree ~every second. With `[onClose]` deps the effect
  // re-ran each second, calling `.focus()` on the modal's first element and
  // yanking focus out of the input you were typing in — you could not paste
  // into the API key box (Session 233).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    // Focus the modal container so screen readers announce it
    const modal = modalRef.current;
    if (modal) {
      // Find the first focusable element inside the modal
      const focusable = modal.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      focusable?.focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !modalRef.current) return;
      // Focus trap: keep Tab within the modal
      const focusables = modalRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      // Restore focus to the element that opened the modal
      previouslyFocused.current?.focus();
    };
    // Empty deps: set up focus + the Tab/Escape trap ONCE on mount and tear
    // down only on unmount. Escape uses onCloseRef so it stays current
    // without re-subscribing (which would steal input focus every render).
  }, []);

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="flex items-center gap-3 text-brand-green-muted">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Loading settings...</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-modal-title"
        tabIndex={-1}
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl border border-brand-border bg-brand-bg-panel shadow-2xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-brand-border bg-brand-bg-panel px-6 py-4">
          <h2 id="settings-modal-title" className="text-lg font-semibold text-brand-green-soft">
            Settings
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-brand-green-muted hover:bg-brand-border hover:text-brand-green-soft transition-colors"
            title="Close"
            aria-label="Close settings"
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
                  ? 'border-brand-amber/30 bg-brand-amber/5 text-brand-amber'
                  : status === 'success'
                  ? 'border-brand-green/30 bg-brand-green/5 text-brand-green'
                  : 'border-brand-red/30 bg-brand-red/5 text-brand-red'
              }`}
            >
              {status === 'saving' && <Loader2 className="h-4 w-4 animate-spin shrink-0" />}
              {status === 'success' && <CheckCircle2 className="h-4 w-4 shrink-0" />}
              {status === 'error' && <AlertCircle className="h-4 w-4 shrink-0" />}
              <span>{message}</span>
            </div>
          )}

          {/* ── Appearance ── */}
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Palette className="h-4 w-4 text-brand-green" />
              Appearance
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              Pick a color theme and light or dark mode. The change applies instantly.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {THEMES.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTheme(t.id)}
                  aria-pressed={theme === t.id}
                  className={`flex flex-col items-start gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    theme === t.id
                      ? 'border-brand-green bg-brand-green/10'
                      : 'border-brand-border hover:border-brand-green/30'
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span
                      className="h-3.5 w-3.5 rounded-full shrink-0"
                      style={{ backgroundColor: t.swatch }}
                    />
                    <span className={`text-sm font-medium ${theme === t.id ? 'text-brand-green' : 'text-brand-green-soft'}`}>
                      {t.label}
                    </span>
                  </span>
                  <span className="text-[11px] leading-tight text-brand-green-muted">{t.blurb}</span>
                </button>
              ))}
            </div>
            <div className="mt-2 inline-flex rounded-lg border border-brand-border p-0.5">
              {MODE_OPTIONS.map((m) => {
                const Icon = m.icon;
                return (
                  <button
                    key={m.id}
                    onClick={() => setMode(m.id)}
                    aria-pressed={mode === m.id}
                    className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                      mode === m.id
                        ? 'bg-brand-green/15 text-brand-green'
                        : 'text-brand-green-muted hover:text-brand-green-soft'
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {m.label}
                  </button>
                );
              })}
            </div>
          </section>

          {/* ── Adapter Selection ── */}
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Server className="h-4 w-4 text-brand-green" />
              AI Provider
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              Choose between local Ollama or a cloud provider. Cloud providers require an API key below.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-[280px] overflow-y-auto custom-scrollbar pr-1">
              <button
                onClick={() => handleAdapterSwitch('ollama')}
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                  adapter === 'ollama'
                    ? 'border-brand-green bg-brand-green/10 text-brand-green'
                    : 'border-brand-border text-brand-green-muted hover:border-brand-green/30 hover:text-brand-green-soft'
                }`}
              >
                Ollama (Local)
              </button>
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleAdapterSwitch(p.id)}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    adapter === p.id
                      ? 'border-brand-green bg-brand-green/10 text-brand-green'
                      : 'border-brand-border text-brand-green-muted hover:border-brand-green/30 hover:text-brand-green-soft'
                  }`}
                >
                  {p.name}
                </button>
              ))}
            </div>
            {adapter !== 'ollama' && (
              <p className="mt-2 text-xs text-brand-green-muted">
                Current model: <span className="font-mono text-brand-green-soft">{model || 'default'}</span>
              </p>
            )}
          </section>

          {/* ── Reasoning (ADR-41) ── */}
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Brain className="h-4 w-4 text-brand-green" />
              Reasoning
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              GLM models on Z.ai think before answering — this produces complete
              answers instead of terse cuts. Tune that here; it applies to the next message.
            </p>
            <div className="space-y-3">
              <div>
                <p className="mb-1.5 text-xs font-medium text-brand-green-soft">Model thinking</p>
                <div className="inline-flex rounded-lg border border-brand-border p-0.5">
                  {(['enabled', 'disabled'] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setThinking(m)}
                      aria-pressed={thinking === m}
                      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                        thinking === m
                          ? 'bg-brand-green/15 text-brand-green'
                          : 'text-brand-green-muted hover:text-brand-green-soft'
                      }`}
                    >
                      {m === 'enabled' ? 'Enabled' : 'Disabled'}
                    </button>
                  ))}
                </div>
                <p className="mt-1 text-[11px] text-brand-green-muted">
                  Disabling makes GLM reply instantly but terse (~28 tokens). GLM-5.3+ always thinks.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-brand-green-soft">
                    Reasoning timeout (s)
                  </span>
                  <input
                    type="number"
                    min={45}
                    value={reasoningTimeout}
                    onChange={(e) => setReasoningTimeout(e.target.value)}
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-brand-green-soft">
                    Plan timeout (s)
                  </span>
                  <input
                    type="number"
                    min={8}
                    value={reasoningPlanTimeout}
                    onChange={(e) => setReasoningPlanTimeout(e.target.value)}
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                  />
                </label>
              </div>
              <div>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-brand-green-soft">
                    Reasoning effort (GLM-5.2+)
                  </span>
                  <select
                    value={reasoningEffort}
                    onChange={(e) => setReasoningEffort(e.target.value)}
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                  >
                    <option value="">Provider default</option>
                    {['none', 'minimal', 'low', 'medium', 'high', 'max', 'xhigh'].map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="mt-1 text-[11px] text-brand-green-muted">
                  Bounds how long GLM thinks (5.2: max/xhigh/high/medium/low/minimal/none; 5.3: max/high/low).
                </p>
              </div>
              <button
                onClick={handleSaveThinking}
                disabled={status === 'saving'}
                className="rounded-lg border border-brand-green/30 bg-brand-green/10 px-4 py-2 text-sm font-medium text-brand-green hover:bg-brand-green/20 transition-colors disabled:opacity-50"
              >
                Save Reasoning
              </button>
            </div>
          </section>

          {/* ── Ollama URL Configuration ── */}
          {adapter === 'ollama' && (
            <section>
              <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
                <Server className="h-4 w-4 text-brand-green" />
                Ollama Server URL
              </h3>
              <p className="mb-3 text-xs text-brand-green-muted">
                Point LocalMind at a local or remote Ollama instance. The URL is validated before saving.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                  placeholder="http://localhost:11434"
                  className="flex-1 rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                />
                <button
                  onClick={handleSaveOllamaUrl}
                  disabled={status === 'saving'}
                  className="rounded-lg border border-brand-green/30 bg-brand-green/10 px-4 py-2 text-sm font-medium text-brand-green hover:bg-brand-green/20 transition-colors disabled:opacity-50"
                >
                  Save
                </button>
                <button
                  onClick={handleResetOllamaUrl}
                  disabled={status === 'saving'}
                  className="rounded-lg border border-brand-border px-3 py-2 text-sm text-brand-green-muted hover:text-brand-green-soft hover:border-brand-green/30 transition-colors disabled:opacity-50"
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
              <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
                <Key className="h-4 w-4 text-brand-green" />
                API Keys
              </h3>
              <p className="mb-3 text-xs text-brand-green-muted">
                Keys are stored locally in <code className="text-brand-green-soft">~/LocalMind/settings.json</code> with
                restricted file permissions. They never leave your machine. Click "Add Key" or "Update" on any provider to enter its key inline.
              </p>

              {/* Unified provider list — each row shows key status and an
                  inline expand button. No separate dropdown needed. */}
              <div className="space-y-1.5">
                {PROVIDERS.map((p) => {
                  const hasKey = providerKeys[p.id];
                  const isEditing = newKeyProvider === p.id;
                  return (
                    <div key={p.id} className="rounded-lg border border-brand-border overflow-hidden">
                      {/* Provider row */}
                      <div className="flex items-center justify-between px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-brand-green-soft">{p.name}</span>
                          {hasKey ? (
                            <span className="flex items-center gap-1 text-xs text-brand-green">
                              <CheckCircle2 className="h-3 w-3" />
                              Key set
                            </span>
                          ) : (
                            <span className="text-xs text-brand-green-muted">No key</span>
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          {hasKey && (
                            <button
                              onClick={() => {
                                setNewKeyProvider(p.id);
                                setNewKeyValue('');
                                setNewKeyModel('');
                              }}
                              disabled={status === 'saving'}
                              className="rounded px-2 py-1 text-xs text-brand-green-muted hover:bg-brand-border hover:text-brand-green-soft transition-colors disabled:opacity-50"
                              title={`Update ${p.name} API key`}
                            >
                              Update
                            </button>
                          )}
                          {hasKey && (
                            <button
                              onClick={() => handleDeleteKey(p.id)}
                              disabled={status === 'saving'}
                              className="flex items-center gap-1 rounded px-2 py-1 text-xs text-brand-red hover:bg-brand-red/10 transition-colors disabled:opacity-50"
                              title={`Remove ${p.name} API key`}
                              aria-label={`Remove ${p.name} API key`}
                            >
                              <Trash2 className="h-3 w-3" />
                              Remove
                            </button>
                          )}
                          {!hasKey && !isEditing && (
                            <button
                              onClick={() => {
                                setNewKeyProvider(p.id);
                                setNewKeyValue('');
                                setNewKeyModel('');
                              }}
                              disabled={status === 'saving'}
                              className="rounded px-2 py-1 text-xs text-brand-green hover:bg-brand-green/10 transition-colors disabled:opacity-50"
                            >
                              + Add Key
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Inline key form — expands when this provider is selected */}
                      {isEditing && (
                        <div className="border-t border-brand-border bg-brand-bg-base p-3 space-y-2">
                          <div className="relative">
                            <input
                              type="password"
                              value={newKeyValue}
                              onChange={(e) => setNewKeyValue(e.target.value)}
                              placeholder="API key"
                              className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 pr-24 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                            />
                            {/* Paste/Copy directly on the field — no OS menu needed
                                (Cmd+V is unreliable in Electron without an app menu). */}
                            <div className="absolute inset-y-0 right-1.5 flex items-center gap-1">
                              <button
                                type="button"
                                onClick={async () => {
                                  try {
                                    const text = await navigator.clipboard.readText();
                                    if (text) setNewKeyValue(text.trim());
                                  } catch {
                                    // Clipboard unavailable (permissions/non-secure context) — no-op.
                                  }
                                }}
                                className="px-2 py-1 text-[11px] rounded text-brand-green hover:bg-brand-green/10 transition-colors"
                                title="Paste API key from clipboard"
                              >
                                Paste
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  if (newKeyValue) navigator.clipboard?.writeText(newKeyValue).catch(() => {});
                                }}
                                disabled={!newKeyValue}
                                className="px-2 py-1 text-[11px] rounded text-brand-green-muted hover:text-brand-green hover:bg-brand-green/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                                title="Copy current value"
                              >
                                Copy
                              </button>
                            </div>
                          </div>
                          <input
                            type="text"
                            value={newKeyModel}
                            onChange={(e) => setNewKeyModel(e.target.value)}
                            placeholder={`Model (optional, default: ${
                              providerDefaults[p.id] || 'provider default'
                            })`}
                            className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                          />
                          {/* Live model chips — populated from GET /api/models?provider=... */}
                          {providerModels.length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                              {providerModels.map((m) => (
                                <button
                                  key={m.id}
                                  type="button"
                                  onClick={() => setNewKeyModel(m.id)}
                                  className={`rounded px-2 py-1 text-[11px] font-mono transition-colors ${
                                    newKeyModel === m.id
                                      ? 'border border-brand-green bg-brand-green/10 text-brand-green'
                                      : 'border border-brand-border text-brand-green-muted hover:border-brand-green/30 hover:text-brand-green-soft'
                                  }`}
                                  title={`Use ${m.id}`}
                                >
                                  {m.id}
                                </button>
                              ))}
                            </div>
                          )}
                          {providerModelsLoading && (
                            <div className="flex items-center gap-1.5 text-[11px] text-brand-green-muted">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              Loading models…
                            </div>
                          )}
                          <div className="flex gap-2">
                            <button
                              onClick={handleSaveKey}
                              disabled={status === 'saving' || !newKeyValue.trim()}
                              className="flex-1 rounded-lg border border-brand-green/30 bg-brand-green/10 px-4 py-2 text-sm font-medium text-brand-green hover:bg-brand-green/20 transition-colors disabled:opacity-50"
                            >
                              {status === 'saving' ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'Save'}
                            </button>
                            <button
                              onClick={() => {
                                setNewKeyProvider('');
                                setNewKeyValue('');
                                setNewKeyModel('');
                              }}
                              disabled={status === 'saving'}
                              className="rounded-lg border border-brand-border px-4 py-2 text-sm text-brand-green-muted hover:text-brand-green-soft hover:border-brand-green/30 transition-colors disabled:opacity-50"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* ── Best-of-N Editor (C2 spec step 7) ── */}
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <FileEdit className="h-4 w-4 text-brand-green" />
              Best-of-N Editor
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              When enabled, coding edits can use the best-of-N pattern: the
              agent produces multiple candidate fixes under different strategies,
              picks the best one via a selector agent, and applies it. The
              candidates are shown in the chat so you can review the runner-up
              strategies. Requires a strong model for the selector agent
              (configure via <code className="text-brand-green-soft">LOCALMIND_AGENT_MODEL_EDITOR_SELECTOR</code>).
            </p>
            <button
              onClick={() => {
                const newVal = !bestOfNEnabled;
                setBestOfNEnabled(newVal);
                try {
                  localStorage.setItem('localmind-best-of-n-editor', newVal ? '1' : '0');
                } catch {
                  // localStorage may be unavailable
                }
              }}
              className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                bestOfNEnabled
                  ? 'border-brand-green bg-brand-green/10 text-brand-green'
                  : 'border-brand-border text-brand-green-muted hover:border-brand-green/30 hover:text-brand-green-soft'
              }`}
            >
              {bestOfNEnabled ? 'Enabled' : 'Disabled'}
            </button>
          </section>

          {/* ── Footer ── */}
          <div className="flex justify-end border-t border-brand-border pt-4">
            <button
              onClick={onClose}
              className="rounded-lg border border-brand-border px-4 py-2 text-sm text-brand-green-muted hover:text-brand-green-soft hover:border-brand-green/30 transition-colors"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
