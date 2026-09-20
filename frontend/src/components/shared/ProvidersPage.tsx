/**
 * ProvidersPage — every AI provider in one place: a list on the left, and the selected provider's
 * settings on the right (on/off, address, key, models, fallback). Providers you have set up come
 * first; the rest of the built-in ones sit under "More providers" until you need them; "Add
 * provider" makes a custom OpenAI-compatible endpoint.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Eye, EyeOff, Loader2, Plus, RefreshCw, Trash2, Zap } from 'lucide-react';
import { localmindClient, type ConnectionRecord, type ConnectionTestResult } from '@/lib/localmind/client';
import type { ModelOption } from '@/types';

type Health = 'ready' | 'needs-key' | 'off';

export function providerHealth(c: Pick<ConnectionRecord, 'enabled' | 'api_key_set' | 'kind'>): Health {
  if (!c.enabled) return 'off';
  if (c.kind === 'ollama') return 'ready';
  return c.api_key_set ? 'ready' : 'needs-key';
}

const DOT: Record<Health, string> = {
  ready: 'bg-brand-green',
  'needs-key': 'bg-brand-amber',
  off: 'bg-brand-border',
};

const HEALTH_TEXT: Record<Health, string> = {
  ready: 'Ready',
  'needs-key': 'Needs an API key',
  off: 'Off',
};

/** Providers you have set up (custom, or with a key, or the one in use) versus the rest of the built-ins. */
export function splitProviders(all: ConnectionRecord[], active: string) {
  const mine = all.filter((c) => !c.preset || c.api_key_set || c.id === active || c.kind === 'ollama');
  const more = all.filter((c) => !mine.includes(c));
  return { mine, more };
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${on ? 'bg-brand-green' : 'bg-brand-border'}`}
    >
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${on ? 'left-[18px]' : 'left-0.5'}`} />
    </button>
  );
}

interface Props {
  /** Called after anything that changes what the rest of the app should show (active provider, models). */
  onChanged?: () => void;
}

export function ProvidersPage({ onChanged }: Props) {
  const [connections, setConnections] = useState<ConnectionRecord[]>([]);
  const [active, setActive] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [filter, setFilter] = useState('');
  const [adding, setAdding] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    try {
      const s = await localmindClient.getSettings();
      const list = ((s as unknown as { connections?: ConnectionRecord[] }).connections ?? []) as ConnectionRecord[];
      setConnections(list);
      setActive((s as unknown as { adapter?: string }).adapter ?? '');
      setSelectedId((cur) => cur || (s as unknown as { adapter?: string }).adapter || list[0]?.id || '');
    } catch {
      /* offline: an empty list says so */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const selected = connections.find((c) => c.id === selectedId) ?? null;
  const q = filter.trim().toLowerCase();
  const visible = connections.filter((c) => !q || c.name.toLowerCase().includes(q) || c.id.includes(q));
  const { mine, more } = useMemo(() => splitProviders(visible, active), [visible, active]);

  const row = (c: ConnectionRecord) => (
    <button
      key={c.id}
      type="button"
      onClick={() => {
        setSelectedId(c.id);
        setAdding(false);
      }}
      aria-current={selectedId === c.id && !adding ? 'true' : undefined}
      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors ${
        selectedId === c.id && !adding ? 'bg-brand-green/10 text-brand-green' : 'text-brand-green-soft hover:bg-brand-border/40'
      }`}
    >
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-brand-border/60 text-[10px] font-medium uppercase">
        {c.name.slice(0, 1)}
      </span>
      <span className="min-w-0 flex-1 truncate">{c.name.replace(/\s*\(.*\)$/, '')}</span>
      {c.id === active && <span className="rounded bg-brand-green/15 px-1 text-[9px] text-brand-green">in use</span>}
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[providerHealth(c)]}`} title={HEALTH_TEXT[providerHealth(c)]} />
    </button>
  );

  return (
    <div className="flex min-h-[420px] gap-4" data-testid="providers-page">
      <aside className="w-56 shrink-0">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search providers"
          aria-label="Search providers"
          className="mb-2 w-full rounded-md border border-brand-border bg-transparent px-2.5 py-1.5 text-[12px] text-brand-green-soft outline-none placeholder:text-brand-green-muted focus:border-brand-green/40"
        />
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="mb-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-brand-green/30 bg-brand-green/10 px-2.5 py-1.5 text-[12px] text-brand-green hover:bg-brand-green/20"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden /> Add provider
        </button>
        {mine.length > 0 && <div className="px-2 pb-1 text-[10px] uppercase tracking-wider text-brand-green-faint">Your providers</div>}
        <div className="space-y-0.5">{mine.map(row)}</div>
        {more.length > 0 && (
          <>
            <div className="px-2 pb-1 pt-3 text-[10px] uppercase tracking-wider text-brand-green-faint">More providers</div>
            <div className="space-y-0.5">{more.map(row)}</div>
          </>
        )}
        {loaded && connections.length === 0 && <p className="px-2 text-xs text-brand-green-muted">Couldn&apos;t load providers.</p>}
      </aside>

      <section className="min-w-0 flex-1">
        {adding ? (
          <AddProvider
            existingIds={connections.map((c) => c.id)}
            onCancel={() => setAdding(false)}
            onCreated={async (id) => {
              setAdding(false);
              await reload();
              setSelectedId(id);
              onChanged?.();
            }}
          />
        ) : selected ? (
          <ProviderDetail
            key={selected.id}
            conn={selected}
            all={connections}
            active={active}
            onChanged={async () => {
              await reload();
              onChanged?.();
            }}
            onDeleted={async () => {
              setSelectedId('');
              await reload();
              onChanged?.();
            }}
          />
        ) : (
          loaded && <p className="text-sm text-brand-green-muted">Pick a provider on the left.</p>
        )}
      </section>
    </div>
  );
}

