'use client';

import {
  Target,
  Gauge,
  Wrench,
  Brain,
  Activity,
} from 'lucide-react';
import { ObservationData } from '@/types';

interface ObservabilityTabProps {
  observation: ObservationData;
}

const intentLabels: Record<string, { label: string; color: string }> = {
  code: { label: 'Code Generation', color: 'text-[#39d353]' },
  file: { label: 'File Operation', color: 'text-[#e8a420]' },
  chat: { label: 'Conversation', color: 'text-[#8ab08a]' },
  search: { label: 'Web Search', color: 'text-[#e8a420]' },
  shell: { label: 'Shell Command', color: 'text-[#39d353]' },
  memory: { label: 'Memory Operation', color: 'text-[#8ab08a]' },
};

// Human-readable labels for raw tool names displayed in "Tools Used" section
const toolDisplayLabels: Record<string, string> = {
  file_write: 'File Write',
  file_read: 'File Read',
  file_task: 'File Read',
  edit_file: 'File Edit',
  code_exec: 'Code Exec',
  shell: 'Shell',
  memory_op: 'Memory',
  web_search: 'Web Search',
  sysinfo: 'System',
  grep: 'Grep',
};

function MetricBar({ label, value, max, color, fallback }: { label: string; value: number; max: number; color: string; fallback?: string }) {
  // Guard against NaN/undefined values
  const safeValue = Number.isFinite(value) ? value : 0;
  const safeMax = Number.isFinite(max) && max > 0 ? max : 1;
  const percentage = Math.min((safeValue / safeMax) * 100, 100);
  const displayValue = safeValue > 0 ? safeValue : (fallback || '0');
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[#8ab08a]">{label}</span>
        <span className="text-[10px] text-[#d4e8d4] font-mono">{displayValue}</span>
      </div>
      <div className="h-1 bg-[#1a2a1a] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

export function ObservabilityTab({ observation }: ObservabilityTabProps) {
  // Guard all numeric values against NaN/undefined. Track "availability"
  // so we can show "—" instead of "0" when the backend hasn't sent data yet.
  const confidence = Number.isFinite(observation.confidence) ? observation.confidence : 0;
  const contextTokens = Number.isFinite(observation.contextTokens) ? observation.contextTokens : 0;
  const latency = Number.isFinite(observation.latency) ? observation.latency : 0;
  const memoryHits = Number.isFinite(observation.memoryHits) ? observation.memoryHits : 0;
  const toolsUsed = observation.toolsUsed ?? [];

  // Whether real data has been received (vs. initial zeros).
  // Don't check observation.intent — the default state has intent='chat',
  // which would make hasData always true and mask the empty state.
  const hasData = observation.confidence > 0 || toolsUsed.length > 0 || latency > 0;

  const intentConfig = hasData
    ? (intentLabels[observation.intent] || { label: observation.intent || 'Unknown', color: 'text-[#8ab08a]', bg: 'bg-[#1a2a1a]' })
    : intentLabels.chat;

  // FIX: Dynamic pipeline status — previously the pipeline was hardcoded
  // with steps 3/5 done. Now we infer status from the observation data:
  // - "done" = a turn_complete or tool dispatch was observed
  // - "running" = we have an intent but no completion yet
  // - "pending" = no data yet
  const hasIntent = !!observation.intent;
  const hasToolCall = (observation.toolsUsed ?? []).length > 0;
  const hasCompletion = observation.latency !== undefined && observation.latency > 0;

  const pipelineSteps = [
    { name: 'Intent Classify', status: hasIntent ? 'done' : 'pending' },
    { name: 'Context Build', status: hasIntent ? (hasToolCall || hasCompletion ? 'done' : 'running') : 'pending' },
    { name: 'Tool Select', status: hasToolCall ? 'done' : hasIntent ? 'running' : 'pending' },
    { name: 'Generate', status: hasCompletion ? 'done' : hasToolCall ? 'running' : 'pending' },
    { name: 'Execute', status: hasCompletion ? 'done' : 'pending' },
  ];

  function stepIcon(status: string) {
    switch (status) {
      case 'done': return 'bg-[#39d353]';
      case 'running': return 'bg-[#e8a420]';
      default: return 'bg-[#8ab08a]';
    }
  }

  function stepTextClass(status: string) {
    switch (status) {
      case 'done': return 'text-[#d4e8d4]';
      case 'running': return 'text-[#e8a420]';
      default: return 'text-[#8ab08a]';
    }
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  function stepSuffix(status: string) {
    switch (status) {
      case 'done': return '\u2713';    // checkmark
      case 'running': return '\u25CF'; // filled circle
      default: return '\u25CB';        // empty circle
    }
  }

  return (
    <div className="space-y-4 p-3">
      {/* Intent Classification */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Target className="h-3 w-3 text-[#e8a420]" />
          <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
            Intent Classification
          </span>
        </div>
        <div className="bg-[#0a120a] border border-[#1a2a1a] rounded-md px-3 py-2">
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-medium ${intentConfig.color}`}>
              {hasData ? intentConfig.label : '—'}
            </span>
            <span className="text-[10px] text-[#d4e8d4] font-mono">
              {confidence > 0 ? `${Math.round(confidence * 100)}%` : '—'}
            </span>
          </div>
          <div className="h-1 bg-[#1a2a1a] rounded-full overflow-hidden mt-1.5">
            <div
              className="h-full bg-[#39d353] rounded-full"
              style={{ width: `${confidence * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Performance */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Gauge className="h-3 w-3 text-[#e8a420]" />
          <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
            Performance
          </span>
        </div>
        <div className="space-y-2">
          <MetricBar label="Confidence" value={hasData ? Math.round(confidence * 100) : 0} max={100} color="bg-[#39d353]" fallback="—" />
          <MetricBar label="Context Tokens" value={contextTokens} max={32768} color="bg-[#e8a420]" fallback="—" />
          <MetricBar label="Latency" value={latency} max={10000} color="bg-[#e05555]" fallback="—" />
        </div>
      </div>

      {/* Tools Used */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Wrench className="h-3 w-3 text-[#e8a420]" />
          <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
            Tools Used
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {toolsUsed.length > 0 ? toolsUsed.map((tool) => (
            <span
              key={tool}
              className="px-1.5 py-0.5 rounded bg-[#1a2a1a] text-[10px] text-[#39d353] font-mono"
              title={tool}
            >
              {toolDisplayLabels[tool] || tool.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())}
            </span>
          )) : (
            <span className="text-[10px] text-[#8ab08a]">{hasData ? 'None' : '—'}</span>
          )}
        </div>
      </div>

      {/* Memory Hits */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Brain className="h-3 w-3 text-[#e8a420]" />
          <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
            Memory
          </span>
        </div>
        <div className="bg-[#0a120a] border border-[#1a2a1a] rounded-md px-3 py-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[#8ab08a]">Vector Store Hits</span>
            <span className="text-[11px] text-[#d4e8d4] font-mono">{memoryHits > 0 ? memoryHits : '—'}</span>
          </div>
        </div>
      </div>

      {/* Pipeline — dynamic status based on observation data */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Activity className="h-3 w-3 text-[#e8a420]" />
          <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
            Agent Pipeline
          </span>
        </div>
        <div className="space-y-1">
          {pipelineSteps.map((step, i) => (
            <div key={step.name} className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${stepIcon(step.status)}`} />
              <span className={`text-[10px] ${stepTextClass(step.status)}`}>
                {step.name}
              </span>
              {i < pipelineSteps.length - 1 && (
                <span className="text-[9px] text-[#5a7a5a] ml-auto">
                  →
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Runtime snapshot — populated only by the structured observation API. */}
      {observation.observation && (
        <RuntimeSnapshot summary={observation.observation} />
      )}
    </div>
  );
}

function RuntimeSnapshot({ summary }: { summary: NonNullable<ObservationData['observation']> }) {
  const { workspace, recentEvents } = summary;
  const build = workspace.lastBuildResult;
  const eventItems = recentEvents.slice(-20);
  const workspaceState = workspace.gitStatus.trim() || 'Clean or unavailable';
  const buildLabel = build?.result || (build ? 'Completed' : 'No build recorded');

  return (
    <section aria-labelledby="runtime-snapshot-heading" className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Activity className="h-3 w-3 text-[#e8a420]" aria-hidden="true" />
        <h2 id="runtime-snapshot-heading" className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
          Runtime Snapshot
        </h2>
      </div>

      <div className="bg-[#0a120a] border border-[#1a2a1a] rounded-md p-2.5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] text-[#8ab08a]">Workspace</span>
          <span className={`text-[10px] font-mono ${workspace.gitAvailable ? 'text-[#39d353]' : 'text-[#8ab08a]'}`}>
            {workspace.gitAvailable ? (workspace.gitBranch || 'git available') : 'git unavailable'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2 text-[10px]">
          <div className="min-w-0">
            <div className="text-[#5a7a5a]">Working tree</div>
            <div className="text-[#d4e8d4] truncate" title={workspaceState}>
              {workspaceState}
            </div>
          </div>
          <div className="min-w-0">
            <div className="text-[#5a7a5a]">Open files</div>
            <div className="text-[#d4e8d4] font-mono">
              {workspace.openFiles.length || '—'}
            </div>
          </div>
        </div>

        {workspace.gitDiffStat && (
          <div className="text-[10px] text-[#8ab08a] truncate" title={workspace.gitDiffStat}>
            diff: <span className="text-[#d4e8d4] font-mono">{workspace.gitDiffStat}</span>
          </div>
        )}

        <div className="flex items-center justify-between gap-2 border-t border-[#1a2a1a] pt-2">
          <span className="text-[10px] text-[#8ab08a]">Last build</span>
          <span className={`text-[10px] font-mono ${build?.result === 'success' ? 'text-[#39d353]' : 'text-[#d4e8d4]'}`}>
            {buildLabel}
          </span>
        </div>

        {eventItems.length > 0 && (
          <div className="border-t border-[#1a2a1a] pt-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] text-[#8ab08a]">Recent events</span>
              <span className="text-[9px] text-[#5a7a5a] font-mono">{eventItems.length}</span>
            </div>
            <div className="max-h-40 overflow-y-auto space-y-1 pr-1" aria-label="Recent runtime events">
              {eventItems.map((event, index) => (
                <div key={`${event.type}-${index}`} className="rounded bg-[#111d11] px-2 py-1.5 min-w-0">
                  <div className="text-[10px] text-[#39d353] font-mono truncate" title={event.type}>
                    {event.type}
                  </div>
                  <div className="text-[9px] text-[#8ab08a] font-mono break-all line-clamp-2">
                    {formatEventData(event.data)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function formatEventData(data: Record<string, unknown>): string {
  try {
    const serialized = JSON.stringify(data);
    if (!serialized) return 'No event data';
    return serialized.length > 240 ? `${serialized.slice(0, 237)}...` : serialized;
  } catch {
    return 'Event data unavailable';
  }
}
