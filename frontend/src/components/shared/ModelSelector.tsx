'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { Check, ChevronsUpDown, Search } from 'lucide-react';
import { ModelOption } from '@/types';

interface ModelSelectorProps {
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  models?: ModelOption[];
}

export function ModelSelector({ selectedModel, onModelChange, models }: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  // Use API-provided models, or empty list while loading.
  // Previously this fell back to a hardcoded list of 5 Ollama models
  // (Qwen3-235B, DeepSeek-R1, etc.), which caused the sidebar to show
  // "Qwen3-235B-A22B" even when the backend was using a cloud provider.
  const modelList = models || [];

  // Some providers (Zen) expose 60+ models. Scrolling a tall dropdown to
  // reach one is painful (and unreliable on macOS). A type-to-filter box
  // makes any model reachable in a couple of keystrokes.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return modelList;
    return modelList.filter(
      (m) => m.id.toLowerCase().includes(q) || (m.name || '').toLowerCase().includes(q),
    );
  }, [modelList, query]);

  // Focus the search box and reset the filter each time the menu opens.
  useEffect(() => {
    if (open) {
      setQuery('');
      const id = requestAnimationFrame(() => searchRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
  }, [open]);

  // Find the current model in the list. If not found (e.g. the backend's
  // current model isn't in the available list), synthesize a display entry
  // so the button shows the actual model name, not a random fallback.
  const fromList = modelList.find((m) => m.id === selectedModel);
  const current: ModelOption = fromList || {
    id: selectedModel,
    name: selectedModel || 'Loading…',
    provider: '',
    size: '',
  };

  // Show all models in a single list — the old free/paid split based on
  // the word "free" in the model ID was unreliable (GLM's free models use
  // "flash" not "free", Zen's free models use "-free" suffix, etc.).
  // Showing all models without categorization is simpler and less misleading.

  return (
    <div className="relative">
      <button
        data-testid="model-selector-trigger"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-brand-green-muted hover:text-brand-green-soft hover:bg-brand-border transition-colors w-full"
      >
        <span className="truncate flex-1 text-left">{current.name}</span>
        <ChevronsUpDown className="h-3 w-3 shrink-0" />
      </button>

      {open && (
        <>
          {/* Click-away layer so the menu closes and scroll/focus behaves
              predictably (macOS Electron can otherwise trap the open state). */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute top-full left-0 right-0 mt-1 bg-brand-bg-rail border border-brand-border rounded-md shadow-xl z-50 overflow-hidden">
            {/* Search filter — 60+ models are unreachable by scrolling alone */}
            <div className="p-1.5 border-b border-brand-border">
              <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-brand-bg-base border border-brand-border">
                <Search className="h-3 w-3 text-brand-green-muted shrink-0" />
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setOpen(false);
                    if (e.key === 'Enter' && filtered.length > 0) {
                      onModelChange(filtered[0].id);
                      setOpen(false);
                    }
                  }}
                  placeholder="Search models…"
                  className="flex-1 min-w-0 bg-transparent text-xs text-brand-green-soft placeholder:text-brand-green-muted outline-none"
                  data-testid="model-search"
                />
              </div>
            </div>

            <div className="p-1 max-h-[280px] overflow-y-auto overscroll-contain model-scrollbar" data-testid="model-list">
              {modelList.length === 0 && (
                <div className="px-2 py-2 text-xs text-brand-green-muted">
                  Loading models…
                </div>
              )}

              {modelList.length > 0 && filtered.length === 0 && (
                <div className="px-2 py-2 text-xs text-brand-green-muted">
                  No models match “{query}”.
                </div>
              )}

              {filtered.map((model, idx) => (
                <button
                  key={`${model.id}-${idx}`}
                  onClick={() => {
                    onModelChange(model.id);
                    setOpen(false);
                  }}
                  className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-xs hover:bg-brand-border transition-colors"
                >
                  <span className="w-3.5 flex items-center justify-center">
                    {model.id === selectedModel && (
                      <Check className="h-3 w-3 text-brand-green" />
                    )}
                  </span>
                  <span className="flex-1 text-left text-brand-green-soft truncate">
                    {model.name}
                  </span>
                  <span className="text-brand-green-muted text-[10px]">{model.size}</span>
                </button>
              ))}
            </div>
            <div className="border-t border-brand-border px-2 py-1.5 flex items-center justify-between">
              <div className="text-[10px] text-brand-green-muted">
                Provider: <span className="text-brand-green-soft">{current.provider}</span>
              </div>
              <div className="text-[10px] text-brand-green-muted">{filtered.length} models</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
