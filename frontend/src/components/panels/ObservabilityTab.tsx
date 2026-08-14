'use client';

import {
  Target,
  Gauge,
  Wrench,
  Brain,
  Activity,
  AlertTriangle,
} from 'lucide-react';
import { CapabilitiesData, ObservationData } from '@/types';
import { formatLatency } from '@/lib/localmind/progress';

interface ObservabilityTabProps {
  observation: ObservationData;
  capabilities?: CapabilitiesData;
}

const intentLabels: Record<string, { label: string; color: string }> = {
  code: { label: 'Code Generation', color: 'text-brand-green' },
  file: { label: 'File Operation', color: 'text-brand-amber' },
  chat: { label: 'Conversation', color: 'text-brand-green-muted' },
  search: { label: 'Web Search', color: 'text-brand-amber' },
  shell: { label: 'Shell Command', color: 'text-brand-green' },
  memory: { label: 'Memory Operation', color: 'text-brand-green-muted' },
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
        <span className="text-[10px] text-brand-green-muted">{label}</span>
        <span className="text-[10px] text-brand-green-soft font-mono">{displayValue}</span>
      </div>
      <div className="h-1 bg-brand-border rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

export function ObservabilityTab({ observation, capabilities = { families: [] } }: ObservabilityTabProps) {
  // Guard all numeric values against NaN/undefined. Track "availability"
  // so we can show "—" instead of "0" when the backend hasn't sent data yet.
  const confidence = Number.isFinite(observation.confidence) ? observation.confidence : 0;
  const contextTokens = Number.isFinite(observation.contextTokens) ? observation.contextTokens : 0;
  const latency = Number.isFinite(observation.latency) ? observation.latency : 0;
  const memoryHits = Number.isFinite(observation.memoryHits) ? observation.memoryHits : 0;
  const toolsUsed = observation.toolsUsed ?? [];
  const anomalies = observation.anomalies ?? [];

  // Whether real data has been received (vs. initial zeros).
  // Don't check observation.intent — the default state has intent='chat',
  // which would make hasData always true and mask the empty state.
  const hasData = observation.confidence > 0 || toolsUsed.length > 0 || latency > 0;

  const intentConfig = hasData
    ? (intentLabels[observation.intent] || { label: observation.intent || 'Unknown', color: 'text-brand-green-muted', bg: 'bg-brand-border' })
    : intentLabels.chat;

  // ADR-12 (B-2026-08-09-2): pipeline status. Backend `stageTimings`
  // (from the engine's _StageClock) are AUTHORITATIVE when present — real
  // latency + truthful done/skipped status. The fallback heuristic below
  // is only for turns where the backend hasn't reported stage timings yet,
  // and it now resolves completed no-tool stages to "skipped" instead of
  // leaving "Tool Select" orange forever / "Execute" done with no tools.
  const stageTimings = observation.stageTimings ?? {};
  const hasBackendStages = Object.keys(stageTimings).length > 0;
  const hasIntent = !!observation.intent;
  const hasToolCall = (observation.toolsUsed ?? []).length > 0;
  const hasCompletion = observation.latency !== undefined && observation.latency > 0;

  // Canonical pipeline stages — keys match the engine's _StageClock names.
  const STAGE_KEYS = ['intent_classify', 'context_build', 'agent_initialize', 'tool_select', 'generate', 'execute'] as const;
  const STAGE_LABELS: Record<string, string> = {
    intent_classify: 'Intent Classify',
    context_build: 'Context Build',
    agent_initialize: 'Agent Initialize',
    tool_select: 'Tool Select',
    generate: 'Generate',
    execute: 'Execute',
  };

  function fallbackStatus(key: string): string {
    switch (key) {
      case 'intent_classify': return hasIntent ? 'done' : 'pending';
      case 'context_build': return hasIntent ? (hasToolCall || hasCompletion ? 'done' : 'running') : 'pending';
      case 'agent_initialize': return hasCompletion ? 'done' : hasIntent ? 'running' : 'pending';
      // No tools used + turn complete → the stage never ran → skipped.
      case 'tool_select': return hasToolCall ? 'done' : hasCompletion ? 'skipped' : hasIntent ? 'running' : 'pending';
      case 'generate': return hasCompletion ? 'done' : hasIntent ? 'running' : 'pending';
      case 'execute': return hasToolCall ? 'done' : hasCompletion ? 'skipped' : 'pending';
      default: return 'pending';
    }
  }

  const pipelineSteps = STAGE_KEYS.map((key) => {
    const backend = stageTimings[key];
    const status = backend ? backend.status : fallbackStatus(key);
    return { name: STAGE_LABELS[key] || key, status, latencyMs: backend ? backend.latencyMs : undefined };
  });

  function stepIcon(status: string) {
    switch (status) {
      case 'done': return 'bg-brand-green';
      case 'running': return 'bg-brand-amber';
      case 'skipped': return 'bg-brand-border-strong';
      default: return 'bg-brand-green-muted';
    }
  }

  function stepTextClass(status: string) {
    switch (status) {
      case 'done': return 'text-brand-green-soft';
      case 'running': return 'text-brand-amber';
      case 'skipped': return 'text-brand-green-faint';
      default: return 'text-brand-green-muted';
    }
  }

  // B-2026-08-09-4: latency formatting is shared (progress.ts formatLatency)
  // so every surface — bottom bar, Observe panel, chat chip — renders the
  // same adaptive s/ms units.

  return (
    <div className="space-y-4 p-3">
      {/* Session 123: anomaly alerts — the panel ALERTS instead of silently
          displaying bad numbers. Backend emits these on stall (>60s with
          near-zero output) and token leak (fresh session inheriting the
          previous session's context count). */}
      {anomalies.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <AlertTriangle className="h-3 w-3 text-brand-red" />
            <span className="text-[10px] uppercase tracking-wider text-brand-red font-medium">
              Alerts
            </span>
          </div>
          <div className="space-y-1.5">
            {anomalies.map((a) => (
              <div
                key={a.kind}
                className="bg-brand-red/5 border border-brand-red/30 rounded-md px-2.5 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-medium text-brand-red">
                    {a.title}
                  </span>
                  <span className="text-[9px] uppercase text-brand-red/70 font-mono">
                    {a.severity}
                  </span>
                </div>
                <p className="text-[10px] text-brand-green-soft/90 mt-1 leading-relaxed">
                  {a.detail}
                </p>
                {a.metrics && Object.keys(a.metrics).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {Object.entries(a.metrics).map(([k, v]) => (
                      <span key={k} className="text-[9px] text-brand-green-faint font-mono">
                        {k.replace(/_/g, ' ')}: <span className="text-brand-green-soft">{v}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Intent Classification */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Target className="h-3 w-3 text-brand-amber" />
          <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
            Intent Classification
          </span>
        </div>
        <div className="bg-brand-bg-code border border-brand-border rounded-md px-3 py-2">
          <div className="flex items-center justify-between">
            <span className={`text-[11px] font-medium ${intentConfig.color}`}>
              {hasData ? intentConfig.label : '—'}
            </span>
            <span className="text-[10px] text-brand-green-soft font-mono">
              {confidence > 0 ? `${Math.round(confidence * 100)}%` : '—'}
            </span>
          </div>
          <div className="h-1 bg-brand-border rounded-full overflow-hidden mt-1.5">
            <div
              className="h-full bg-brand-green rounded-full"
              style={{ width: `${confidence * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Performance */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Gauge className="h-3 w-3 text-brand-amber" />
          <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
            Performance
          </span>
        </div>
        <div className="space-y-2">
          <MetricBar label="Confidence" value={hasData ? Math.round(confidence * 100) : 0} max={100} color="bg-brand-green" fallback="—" />
          <MetricBar label="Context Tokens" value={contextTokens} max={32768} color="bg-brand-amber" fallback="—" />
          {/* B-2026-08-09-4: latency has no meaningful fixed scale — the old
              max={10000} bar saturated on any >10s turn. Show the adaptive
              s/ms value instead of a misleading full bar. */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-brand-green-muted">Latency</span>
            <span className="text-[10px] text-brand-green-soft font-mono">
              {latency > 0 ? formatLatency(latency) : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Tools Used */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Wrench className="h-3 w-3 text-brand-amber" />
          <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
            Tools Used
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {toolsUsed.length > 0 ? toolsUsed.map((tool) => (
            <span
              key={tool}
              className="px-1.5 py-0.5 rounded bg-brand-border text-[10px] text-brand-green font-mono"
              title={tool}
            >
              {toolDisplayLabels[tool] || tool.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())}
            </span>
          )) : (
            <span className="text-[10px] text-brand-green-muted">{hasData ? 'None' : '—'}</span>
          )}
        </div>
      </div>

      {/* Memory Hits */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Brain className="h-3 w-3 text-brand-amber" />
          <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
            Memory
          </span>
        </div>
        <div className="bg-brand-bg-code border border-brand-border rounded-md px-3 py-2">
          <div className="flex items-center justify-between">
            {/* B-2026-08-09-8: this counts memory_facts injected into the
                prompt, not vector-DB hits — renamed accordingly. '—' only when
                the session truly has no observation; a real 0 (fresh session)
                renders as 0. */}
            <span className="text-[10px] text-brand-green-muted">Memory Facts</span>
            <span className="text-[11px] text-brand-green-soft font-mono">{hasData ? memoryHits : '—'}</span>
          </div>
        </div>
      </div>

      {/* Pipeline — dynamic status based on observation data */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Activity className="h-3 w-3 text-brand-amber" />
          <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
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
              {step.latencyMs !== undefined && step.latencyMs > 0 && (
                <span className="text-[9px] text-brand-green-faint font-mono">
                  {formatLatency(step.latencyMs)}
                </span>
              )}
              {step.status === 'skipped' && (
                <span className="text-[9px] text-brand-green-faint">skipped</span>
              )}
              {i < pipelineSteps.length - 1 && (
                <span className="text-[9px] text-brand-green-faint ml-auto">
                  →
                </span>
              )}
            </div>
          ))}
          {hasBackendStages && (
            <div className="text-[9px] text-brand-green-faint pt-1 border-t border-brand-border">
              Real stage timings from engine
            </div>
          )}
        </div>
      </div>

      {/* Runtime snapshot — populated only by the structured observation API. */}
      {observation.observation && (
        <RuntimeSnapshot summary={observation.observation} />
      )}
      {capabilities.families.length > 0 && (
        <CapabilityCatalog capabilities={capabilities} />
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
        <Activity className="h-3 w-3 text-brand-amber" aria-hidden="true" />
        <h2 id="runtime-snapshot-heading" className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
          Runtime Snapshot
        </h2>
      </div>

      <div className="bg-brand-bg-code border border-brand-border rounded-md p-2.5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] text-brand-green-muted">Workspace</span>
          <span className={`text-[10px] font-mono ${workspace.gitAvailable ? 'text-brand-green' : 'text-brand-green-muted'}`}>
            {workspace.gitAvailable ? (workspace.gitBranch || 'git available') : 'git unavailable'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2 text-[10px]">
          <div className="min-w-0">
            <div className="text-brand-green-faint">Working tree</div>
            <div className="text-brand-green-soft truncate" title={workspaceState}>
              {workspaceState}
            </div>
          </div>
          <div className="min-w-0">
            <div className="text-brand-green-faint">Open files</div>
            <div className="text-brand-green-soft font-mono">
              {workspace.openFiles.length || '—'}
            </div>
          </div>
        </div>

        {workspace.gitDiffStat && (
          <div className="text-[10px] text-brand-green-muted truncate" title={workspace.gitDiffStat}>
            diff: <span className="text-brand-green-soft font-mono">{workspace.gitDiffStat}</span>
          </div>
        )}

        <div className="flex items-center justify-between gap-2 border-t border-brand-border pt-2">
          <span className="text-[10px] text-brand-green-muted">Last build</span>
          <span className={`text-[10px] font-mono ${build?.result === 'success' ? 'text-brand-green' : 'text-brand-green-soft'}`}>
            {buildLabel}
          </span>
        </div>

        {eventItems.length > 0 && (
          <div className="border-t border-brand-border pt-2">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[10px] text-brand-green-muted">Recent events</span>
              <span className="text-[9px] text-brand-green-faint font-mono">{eventItems.length}</span>
            </div>
            <div className="max-h-40 overflow-y-auto space-y-1 pr-1" aria-label="Recent runtime events">
              {eventItems.map((event, index) => (
                <div key={`${event.type}-${index}`} className="rounded bg-brand-gh-green-bg px-2 py-1.5 min-w-0">
                  <div className="text-[10px] text-brand-green font-mono truncate" title={event.type}>
                    {event.type}
                  </div>
                  <div className="text-[9px] text-brand-green-muted font-mono break-all line-clamp-2">
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

function CapabilityCatalog({ capabilities }: { capabilities: CapabilitiesData }) {
  const families = capabilities.families.filter((family) => family.capabilities.length > 0);

  return (
    <section aria-labelledby="capability-catalog-heading" className="space-y-2">
      <div className="flex items-center gap-1.5">
        <Brain className="h-3 w-3 text-brand-amber" aria-hidden="true" />
        <h2 id="capability-catalog-heading" className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
          Capabilities
        </h2>
      </div>
      <div className="bg-brand-bg-code border border-brand-border rounded-md p-2.5 space-y-2">
        {families.map((family) => (
          <div key={family.id} className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] text-brand-green-soft">{family.label}</span>
              <span className="text-[9px] text-brand-green-faint font-mono">{family.capabilities.length}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {family.capabilities.map((capability) => (
                <span
                  key={capability.id}
                  className="px-1.5 py-0.5 rounded bg-brand-border text-[9px] text-brand-green-muted font-mono"
                  title={capability.description}
                >
                  <span aria-hidden="true">{capability.id.replace(/_/g, ' ')}</span>
                  <span className="sr-only">: {capability.description}</span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
