'use client';

import { useState } from 'react';
import { ChevronDown, Check, ChevronsUpDown } from 'lucide-react';
import { ModelOption } from '@/types';

interface ModelSelectorProps {
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  models?: ModelOption[];
}

// Fallback models if none provided by API
const fallbackModels: ModelOption[] = [
  { id: 'qwen3-235b', name: 'Qwen3-235B-A22B', provider: 'Ollama', size: '235B' },
  { id: 'deepseek-r1', name: 'DeepSeek-R1-0528', provider: 'Ollama', size: '671B' },
  { id: 'llama3.3', name: 'Llama 3.3 70B', provider: 'Ollama', size: '70B' },
  { id: 'codestral', name: 'Codestral 22B', provider: 'Ollama', size: '22B' },
  { id: 'mistral-small', name: 'Mistral Small 24B', provider: 'Ollama', size: '24B' },
];

export function ModelSelector({ selectedModel, onModelChange, models }: ModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const modelList = models && models.length > 0 ? models : fallbackModels;
  const current = modelList.find((m) => m.id === selectedModel) || modelList[0];

  // Group models: free vs paid
  const freeModels = modelList.filter((m) => m.id.toLowerCase().includes('free'));
  const paidModels = modelList.filter((m) => !m.id.toLowerCase().includes('free'));

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

            {freeModels.length > 0 && (
              <>
                <div className="px-2 py-1 text-[9px] uppercase tracking-wider text-[#6a8a6a] font-medium mt-1">
                  Free
                </div>
                {freeModels.map((model, idx) => (
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
              </>
            )}

            {paidModels.length > 0 && (
              <>
                <div className="px-2 py-1 text-[9px] uppercase tracking-wider text-[#6a8a6a] font-medium mt-1">
                  Paid
                </div>
                {paidModels.map((model, idx) => (
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
              </>
            )}
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