/* ─────────────────────────── detail ─────────────────────────── */

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-4">
      <div className="mb-1 text-[12px] text-brand-green-muted">{label}</div>
      {children}
      {hint && <p className="mt-1 text-[11px] text-brand-green-faint">{hint}</p>}
    </div>
  );
}

const INPUT =
  'w-full rounded-md border border-brand-border bg-transparent px-3 py-2 text-[13px] text-brand-green-soft outline-none placeholder:text-brand-green-muted focus:border-brand-green/40 disabled:opacity-60';

function ProviderDetail({
  conn,
  all,
  active,
  onChanged,
  onDeleted,
}: {
  conn: ConnectionRecord;
  all: ConnectionRecord[];
  active: string;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
}) {
  const custom = !conn.preset;
  const [name, setName] = useState(conn.name);
  const [baseUrl, setBaseUrl] = useState(conn.base_url);
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [currentModel, setCurrentModel] = useState(conn.model);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [newModel, setNewModel] = useState('');
  const [test, setTest] = useState<ConnectionTestResult | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const say = (tone: 'ok' | 'bad', text: string) => setNote({ tone, text });

  const loadModels = useCallback(async () => {
    if (conn.kind === 'ollama') return;
    setModelsLoading(true);
    try {
      const r = await localmindClient.getModels(conn.id);
      setModels(r.models);
      setCurrentModel(r.current || conn.model);
    } catch {
      setModels([]);
    } finally {
      setModelsLoading(false);
    }
  }, [conn.id, conn.kind, conn.model]);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  const save = async (patch: Parameters<typeof localmindClient.saveConnection>[0], ok?: string) => {
    setBusy(true);
    try {
      await localmindClient.saveConnection({ id: conn.id, ...patch });
      if (ok) say('ok', ok);
      await onChanged();
      return true;
    } catch (e) {
      say('bad', e instanceof Error ? e.message : 'Could not save');
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveKey = async () => {
    if (!apiKey.trim()) return;
    setBusy(true);
    try {
      const r = await localmindClient.setProviderKey(conn.id, apiKey.trim());
      setApiKey('');
      say(r.validated ? 'ok' : 'bad', r.validated ? 'Key saved and working.' : r.validation_error || 'Key saved, but it did not validate.');
      await onChanged();
      await loadModels();
    } catch (e) {
      say('bad', e instanceof Error ? e.message : 'Could not save the key');
    } finally {
      setBusy(false);
    }
  };

  const hidden = new Set(conn.hidden_models ?? []);
  const extras = new Set(conn.extra_models ?? []);

  const toggleModel = (id: string, on: boolean) => {
    const next = new Set(hidden);
    if (on) next.delete(id);
    else next.add(id);
    void save({ hidden_models: [...next] });
  };

  const addModel = async () => {
    const id = newModel.trim();
    if (!id) return;
    setNewModel('');
    await save({ extra_models: [...(conn.extra_models ?? []), id] }, `Added ${id}.`);
    await loadModels();
  };

  const removeModel = async (id: string) => {
    await save({ extra_models: (conn.extra_models ?? []).filter((m) => m !== id) });
    await loadModels();
  };

  const runTest = async () => {
    setBusy(true);
    setTest(null);
    try {
      setTest(await localmindClient.testConnection(conn.id));
    } catch (e) {
      say('bad', e instanceof Error ? e.message : 'Test failed');
    } finally {
      setBusy(false);
    }
  };

  const makeActive = async () => {
    setBusy(true);
    try {
      await localmindClient.setAdapter(conn.id);
      say('ok', `${conn.name} is now the provider in use.`);
      await onChanged();
    } catch (e) {
      say('bad', e instanceof Error ? e.message : 'Could not switch');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      const r = await localmindClient.deleteConnection(conn.id);
      say('ok', r.message);
      await onDeleted();
    } catch (e) {
      say('bad', e instanceof Error ? e.message : 'Could not delete');
      setBusy(false);
    }
  };

  const others = all.filter((c) => c.id !== conn.id && c.enabled);
  const health = providerHealth(conn);

  return (
    <div data-testid="provider-detail">
      <div className="mb-4 flex items-center gap-3">
        <h4 className="min-w-0 flex-1 truncate text-base font-medium text-brand-green-soft">{conn.name}</h4>
        {conn.id !== active && conn.kind !== 'ollama' && (
          <button type="button" onClick={makeActive} disabled={busy || health !== 'ready'} className="rounded-md border border-brand-green/30 px-2.5 py-1 text-[12px] text-brand-green hover:bg-brand-green/10 disabled:opacity-40">
            Use this provider
          </button>
        )}
        {conn.id === active && <span className="rounded bg-brand-green/15 px-2 py-0.5 text-[11px] text-brand-green">In use</span>}
        <Toggle on={conn.enabled} label={`${conn.name} enabled`} onChange={(v) => save({ enabled: v })} />
      </div>

      <div className="mb-4 flex items-center gap-2 text-[11.5px] text-brand-green-muted">
        <span className={`h-1.5 w-1.5 rounded-full ${DOT[health]}`} aria-hidden />
        {HEALTH_TEXT[health]}
      </div>

      {conn.kind !== 'ollama' && (
        <>
          {custom && (
            <Field label="Name">
              <input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== conn.name && save({ name: name.trim() })} aria-label="Name" />
            </Field>
          )}
          <Field label="Base URL">
            <input
              className={INPUT}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              onBlur={() => baseUrl.trim() && baseUrl !== conn.base_url && save({ base_url: baseUrl.trim() }, 'Address saved.')}
              placeholder="https://api.example.com/v1"
              aria-label="Base URL"
            />
          </Field>
          <Field label="API format">
            <select className={INPUT} value="openai" disabled aria-label="API format">
              <option value="openai">Chat completions (/chat/completions)</option>
            </select>
          </Field>
          <Field label="API key" hint={conn.api_key_set ? 'A key is saved. Enter a new one to replace it.' : undefined}>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  className={`${INPUT} pr-9`}
                  type={showKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && void saveKey()}
                  placeholder={conn.api_key_set ? '••••••••••••••••••••' : 'Paste your API key'}
                  aria-label="API key"
                  autoComplete="off"
                  spellCheck={false}
                />
                <button type="button" onClick={() => setShowKey((v) => !v)} aria-label={showKey ? 'Hide key' : 'Show key'} className="absolute right-2 top-1/2 -translate-y-1/2 text-brand-green-muted hover:text-brand-green-soft">
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <button type="button" onClick={saveKey} disabled={busy || !apiKey.trim()} className="rounded-md border border-brand-green/30 bg-brand-green/10 px-3 text-[12px] text-brand-green hover:bg-brand-green/20 disabled:opacity-40">
                Save key
              </button>
              {conn.api_key_set && (
                <button
                  type="button"
                  onClick={async () => {
                    await localmindClient.deleteProviderKey(conn.id);
                    say('ok', 'Key removed.');
                    await onChanged();
                  }}
                  className="rounded-md border border-brand-border px-3 text-[12px] text-brand-green-muted hover:text-brand-red"
                >
                  Remove
                </button>
              )}
            </div>
          </Field>

          <div className="mb-2 flex items-center">
            <div className="flex-1 text-[12px] text-brand-green-muted">Model list</div>
            <button type="button" onClick={loadModels} aria-label="Refresh models" className="mr-2 rounded p-1 text-brand-green-muted hover:text-brand-green-soft">
              {modelsLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            </button>
          </div>
          <div className="mb-3 divide-y divide-brand-border/50 rounded-lg border border-brand-border" data-testid="model-list">
            {models.length === 0 && <p className="px-3 py-3 text-[12px] text-brand-green-muted">{modelsLoading ? 'Loading models…' : 'No models listed. Add one below.'}</p>}
            {models.map((m) => {
              const isDefault = m.id === currentModel;
              return (
                <div key={m.id} className="flex items-center gap-2 px-3 py-2">
                  <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-brand-green-soft">{m.id}</span>
                  {m.contextWindow ? <span className="rounded bg-brand-border/60 px-1.5 text-[10px] text-brand-green-muted">{Math.round(m.contextWindow / 1000)}K</span> : null}
                  <button
                    type="button"
                    onClick={() => save({ model: m.id }, `${m.id} is the default for ${conn.name}.`)}
                    className={`rounded px-1.5 text-[10.5px] ${isDefault ? 'bg-brand-green/15 text-brand-green' : 'text-brand-green-muted hover:text-brand-green-soft'}`}
                    aria-label={`Use ${m.id} by default`}
                    aria-pressed={isDefault}
                  >
                    {isDefault ? 'default' : 'use'}
                  </button>
                  {extras.has(m.id) && (
                    <button type="button" onClick={() => removeModel(m.id)} aria-label={`Remove ${m.id}`} className="text-brand-green-muted hover:text-brand-red">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                  <Toggle on={!hidden.has(m.id)} label={`Show ${m.id} in the model picker`} onChange={(v) => toggleModel(m.id, v)} />
                </div>
              );
            })}
          </div>
          <div className="mb-4 flex gap-2">
            <input className={INPUT} value={newModel} onChange={(e) => setNewModel(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void addModel()} placeholder="Add a model id" aria-label="Add a model id" />
            <button type="button" onClick={addModel} disabled={!newModel.trim() || busy} className="rounded-md border border-brand-border px-3 text-[12px] text-brand-green-soft hover:border-brand-green/40 disabled:opacity-40">
              Add model
            </button>
          </div>

          <Field label="If this provider fails, try" hint="Used automatically when it is rate-limited, out of quota or unreachable.">
            <select className={INPUT} value={conn.fallback_to} onChange={(e) => save({ fallback_to: e.target.value })} aria-label="Fallback provider">
              <option value="">Any other provider with a key</option>
              {others.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </Field>

          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={runTest} disabled={busy} className="flex items-center gap-1.5 rounded-md border border-brand-border px-3 py-1.5 text-[12px] text-brand-green-soft hover:border-brand-green/40 disabled:opacity-40">
              <Zap className="h-3.5 w-3.5" aria-hidden /> Test connection
            </button>
            {test && (
              <span className={`text-[12px] ${test.ok ? 'text-brand-green' : 'text-brand-red'}`} role="status">
                {test.ok ? `Works${test.latency_ms ? ` · ${test.latency_ms} ms` : ''}` : test.error || 'Did not work'}
              </span>
            )}
          </div>
        </>
      )}

      {note && (
        <p role="status" className={`mb-3 text-[12px] ${note.tone === 'ok' ? 'text-brand-green' : 'text-brand-red'}`}>{note.text}</p>
      )}

      {conn.kind !== 'ollama' && (
        <div className="mt-6 border-t border-brand-border pt-4">
          {confirmDelete ? (
            <div className="rounded-lg border border-brand-red/30 bg-brand-red/5 p-3 text-[12px] text-brand-green-soft" role="alertdialog">
              <p className="mb-2">
                {custom
                  ? `Delete ${conn.name}? Its saved API key is removed too, providers that use it as a fallback stop pointing at it${conn.id === active ? ', and LocalMind switches to another ready provider' : ''}. Your chats are not affected.`
                  : `Reset ${conn.name} to its defaults? Its saved key stays.`}
              </p>
              <div className="flex gap-2">
                <button type="button" onClick={remove} disabled={busy} className="rounded-md bg-brand-red/80 px-3 py-1 text-white hover:bg-brand-red disabled:opacity-50">
                  {custom ? 'Delete' : 'Reset'}
                </button>
                <button type="button" onClick={() => setConfirmDelete(false)} className="rounded-md border border-brand-border px-3 py-1 text-brand-green-muted">Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setConfirmDelete(true)} className="flex items-center gap-1.5 text-[12px] text-brand-green-muted hover:text-brand-red">
              <Trash2 className="h-3.5 w-3.5" aria-hidden /> {custom ? 'Delete provider' : 'Reset to defaults'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────── add ─────────────────────────── */

function AddProvider({ existingIds, onCancel, onCreated }: { existingIds: string[]; onCancel: () => void; onCreated: (id: string) => Promise<void> }) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const clash = !!id && existingIds.includes(id);
  const ready = !!id && !clash && !!baseUrl.trim() && !!model.trim();

  const create = async () => {
    setBusy(true);
    setError('');
    try {
      await localmindClient.saveConnection({ id, name: name.trim(), base_url: baseUrl.trim(), model: model.trim() });
      if (apiKey.trim()) await localmindClient.setProviderKey(id, apiKey.trim());
      await onCreated(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the provider');
      setBusy(false);
    }
  };

  return (
    <div data-testid="add-provider">
      <h4 className="mb-1 text-base font-medium text-brand-green-soft">Add a provider</h4>
      <p className="mb-4 text-[12px] text-brand-green-muted">Any service that speaks the OpenAI chat-completions API: a gateway, a proxy, a self-hosted model.</p>
      <Field label="Name" hint={clash ? 'A provider with this name already exists.' : id ? `Saved as “${id}”.` : undefined}>
        <input className={INPUT} value={name} onChange={(e) => setName(e.target.value)} placeholder="My gateway" aria-label="Name" />
      </Field>
      <Field label="Base URL">
        <input className={INPUT} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" aria-label="Base URL" />
      </Field>
      <Field label="Default model">
        <input className={INPUT} value={model} onChange={(e) => setModel(e.target.value)} placeholder="model-id" aria-label="Default model" />
      </Field>
      <Field label="API key (optional now)">
        <input className={INPUT} type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} aria-label="API key" autoComplete="off" />
      </Field>
      {error && <p role="alert" className="mb-3 text-[12px] text-brand-red">{error}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={create} disabled={!ready || busy} className="rounded-md border border-brand-green/30 bg-brand-green/10 px-4 py-1.5 text-[12px] text-brand-green hover:bg-brand-green/20 disabled:opacity-40">
          {busy ? 'Adding…' : 'Add provider'}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md border border-brand-border px-4 py-1.5 text-[12px] text-brand-green-muted">Cancel</button>
      </div>
    </div>
  );
}
