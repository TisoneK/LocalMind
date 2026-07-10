'use client';

import { useState } from 'react';
import { Check, ChevronsUpDown } from 'lucide-react';
import { ModelOption } from '@/types';

interface ModelSelectorProps {
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  models?: ModelOption[];
}

export function ModelSelector({ selectedModel, onModelChange, models }: ModelSelectorProps) {
  const [open, setOpen] = useState(false);

  // Use API-provided models, or empty list while loading.
  // Previously this fell back to a hardcoded list of 5 Ollama models
  // (Qwen3-235B, DeepSeek-R1, etc.), which caused the sidebar to show
  // "Qwen3-235B-A22B" even when the backend was using a cloud provider.
  const modelList = models || [];

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
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-[#8ab08a] hover:text-[#d4e8d4] hover:bg-[#1a2a1a] transition-colors w-full"
      >
        <span className="truncate flex-1 text-left">{current.name}</span>
        <ChevronsUpDown className="h-3 w-3 shrink-0" />
      </button>

      {open && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-[#111a11] border border-[#1a2a1a] rounded-md shadow-xl z-50 overflow-hidden">
          <div className="p-1 max-h-[300px] overflow-y-auto custom-scrollbar">
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
              Models
            </div>

            {modelList.length === 0 && (
              <div className="px-2 py-2 text-xs text-[#8ab08a]">
                Loading models…
              </div>
            )}

            {modelList.map((model, idx) => (
              <button
                key={`${model.id}-${idx}`}
                onClick={() => {
                  onModelChange(model.id);
                  setOpen(false);
                }}
                className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-xs hover:bg-[#1a2a1a] transition-colors"
              >
                <span className="w-3.5 flex items-center justify-center">
                  {model.id === selectedModel && (
                    <Check className="h-3 w-3 text-[#39d353]" />
                  )}
                </span>
                <span className="flex-1 text-left text-[#d4e8d4] truncate">
                  {model.name}
                </span>
                <span className="text-[#8ab08a] text-[10px]">{model.size}</span>
              </button>
            ))}
          </div>
          <div className="border-t border-[#1a2a1a] px-2 py-1.5">
            <div className="text-[10px] text-[#8ab08a]">
              Provider: <span className="text-[#d4e8d4]">{current.provider}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
