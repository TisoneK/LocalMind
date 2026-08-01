'use client';

import { useState } from 'react';
import { CheckCircle2, CirclePause, Loader2, Play, Plus, Square, TriangleAlert } from 'lucide-react';
import type { Objective } from '@/types';

interface ObjectivesPanelProps {
  objectives: Objective[];
  currentSessionId: string | null;
  onCreate: (prompt: string) => Promise<void>;
  onPause: (id: string) => Promise<void>;
  onResume: (id: string) => Promise<void>;
  onCancel: (id: string) => Promise<void>;
}

const STATUS_LABELS: Record<Objective['status'], string> = {
  queued: 'Queued',
  running: 'Working',
  paused: 'Paused',
  blocked: 'Needs approval',
  completed: 'Complete',
  failed: 'Failed',
  canceled: 'Canceled',
};

export function ObjectivesPanel({
  objectives,
  currentSessionId,
  onCreate,
  onPause,
  onResume,
  onCancel,
}: ObjectivesPanelProps) {
  const [prompt, setPrompt] = useState('');
  const [showInput, setShowInput] = useState(false);
  const [saving, setSaving] = useState(false);

  const active = objectives.filter((item) => ['queued', 'running', 'blocked', 'paused'].includes(item.status));

  const handleCreate = async () => {
    const value = prompt.trim();
    if (!currentSessionId || !value || saving) return;
    setSaving(true);
    try {
      await onCreate(value);
      setPrompt('');
      setShowInput(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="border-t border-[#1a2a1a] px-3 py-3">
      <div className="flex items-center gap-1.5 mb-2">
        <div className="w-1.5 h-1.5 rounded-full bg-[#39d353] shadow-[0_0_8px_rgba(57,211,83,0.7)]" />
        <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">Autonomous work</span>
        {active.length > 0 && (
          <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded-full bg-[#39d353]/10 text-[#39d353] font-mono">
            {active.length} active
          </span>
        )}
        <button
          onClick={() => setShowInput((value) => !value)}
          disabled={!currentSessionId}
          className="ml-auto p-0.5 rounded text-[#8ab08a] hover:text-[#39d353] hover:bg-[#1a2a1a] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title={currentSessionId ? 'Start background work' : 'Start a chat first to create background work'}
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>

      {!currentSessionId && (
        <div className="mb-2 text-[9px] text-[#5a7a5a] italic">
          Start or select a chat before creating background work.
        </div>
      )}

      {showInput && currentSessionId && (
        <div className="mb-2 space-y-1.5">
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void handleCreate();
              }
              if (event.key === 'Escape') {
                setShowInput(false);
                setPrompt('');
              }
            }}
            placeholder="e.g. Research the latest FastAPI lifespan guidance and summarize it"
            rows={3}
            autoFocus
            className="w-full resize-none bg-[#111a11] border border-[#1a2a1a] rounded px-2 py-1.5 text-[10px] leading-relaxed text-[#d4e8d4] placeholder:text-[#5a7a5a] outline-none focus:border-[#39d353]/40"
          />
          <div className="flex items-center justify-between">
            <span className="text-[9px] text-[#5a7a5a]">Ctrl/Cmd + Enter to start</span>
            <button
              onClick={() => void handleCreate()}
              disabled={!currentSessionId || !prompt.trim() || saving}
              className="flex items-center gap-1 px-2 py-1 rounded bg-[#39d353]/10 text-[#39d353] text-[10px] hover:bg-[#39d353]/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
              Start
            </button>
          </div>
        </div>
      )}

      <div className="space-y-1.5 max-h-52 overflow-y-auto custom-scrollbar">
        {objectives.length === 0 && !showInput && (
          <div className="text-[10px] text-[#5a7a5a] italic">
            No background work yet — click + to start an objective.
          </div>
        )}
        {objectives.map((objective) => {
          const isRunning = objective.status === 'running';
          const canResume = ['paused', 'blocked', 'failed'].includes(objective.status);
          const statusColor = objective.status === 'completed'
            ? 'text-[#39d353]'
            : objective.status === 'failed' || objective.status === 'canceled'
              ? 'text-[#e05555]'
              : objective.status === 'blocked'
                ? 'text-[#e8a420]'
                : 'text-[#8ab08a]';
          return (
            <div key={objective.id} className="rounded border border-[#1a2a1a] bg-[#111a11]/60 p-2">
              <div className="flex items-start gap-1.5">
                <span className={`mt-0.5 ${statusColor}`}>
                  {objective.status === 'completed' ? <CheckCircle2 className="h-3 w-3" />
                    : objective.status === 'failed' || objective.status === 'blocked' ? <TriangleAlert className="h-3 w-3" />
                      : isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <div className="h-3 w-3 rounded-full border border-current" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] leading-relaxed text-[#d4e8d4] line-clamp-2" title={objective.prompt}>
                    {objective.prompt}
                  </div>
                  <div className={`mt-1 text-[9px] ${statusColor}`}>
                    {STATUS_LABELS[objective.status] || objective.status}
                    {objective.lastEvent ? ` · ${objective.lastEvent.replaceAll('_', ' ')}` : ''}
                  </div>
                  {objective.result && (objective.status === 'completed' || objective.status === 'blocked') && (
                    <div className="mt-1 text-[9px] text-[#8ab08a] line-clamp-3">{objective.result}</div>
                  )}
                  {objective.error && <div className="mt-1 text-[9px] text-[#e05555] line-clamp-2">{objective.error}</div>}
                </div>
              </div>
              <div className="flex items-center justify-end gap-1 mt-1.5">
                {isRunning && (
                  <button onClick={() => void onPause(objective.id)} className="p-1 rounded text-[#e8a420] hover:bg-[#e8a420]/10" title="Pause objective">
                    <CirclePause className="h-3 w-3" />
                  </button>
                )}
                {canResume && (
                  <button onClick={() => void onResume(objective.id)} className="p-1 rounded text-[#39d353] hover:bg-[#39d353]/10" title="Resume objective">
                    <Play className="h-3 w-3" />
                  </button>
                )}
                {!['completed', 'failed', 'canceled'].includes(objective.status) && (
                  <button onClick={() => void onCancel(objective.id)} className="p-1 rounded text-[#e05555] hover:bg-[#e05555]/10" title="Cancel objective">
                    <Square className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
