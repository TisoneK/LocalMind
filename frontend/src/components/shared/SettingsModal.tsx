'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { X, Server, Key, Loader2, CheckCircle2, AlertCircle, Trash2, FileEdit, Palette, Sun, Moon, Monitor, Brain, Cpu, Database, RotateCcw, MessageSquarePlus, Download, Shield, Plug, Zap } from 'lucide-react';
import { localmindClient, type ConnectionRecord, type ConnectionTestResult } from '@/lib/localmind/client';
import { Progress } from '@/components/ui/progress';
import { PAGES, GROUPS, SECTION_PAGE, type PageId } from './settingsPages';
import { PackageEnvChoice } from '@/components/panels/PackageEnvChoice';
import { useTheme, THEMES, type CustomTheme, type ModePref } from '@/hooks/useTheme';

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
  { id: 'bankofai', name: 'BankOfAI (promo free models — time-limited)' },
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
  { id: 'omniroute', name: 'OmniRoute (self-hosted gateway — 500+ models)' },
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
  contextWindow?: number;  // effective window from /api/models (drives Bug C)
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
  const { theme, mode, custom, tone, setTheme, setMode, setCustomTheme, setTone } = useTheme();
  // Persist appearance to settings.json on every change so
  // the theme/tone/custom palette survive restarts (mirrors adapter/model).
  const persistAppearance = useCallback((partial: {
    theme?: string;
    mode?: string;
    custom_theme?: CustomTheme;
    tone?: number;
  }) => {
    localmindClient.setAppearance(partial).catch(() => {
      // Non-fatal: the change already applied locally; persistence is best-effort.
    });
  }, []);
  // Draft state for the custom palette editor (avoid mutating the applied
  // palette mid-edit; committed on color/name change).
  const customDraft = custom ?? { name: 'Custom', accent: '#34d399', background: '#12161d', surface: '#1f2530', text: '#e6edf3' };
  const commitCustom = (next: CustomTheme) => {
    setCustomTheme(next);
    persistAppearance({ theme: 'custom', mode, custom_theme: next, tone });
  };
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
  // AI Connections — preset providers + user-defined endpoints (GET
  // /api/settings `connections`). Custom (non-preset) ones get their own
  // manager section; ALL enabled ones (preset + custom) join the provider
  // picker above so a custom connection can be selected as the active adapter.
  const [connections, setConnections] = useState<ConnectionRecord[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(false);
  // Draft for the "Add connection" form; '' id means the form is closed.
  const [newConnDraft, setNewConnDraft] = useState<{
    id: string; name: string; base_url: string; model: string;
    tool_calling: boolean; streaming: boolean;
  } | null>(null);
  const [editingConnId, setEditingConnId] = useState<string>('');
  const [editConnDraft, setEditConnDraft] = useState<{ name: string; base_url: string; model: string }>({
    name: '', base_url: '', model: '',
  });
  const [connTestResults, setConnTestResults] = useState<Record<string, ConnectionTestResult>>({});
  const [connTesting, setConnTesting] = useState<string>('');
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
  // Reasoning-model thinking policy — mirror of the
  // backend's Settings fields (GET /api/settings), saved via
  // POST /api/settings/thinking.
  const [thinking, setThinking] = useState<'enabled' | 'disabled'>('enabled');
  const [reasoningTimeout, setReasoningTimeout] = useState('180');
  const [reasoningPlanTimeout, setReasoningPlanTimeout] = useState('30');
  const [reasoningMaxWallClock, setReasoningMaxWallClock] = useState('360');
  const [reasoningEffort, setReasoningEffort] = useState('');
  // ── Active-model + local (Ollama) settings ──
  // The active-model list for the CURRENT adapter (so users can switch the
  // chat model right here, not only in the sidebar). Embedding model + context
  // window (num_ctx) are Ollama-local knobs — previously only settable via env.
  const [activeModels, setActiveModels] = useState<ModelOption[]>([]);
  const [embedModels, setEmbedModels] = useState<ModelOption[]>([]);
  const [embedModel, setEmbedModel] = useState('');
  // num_ctx override as a string; '' means AUTO (use the model's own window,
  // shown as the field placeholder so it reflects the selected model — Bug C).
  const [numCtx, setNumCtx] = useState('');
  // The selected model's effective context window (from /api/models) — drives
  // the num_ctx placeholder so the field reflects the current model's value.
  const [modelWindow, setModelWindow] = useState<number | null>(null);
  // Shell-tool enable toggle (Bug B — was env-only, now a UI switch).
  const [shellEnabled, setShellEnabled] = useState(false);
  // Startup session behavior ("resume" | "new").
  const [startupSession, setStartupSession] = useState<'new' | 'resume'>('new');
  // Operation permissions.
  const [permissions, setPermissions] = useState<Record<string, boolean>>({
    file_read: true,
    file_write: true,
    file_edit: true,
    shell: true,
    code_exec: true,
    web_search: true,
    web_fetch: true,
    memory_op: true,
  });
  // Embed-model download status + progress.
  const [embedStatus, setEmbedStatus] = useState<{ ollama_available: boolean; model_installed: boolean; model_name: string } | null>(null);
  const [embedDownload, setEmbedDownload] = useState<{ status: string; progress: number | null; detail: string } | null>(null);
  const embedPullRef = useRef<{ cancel: () => void } | null>(null);

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
        setReasoningMaxWallClock(String(settings.reasoning_max_wall_clock ?? 360));
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
        setConnections(Array.isArray(settings.connections) ? settings.connections : []);
        // Local knobs: embedding model + context-window override + shell toggle.
        setEmbedModel(settings.embed_model ?? '');
        // '' = auto (0); a real override shows as its number.
        setNumCtx(settings.num_ctx && settings.num_ctx > 0 ? String(settings.num_ctx) : '');
        setShellEnabled(settings.shell_enabled ?? false);
        // Startup session behavior.
        setStartupSession(settings.startup_session === 'resume' ? 'resume' : 'new');
        // Operation permissions.
        if (settings.permissions && typeof settings.permissions === 'object') {
          setPermissions((prev) => ({ ...prev, ...settings.permissions }));
        }
        // Bug A: the essential settings are loaded — reveal the modal NOW and
        // let the model/embedding lists (which prime Ollama /api/show and can
        // take a few seconds) populate in the background instead of blocking
        // the whole dialog behind a "Loading settings…" spinner.
        setLoading(false);
        // Active-model list for the current adapter + embedding-model list.
        // Both best-effort — a cloud adapter or a stopped Ollama must not
        // block the rest of the settings from loading.
        try {
          const activeList = await localmindClient.getModels();
          setActiveModels(activeList.models);
          const current = activeList.current || settings.model;
          if (current) setModel(current);
          // Bug C: reflect the selected model's window in the num_ctx field.
          const cur = activeList.models.find((m) => m.id === current);
          if (cur?.contextWindow) setModelWindow(cur.contextWindow);
        } catch {
          /* keep whatever /api/settings reported */
        }
        try {
          const embedList = await localmindClient.getEmbeddingModels();
          setEmbedModels(embedList.models);
          if (embedList.current) setEmbedModel(embedList.current);
        } catch {
          /* embedding list is Ollama-only; non-fatal */
        }
        // Load Ollama URL if using ollama adapter
        if (settings.adapter === 'ollama') {
          try {
            const urlInfo = await localmindClient.getOllamaUrl();
            setOllamaUrl(urlInfo.url);
          } catch {
            // Non-fatal: ollama routes may 501 for cloud adapters
          }
        }
        // Check if embed model needs downloading
        try {
          const est = await localmindClient.getOllamaEmbedStatus();
          setEmbedStatus(est);
        } catch {
          /* non-fatal */
        }
      } catch (err) {
        setStatus('error');
        setMessage(err instanceof Error ? err.message : 'Failed to load settings');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Save the reasoning-model thinking policy via the backend.
  const handleSaveThinking = useCallback(async () => {
    const timeout = Number(reasoningTimeout);
    const planTimeout = Number(reasoningPlanTimeout);
    const maxWallClock = Number(reasoningMaxWallClock);
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
    if (!Number.isFinite(maxWallClock) || maxWallClock < 180) {
      setStatus('error');
      setMessage('Total-turn timeout must be at least 180 seconds.');
      return;
    }
    setStatus('saving');
    setMessage('Saving reasoning settings…');
    try {
      await localmindClient.setThinkingSettings({
        thinking,
        reasoningTimeout: timeout,
        reasoningPlanTimeout: planTimeout,
        reasoningMaxWallClock: maxWallClock,
        reasoningEffort,
      });
      setStatus('success');
      setMessage('Reasoning settings saved — they apply to the next message.');
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to save reasoning settings');
    }
  }, [thinking, reasoningTimeout, reasoningPlanTimeout, reasoningMaxWallClock, reasoningEffort, onSave]);

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
      // Refresh the active-model list for the new adapter so the model
      // selector below reflects the newly-selected provider's models.
      try {
        const activeList = await localmindClient.getModels();
        setActiveModels(activeList.models);
        if (activeList.current) setModel(activeList.current);
      } catch {
        /* non-fatal */
      }
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to switch adapter');
    }
  }, [onSave, providerDefaults]);

  // Hot-swap the active chat model for the CURRENT adapter.
  const handleSelectActiveModel = useCallback(async (modelId: string) => {
    if (!modelId || modelId === model) return;
    setModel(modelId);
    // Bug C: reflect the newly-selected model's window in the num_ctx field.
    const picked = activeModels.find((m) => m.id === modelId);
    if (picked?.contextWindow) setModelWindow(picked.contextWindow);
    setStatus('saving');
    setMessage(`Switching model to ${modelId}...`);
    try {
      await localmindClient.selectModel(modelId);
      setStatus('success');
      setMessage(`Active model: ${modelId}`);
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to switch model');
    }
  }, [model, activeModels, onSave]);

  // Persist Ollama-local knobs: embedding model + context window + shell toggle.
  const handleSaveLocal = useCallback(async () => {
    // '' = auto (0). A concrete value is a positive override.
    const trimmed = numCtx.trim();
    const parsed = trimmed === '' ? 0 : Number.parseInt(trimmed, 10);
    if (Number.isNaN(parsed) || parsed < 0) {
      setStatus('error');
      setMessage('Context window must be blank (auto) or a positive number');
      return;
    }
    setStatus('saving');
    setMessage('Saving local model settings...');
    try {
      const res = await localmindClient.setLocalSettings({
        embedModel: embedModel || undefined,
        numCtx: parsed,
        shellEnabled,
      });
      setNumCtx(res.num_ctx && res.num_ctx > 0 ? String(res.num_ctx) : '');
      setStatus('success');
      setMessage(
        parsed === 0
          ? 'Local settings saved — context window auto-fit to the model'
          : `Local settings saved — context window ${parsed.toLocaleString()} tokens`,
      );
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to save local settings');
    }
  }, [embedModel, numCtx, shellEnabled, onSave]);

  // Download the configured embed model from Ollama.
  const refreshEmbedStatus = useCallback(async () => {
    try {
      const est = await localmindClient.getOllamaEmbedStatus();
      setEmbedStatus(est);
    } catch {
      /* non-fatal */
    }
  }, []);

  const handleDownloadEmbed = useCallback(() => {
    setEmbedDownload({ status: 'pulling', progress: null, detail: 'Starting download…' });
    setStatus('saving');
    setMessage('Downloading embed model…');
    const { cancel } = localmindClient.pullEmbedModel(
      (data) => setEmbedDownload(data),
      async () => {
        setEmbedDownload(null);
        setStatus('success');
        setMessage('Embed model downloaded successfully.');
        await refreshEmbedStatus();
        // Also refresh the embedding model list so the dropdown updates.
        try {
          const embedList = await localmindClient.getEmbeddingModels();
          setEmbedModels(embedList.models);
        } catch { /* non-fatal */ }
        onSave();
      },
      (err) => {
        setEmbedDownload(null);
        setStatus('error');
        setMessage(`Failed to download embed model: ${err}`);
      },
    );
    embedPullRef.current = { cancel };
  }, [onSave, refreshEmbedStatus]);

  // Persist startup session behavior immediately on toggle.
  const handleChangeStartupSession = useCallback(async (mode: 'new' | 'resume') => {
    setStartupSession(mode);
    try {
      await localmindClient.setStartupSession(mode);
    } catch {
      // Non-fatal: the local state is already correct.
    }
  }, []);

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

  // Refresh the connections list from /api/settings (cheaper than a full
  // reload — the rest of the settings snapshot doesn't need to move).
  const refreshConnections = useCallback(async () => {
    try {
      const s = await localmindClient.getSettings();
      setConnections(Array.isArray(s.connections) ? s.connections : []);
    } catch {
      /* non-fatal — the local optimistic update already applied */
    }
  }, []);

  const handleCreateConnection = useCallback(async () => {
    if (!newConnDraft) return;
    const { id, name, base_url, model, tool_calling, streaming } = newConnDraft;
    if (!id.trim() || !name.trim() || !base_url.trim() || !model.trim()) {
      setStatus('error');
      setMessage('A connection needs an id, name, base URL, and model.');
      return;
    }
    setConnectionsLoading(true);
    setStatus('saving');
    setMessage(`Creating connection '${name}'...`);
    try {
      await localmindClient.saveConnection({
        id: id.trim(),
        name: name.trim(),
        base_url: base_url.trim(),
        model: model.trim(),
        capabilities: { tool_calling, streaming },
      });
      setNewConnDraft(null);
      await refreshConnections();
      setStatus('success');
      setMessage(`Connection '${name}' created — select it above to use it.`);
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to create connection');
    } finally {
      setConnectionsLoading(false);
    }
  }, [newConnDraft, refreshConnections, onSave]);

  const handleSaveConnectionEdit = useCallback(async (id: string) => {
    setConnectionsLoading(true);
    setStatus('saving');
    setMessage(`Saving connection '${id}'...`);
    try {
      await localmindClient.saveConnection({
        id,
        name: editConnDraft.name.trim() || undefined,
        base_url: editConnDraft.base_url.trim() || undefined,
        model: editConnDraft.model.trim() || undefined,
      });
      setEditingConnId('');
      await refreshConnections();
      setStatus('success');
      setMessage(`Connection '${id}' updated`);
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to update connection');
    } finally {
      setConnectionsLoading(false);
    }
  }, [editConnDraft, refreshConnections, onSave]);

  const handleToggleConnectionEnabled = useCallback(async (conn: ConnectionRecord) => {
    setConnectionsLoading(true);
    try {
      await localmindClient.saveConnection({ id: conn.id, enabled: !conn.enabled });
      await refreshConnections();
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to toggle connection');
    } finally {
      setConnectionsLoading(false);
    }
  }, [refreshConnections, onSave]);

  const handleDeleteConnection = useCallback(async (conn: ConnectionRecord) => {
    setConnectionsLoading(true);
    setStatus('saving');
    setMessage(conn.preset ? `Resetting '${conn.name}'...` : `Deleting '${conn.name}'...`);
    try {
      const result = await localmindClient.deleteConnection(conn.id);
      await refreshConnections();
      setStatus('success');
      setMessage(result.message);
      if (result.adapter !== adapter) {
        // The backend fell back to Ollama because the active adapter was
        // the connection just deleted.
        setAdapter(result.adapter);
      }
      onSave();
    } catch (err) {
      setStatus('error');
      setMessage(err instanceof Error ? err.message : 'Failed to delete connection');
    } finally {
      setConnectionsLoading(false);
    }
  }, [adapter, refreshConnections, onSave]);

  const handleTestConnection = useCallback(async (connectionId: string) => {
    setConnTesting(connectionId);
    try {
      const result = await localmindClient.testConnection(connectionId);
      setConnTestResults((prev) => ({ ...prev, [connectionId]: result }));
      if (result.stored) {
        await refreshConnections();
      }
    } catch (err) {
      setConnTestResults((prev) => ({
        ...prev,
        [connectionId]: {
          connection: connectionId,
          model: '',
          ok: false,
          reachable: false,
          auth_ok: false,
          chat_ok: false,
          streaming_ok: null,
          tools: null,
          models_count: null,
          context_window: null,
          latency_ms: null,
          error: err instanceof Error ? err.message : 'Test failed',
          stored: null,
        },
      }));
    } finally {
      setConnTesting('');
    }
  }, [refreshConnections]);

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
  const [page, setPage] = useState<PageId>('general');
  const previouslyFocused = useRef<HTMLElement | null>(null);
  // Keep the latest onClose in a ref so the focus/keydown effect below can
  // run ONCE (empty deps) and never tear down on a parent re-render.
  // RightPanel passes an inline `onClose={() => setShowSettings(false)}`, so
  // its identity changes every parent render; a live clock/stats tick
  // re-renders the tree ~every second. With `[onClose]` deps the effect
  // re-ran each second, calling `.focus()` on the modal's first element and
  // yanking focus out of the input you were typing in — you could not paste
  // into the API key box .
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
    // Bug A: match the modal's own themed panel (border/bg/text tokens adapt to
    // the active theme) instead of bare muted text floating on the backdrop.
    // The lag is separately fixed by revealing the modal right after the
    // essential settings load, so this state now only flashes briefly.
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="flex items-center gap-3 rounded-xl border border-brand-border bg-brand-bg-panel px-6 py-4 text-brand-green-soft shadow-2xl">
          <Loader2 className="h-5 w-5 animate-spin text-brand-green" />
          <span>Loading settings…</span>
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
        className="flex h-[82vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-brand-border bg-brand-bg-panel shadow-2xl outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-brand-border bg-brand-bg-panel px-6 py-4">
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

        <div className="flex min-h-0 flex-1">
          {/* Left nav: pages, grouped */}
          <nav aria-label="Settings pages" className="w-52 shrink-0 overflow-y-auto border-r border-brand-border bg-brand-bg-dark/40 px-2 py-3">
            {GROUPS.map((g) => (
              <div key={g} className="mb-3">
                <div className="px-2 pb-1 text-[10px] uppercase tracking-wider text-brand-green-faint">{g}</div>
                {PAGES.filter((pg) => pg.group === g).map((pg) => (
                  <button
                    key={pg.id}
                    type="button"
                    onClick={() => setPage(pg.id)}
                    aria-current={page === pg.id ? 'page' : undefined}
                    className={`mb-0.5 flex w-full items-center rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
                      page === pg.id ? 'bg-brand-green/10 text-brand-green' : 'text-brand-green-muted hover:bg-brand-border/40 hover:text-brand-green-soft'
                    }`}
                  >
                    {pg.label}
                  </button>
                ))}
              </div>
            ))}
          </nav>
          <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="space-y-6 px-6 py-5">
          {/* Page heading */}
          <div>
            <h3 className="text-base font-medium text-brand-green-soft">{PAGES.find((pg) => pg.id === page)?.label}</h3>
            <p className="text-xs text-brand-green-muted">{PAGES.find((pg) => pg.id === page)?.blurb}</p>
          </div>
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
          <section hidden={page !== SECTION_PAGE['Appearance']}>
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
                  onClick={() => {
                    setTheme(t.id);
                    persistAppearance({ theme: t.id, mode });
                  }}
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
                      style={{ background: t.swatch }}
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
                    onClick={() => {
                      setMode(m.id);
                      persistAppearance({ theme, mode: m.id });
                    }}
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

            {/* ── Custom palette editor ── */}
            {theme === 'custom' && (
              <div className="mt-3 rounded-lg border border-brand-border bg-brand-bg-panel-alt p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-brand-green-soft">Custom palette</span>
                  <span className="text-[11px] text-brand-green-muted">Saved to settings.json</span>
                </div>
                <div className="flex items-center gap-2">
                  <label className="w-24 shrink-0 text-[11px] text-brand-green-muted" htmlFor="custom-theme-name">
                    Name
                  </label>
                  <input
                    id="custom-theme-name"
                    value={customDraft.name}
                    maxLength={32}
                    onChange={(e) => commitCustom({ ...customDraft, name: e.target.value || 'Custom' })}
                    className="flex-1 rounded-md border border-brand-border bg-brand-bg-base px-2 py-1.5 text-sm text-brand-green-soft outline-none focus:border-brand-green/50"
                  />
                </div>
                {([
                  ['Accent', 'accent'],
                  ['Background', 'background'],
                  ['Surface', 'surface'],
                  ['Text', 'text'],
                ] as const).map(([label, key]) => (
                  <div key={key} className="flex items-center gap-2">
                    <label className="w-24 shrink-0 text-[11px] text-brand-green-muted" htmlFor={`custom-theme-${key}`}>
                      {label}
                    </label>
                    <input
                      id={`custom-theme-${key}`}
                      type="color"
                      value={customDraft[key]}
                      onChange={(e) => commitCustom({ ...customDraft, [key]: e.target.value })}
                      className="h-8 w-12 shrink-0 cursor-pointer rounded-md border border-brand-border bg-transparent"
                    />
                    <code className="flex-1 truncate font-mono text-[11px] text-brand-green-muted">{customDraft[key]}</code>
                  </div>
                ))}
                <button
                  onClick={() => {
                    setTheme('graphite');
                    persistAppearance({ theme: 'graphite', mode });
                  }}
                  className="text-[11px] text-brand-green-muted hover:text-brand-green-soft"
                >
                  Reset to built-in theme
                </button>
              </div>
            )}

            {/* ── UI tone (brightness) ── */}
            <div className="mt-3 flex items-center gap-3 rounded-lg border border-brand-border px-3 py-2.5">
              <label className="w-24 shrink-0 text-xs text-brand-green-soft" htmlFor="ui-tone-slider">
                Tone
              </label>
              <input
                id="ui-tone-slider"
                type="range"
                min={0.5}
                max={1.5}
                step={0.05}
                value={tone}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setTone(v);
                  persistAppearance({ theme, mode, tone: v });
                }}
                className="flex-1 accent-brand-green"
                aria-label="UI tone / brightness"
              />
              <span className="w-14 shrink-0 text-right font-mono text-[11px] text-brand-green-muted">
                {tone.toFixed(2)}×
              </span>
            </div>
          </section>

          {/* ── Adapter Selection ── */}
          <section hidden={page !== SECTION_PAGE['AI Provider']}>
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
              {/* Custom (user-defined) connections — AI Connections below manages
                  them; enabled ones are selectable here like any preset provider. */}
              {connections.filter((c) => !c.preset && c.enabled).map((c) => (
                <button
                  key={c.id}
                  onClick={() => handleAdapterSwitch(c.id)}
                  title={c.base_url}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                    adapter === c.id
                      ? 'border-brand-green bg-brand-green/10 text-brand-green'
                      : 'border-brand-border text-brand-green-muted hover:border-brand-green/30 hover:text-brand-green-soft'
                  }`}
                >
                  {c.name}
                </button>
              ))}
            </div>
          </section>

          {/* ── Active Model ── */}
          <section hidden={page !== SECTION_PAGE['Model']}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Cpu className="h-4 w-4 text-brand-green" />
              Model
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              The chat model for the current provider. Switching here takes
              effect on your next message.
            </p>
            {activeModels.length > 0 ? (
              <select
                value={model}
                onChange={(e) => handleSelectActiveModel(e.target.value)}
                className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                data-testid="active-model-select"
              >
                {/* Include the current model even if the list didn't return it,
                    so the dropdown always shows what's actually active. */}
                {!activeModels.some((m) => m.id === model) && model && (
                  <option value={model}>{model}</option>
                )}
                {activeModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.size ? ` — ${m.size}` : ''}
                  </option>
                ))}
              </select>
            ) : (
              <p className="text-xs text-brand-green-muted">
                {adapter === 'ollama'
                  ? 'No local models found. Pull one with `ollama pull <model>` and reopen settings.'
                  : `Current model: `}
                {adapter !== 'ollama' && (
                  <span className="font-mono text-brand-green-soft">{model || 'default'}</span>
                )}
              </p>
            )}
          </section>

          {/* ── Local model (Ollama) — embeddings + context window ── */}
          <section hidden={page !== SECTION_PAGE['Local model (Ollama)']}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Database className="h-4 w-4 text-brand-green" />
              Local model (Ollama)
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              The embedding model powers memory and file search (always local).
              Context window sets how much the model reads per turn.
            </p>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-brand-green-soft">
                  Embedding model
                </label>
                {embedModels.length > 0 ? (
                  <select
                    value={embedModel}
                    onChange={(e) => setEmbedModel(e.target.value)}
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                    data-testid="embed-model-select"
                  >
                    {!embedModels.some((m) => m.id === embedModel) && embedModel && (
                      <option value={embedModel}>{embedModel}</option>
                    )}
                    {embedModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={embedModel}
                    onChange={(e) => setEmbedModel(e.target.value)}
                    placeholder="nomic-embed-text"
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                    data-testid="embed-model-input"
                  />
                )}
                {embedModels.length === 0 && !embedDownload && (
                  <p className="mt-1 text-[11px] text-brand-green-muted">
                    No embedding models detected. Pull one, e.g. `ollama pull nomic-embed-text`.
                  </p>
                )}
                {/* One-click embed model download */}
                {embedStatus?.ollama_available && !embedStatus.model_installed && !embedDownload && (
                  <button
                    onClick={handleDownloadEmbed}
                    className="mt-2 flex items-center gap-1.5 rounded-lg border border-brand-green/30 bg-brand-green/10 px-3 py-1.5 text-xs font-medium text-brand-green hover:bg-brand-green/20 transition-colors"
                    data-testid="download-embed-model"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download {embedStatus.model_name}
                  </button>
                )}
                {embedDownload && (
                  <div className="mt-2 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-brand-green-soft">{embedDownload.detail || 'Pulling…'}</span>
                      {embedDownload.progress != null && (
                        <span className="font-mono text-brand-green-muted">{embedDownload.progress.toFixed(1)}%</span>
                      )}
                    </div>
                    <Progress
                      value={embedDownload.progress ?? 0}
                      className="h-1.5 bg-brand-border [&>div]:bg-brand-green"
                    />
                  </div>
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-brand-green-soft">
                  Context window (tokens)
                </label>
                <input
                  type="number"
                  min={0}
                  step={1024}
                  value={numCtx}
                  placeholder={modelWindow ? `${modelWindow} (auto)` : 'auto'}
                  onChange={(e) => setNumCtx(e.target.value)}
                  className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft font-mono placeholder:text-brand-green-muted focus:border-brand-green outline-none"
                  data-testid="num-ctx-input"
                />
                <p className="mt-1 text-[11px] text-brand-green-muted">
                  {modelWindow
                    ? `Leave blank to auto-fit the selected model (${modelWindow.toLocaleString()} tokens). `
                    : 'Leave blank to auto-fit the selected model. '}
                  Enter a number to pin a custom window — larger is slower to load and uses more memory.
                </p>
              </div>
              {/* Bug B: shell-tool enable toggle (was LOCALMIND_SHELL_ENABLED env-only) */}
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-medium text-brand-green-soft">Shell tool</p>
                  <p className="mt-0.5 text-[11px] text-brand-green-muted">
                    Lets the agent run system commands (list files, check disk, run scripts). Off by default for safety.
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={shellEnabled}
                  onClick={() => setShellEnabled((v) => !v)}
                  data-testid="shell-enabled-toggle"
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
                    shellEnabled ? 'bg-brand-green/70' : 'bg-brand-border'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 h-4 w-4 rounded-full bg-brand-bg-panel transition-transform ${
                      shellEnabled ? 'translate-x-4' : 'translate-x-0.5'
                    }`}
                  />
                </button>
              </div>
              <button
                onClick={handleSaveLocal}
                className="rounded-lg border border-brand-green/30 bg-brand-green/10 px-3 py-1.5 text-xs font-medium text-brand-green hover:bg-brand-green/20 transition-colors"
                data-testid="save-local-settings"
              >
                Save local settings
              </button>
            </div>
          </section>

          {/* ── Startup Session ── */}
          <section hidden={page !== SECTION_PAGE['On Startup']}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <RotateCcw className="h-4 w-4 text-brand-green" />
              On Startup
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              Choose what happens when you open LocalMind.
            </p>
            <div className="inline-flex rounded-lg border border-brand-border p-0.5">
              {([['new', 'New chat', MessageSquarePlus], ['resume', 'Resume last', RotateCcw]] as const).map(([id, label, Icon]) => (
                <button
                  key={id}
                  onClick={() => handleChangeStartupSession(id)}
                  aria-pressed={startupSession === id}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    startupSession === id
                      ? 'bg-brand-green/15 text-brand-green'
                      : 'text-brand-green-muted hover:text-brand-green-soft'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[11px] text-brand-green-muted">
              {startupSession === 'resume'
                ? 'Resumes the most recent chat when you launch LocalMind.'
                : 'Always opens a fresh chat on launch.'}
            </p>
          </section>

          {/* ── Reasoning ── */}
          <section hidden={page !== SECTION_PAGE['Reasoning']}>
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
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-brand-green-soft">
                    Total-turn timeout (s)
                  </span>
                  <input
                    type="number"
                    min={180}
                    value={reasoningMaxWallClock}
                    onChange={(e) => setReasoningMaxWallClock(e.target.value)}
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                  />
                </label>
                <div className="flex items-end pb-0.5">
                  <p className="text-[11px] leading-tight text-brand-green-muted">
                    Slow free tiers spend 30-170s per call thinking — a
                    multi-step turn needs more than the 180s default.
                  </p>
                </div>
              </div>
              <div>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-brand-green-soft">
                    Reasoning effort (thinking level)
                  </span>
                  <select
                    value={reasoningEffort}
                    onChange={(e) => setReasoningEffort(e.target.value)}
                    className="w-full rounded-lg border border-brand-border bg-brand-bg-base px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                  >
                    <option value="">Provider default (unbounded)</option>
                    {['none', 'minimal', 'low', 'medium', 'high', 'max', 'xhigh'].map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="mt-1 text-[11px] text-brand-green-muted">
                  Bounds how much GLM thinks — applies to glm-4.5-flash too. Lower = faster, less
                  over-thinking; higher = deeper. Try low/medium on slow free tiers. (A version that
                  doesn&apos;t support a level is ignored safely.)
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
            <section hidden={page !== SECTION_PAGE['Ollama Server URL']}>
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
            <section hidden={page !== SECTION_PAGE['API Keys']}>
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
                {[...PROVIDERS, ...connections.filter((c) => !c.preset).map((c) => ({ id: c.id, name: c.name }))].map((p) => {
                  const hasKey = providerKeys[p.id] ?? connections.find((c) => c.id === p.id)?.api_key_set ?? false;
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

          {/* ── AI Connections — custom OpenAI-compatible endpoints ── */}
          <section hidden={page !== SECTION_PAGE['AI Connections']}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Plug className="h-4 w-4 text-brand-green" />
              AI Connections
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              Point LocalMind at any OpenAI-compatible endpoint — a gateway, a proxy, a
              self-hosted service — without waiting on a built-in provider. Test a
              connection to discover what it actually supports before switching to it.
            </p>

            <div className="space-y-1.5">
              {connections.filter((c) => !c.preset).map((c) => {
                const isEditing = editingConnId === c.id;
                const testResult = connTestResults[c.id];
                const isTesting = connTesting === c.id;
                return (
                  <div key={c.id} className="rounded-lg border border-brand-border overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="truncate text-sm text-brand-green-soft">{c.name}</span>
                        <span className="shrink-0 truncate max-w-[160px] font-mono text-[11px] text-brand-green-muted" title={c.base_url}>
                          {c.base_url}
                        </span>
                        {!c.enabled && (
                          <span className="shrink-0 rounded bg-brand-border px-1.5 py-0.5 text-[10px] text-brand-green-muted">
                            disabled
                          </span>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button
                          onClick={() => handleTestConnection(c.id)}
                          disabled={isTesting || connectionsLoading}
                          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-brand-green-muted hover:bg-brand-border hover:text-brand-green-soft transition-colors disabled:opacity-50"
                          title={`Probe ${c.name}`}
                        >
                          {isTesting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                          Test
                        </button>
                        <button
                          onClick={() => handleToggleConnectionEnabled(c)}
                          disabled={connectionsLoading}
                          className="rounded px-2 py-1 text-xs text-brand-green-muted hover:bg-brand-border hover:text-brand-green-soft transition-colors disabled:opacity-50"
                        >
                          {c.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          onClick={() => {
                            setEditingConnId(isEditing ? '' : c.id);
                            setEditConnDraft({ name: c.name, base_url: c.base_url, model: c.model });
                          }}
                          disabled={connectionsLoading}
                          className="rounded px-2 py-1 text-xs text-brand-green-muted hover:bg-brand-border hover:text-brand-green-soft transition-colors disabled:opacity-50"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleDeleteConnection(c)}
                          disabled={connectionsLoading}
                          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-brand-red hover:bg-brand-red/10 transition-colors disabled:opacity-50"
                          title={`Delete ${c.name}`}
                          aria-label={`Delete ${c.name}`}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </div>

                    {isEditing && (
                      <div className="border-t border-brand-border bg-brand-bg-base p-3 space-y-2">
                        <input
                          type="text"
                          value={editConnDraft.name}
                          onChange={(e) => setEditConnDraft((d) => ({ ...d, name: e.target.value }))}
                          placeholder="Display name"
                          className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                        />
                        <input
                          type="text"
                          value={editConnDraft.base_url}
                          onChange={(e) => setEditConnDraft((d) => ({ ...d, base_url: e.target.value }))}
                          placeholder="https://api.example.com/v1"
                          className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                        />
                        <input
                          type="text"
                          value={editConnDraft.model}
                          onChange={(e) => setEditConnDraft((d) => ({ ...d, model: e.target.value }))}
                          placeholder="Model id"
                          className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                        />
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleSaveConnectionEdit(c.id)}
                            disabled={connectionsLoading}
                            className="flex-1 rounded-lg border border-brand-green/30 bg-brand-green/10 px-4 py-2 text-sm font-medium text-brand-green hover:bg-brand-green/20 transition-colors disabled:opacity-50"
                          >
                            {connectionsLoading ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'Save'}
                          </button>
                          <button
                            onClick={() => setEditingConnId('')}
                            disabled={connectionsLoading}
                            className="rounded-lg border border-brand-border px-4 py-2 text-sm text-brand-green-muted hover:text-brand-green-soft hover:border-brand-green/30 transition-colors disabled:opacity-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}

                    {testResult && (
                      <div className="border-t border-brand-border bg-brand-bg-base px-3 py-2 text-[11px] space-y-1">
                        <div className={`flex items-center gap-1 font-medium ${testResult.ok ? 'text-brand-green' : 'text-brand-red'}`}>
                          {testResult.ok ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                          {testResult.ok ? `Working — ${testResult.latency_ms ?? '?'}ms` : 'Test failed'}
                        </div>
                        <div className="text-brand-green-muted">
                          reachable: {String(testResult.reachable)} · auth: {String(testResult.auth_ok)} ·
                          {' '}streaming: {testResult.streaming_ok === null ? 'unknown' : String(testResult.streaming_ok)} ·
                          {' '}tools: {testResult.tools ?? 'unknown'}
                          {testResult.context_window ? ` · context: ${testResult.context_window.toLocaleString()}` : ''}
                        </div>
                        {testResult.error && (
                          <div className="text-brand-red">{testResult.error}</div>
                        )}
                        {testResult.stored && (
                          <div className="text-brand-green-muted">Learned capabilities saved to this connection.</div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Add-connection form */}
            {newConnDraft ? (
              <div className="mt-2 rounded-lg border border-brand-border bg-brand-bg-base p-3 space-y-2">
                <input
                  type="text"
                  value={newConnDraft.id}
                  onChange={(e) => setNewConnDraft((d) => d && { ...d, id: e.target.value.toLowerCase() })}
                  placeholder="id (lowercase, dashes — e.g. 'atria-proxy')"
                  className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                />
                <input
                  type="text"
                  value={newConnDraft.name}
                  onChange={(e) => setNewConnDraft((d) => d && { ...d, name: e.target.value })}
                  placeholder="Display name"
                  className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft focus:border-brand-green outline-none"
                />
                <input
                  type="text"
                  value={newConnDraft.base_url}
                  onChange={(e) => setNewConnDraft((d) => d && { ...d, base_url: e.target.value })}
                  placeholder="https://api.example.com/v1"
                  className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                />
                <input
                  type="text"
                  value={newConnDraft.model}
                  onChange={(e) => setNewConnDraft((d) => d && { ...d, model: e.target.value })}
                  placeholder="Model id"
                  className="w-full rounded-lg border border-brand-border bg-brand-bg-panel px-3 py-2 text-sm text-brand-green-soft font-mono focus:border-brand-green outline-none"
                />
                <div className="flex gap-3 text-xs text-brand-green-muted">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={newConnDraft.tool_calling}
                      onChange={(e) => setNewConnDraft((d) => d && { ...d, tool_calling: e.target.checked })}
                    />
                    Supports tool calling
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={newConnDraft.streaming}
                      onChange={(e) => setNewConnDraft((d) => d && { ...d, streaming: e.target.checked })}
                    />
                    Supports streaming
                  </label>
                </div>
                <p className="text-[11px] text-brand-green-muted">
                  An API key (if the endpoint needs one) can be added below via "Add Key" once
                  the connection is created — it appears alongside the built-in providers.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleCreateConnection}
                    disabled={connectionsLoading}
                    className="flex-1 rounded-lg border border-brand-green/30 bg-brand-green/10 px-4 py-2 text-sm font-medium text-brand-green hover:bg-brand-green/20 transition-colors disabled:opacity-50"
                  >
                    {connectionsLoading ? <Loader2 className="h-4 w-4 animate-spin mx-auto" /> : 'Create connection'}
                  </button>
                  <button
                    onClick={() => setNewConnDraft(null)}
                    disabled={connectionsLoading}
                    className="rounded-lg border border-brand-border px-4 py-2 text-sm text-brand-green-muted hover:text-brand-green-soft hover:border-brand-green/30 transition-colors disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setNewConnDraft({ id: '', name: '', base_url: '', model: '', tool_calling: true, streaming: true })}
                className="mt-2 rounded-lg border border-brand-border px-3 py-1.5 text-xs text-brand-green hover:bg-brand-green/10 transition-colors"
              >
                + Add connection
              </button>
            )}
          </section>

          {/* ── Operation Permissions ── */}
          <section hidden={page !== SECTION_PAGE['Permissions']}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Shield className="h-4 w-4 text-brand-green" />
              Permissions
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              Control which operations the agent can perform. Disabled tools will return an error when invoked.
            </p>
            <div className="space-y-2">
              {([
                ['file_read', 'File read'],
                ['file_write', 'File write'],
                ['file_edit', 'File edit'],
                ['shell', 'Shell commands'],
                ['code_exec', 'Code execution'],
                ['web_search', 'Web search'],
                ['web_fetch', 'Web fetch'],
                ['memory_op', 'Memory operations'],
              ] as const).map(([key, label]) => (
                <label key={key} className="flex items-center justify-between rounded-lg border border-brand-border px-3 py-2 cursor-pointer hover:border-brand-green/30 transition-colors">
                  <span className="text-xs text-brand-green-soft">{label}</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={permissions[key] ?? true}
                    onClick={() => {
                      const next = { ...permissions, [key]: !(permissions[key] ?? true) };
                      setPermissions(next);
                      localmindClient.setPermissions({ [key]: next[key] }).catch(() => {});
                    }}
                    className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-green ${
                      permissions[key] !== false ? 'bg-brand-green' : 'bg-brand-border'
                    }`}
                  >
                    <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg ring-0 transition-transform duration-200 ease-in-out ${
                      permissions[key] !== false ? 'translate-x-4' : 'translate-x-0'
                    }`} />
                  </button>
                </label>
              ))}
            </div>
          </section>

          {/* ── Best-of-N Editor (C2 spec step 7) ── */}
          <section hidden={page !== SECTION_PAGE['Best-of-N Editor']}>
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

          {/* ── Package installs ── */}
          <section hidden={page !== SECTION_PAGE['Package installs']}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium text-brand-green-soft">
              <Download className="h-4 w-4 text-brand-green" />
              Package installs
            </h3>
            <p className="mb-3 text-xs text-brand-green-muted">
              Where <code className="font-mono">pip install</code> puts things when you or the agent install a Python
              package. LocalMind's own folder keeps your system Python untouched; System installs like running pip yourself.
            </p>
            <PackageEnvChoice />
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
      </div>
    </div>
  );
}
