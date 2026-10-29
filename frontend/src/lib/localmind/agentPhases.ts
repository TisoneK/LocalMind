/**
 * Pure helpers for the agent turn: prompt-leak filtering, tool labels/previews, and the
 * agent-phase timeline built from backend observation events. No React, no state.
 */

import { friendlyUnmet } from '@/lib/localmind/errorText';
import type { AgentPhase } from '@/types';

// ─── Prompt leak detection (FIX 1) ────────────────────────────────────
// Patterns that indicate a leaked system prompt or planning fragment.
// These appear when the agent loop accidentally streams planning text
// or system instructions to the user instead of keeping them internal.
// Map tool names to intent categories for the observation panel
export function _toolToIntent(toolName: string, fallback: string = 'chat'): string {
  const map: Record<string, string> = {
    web_search: 'search',
    shell: 'shell',
    code_exec: 'code',
    file_write: 'file',
    file_task: 'file',
    file_read: 'file',
    memory_op: 'memory',
    sysinfo: 'chat',
    edit_file: 'file',
    grep: 'search',
  };
  return map[toolName] || fallback;
}

// Canonical narrative order for the active-agent lifecycle phases (mirrors
// the backend's _LIFECYCLE_PHASE_RANK in agent_workspace.py). The loop emits
// some events out of story order (agent_loop_start fires before init), so
// the run node always reads "getting started → understood → working → done".
export const LIFECYCLE_PHASE_RANK: Record<string, number> = {
  initializing: 0,
  understanding: 1,
  acknowledged: 2,
  initialized: 3,
  planned: 4,
  thinking: 5,
  thinking_done: 6,
  working: 7,
  turn_done: 8,
};

// ─── Frontend Phase Visibility ──────────────────────
//
// buildAgentPhase converts a backend obs event into an AgentPhase entry.
// Two consumers: the chat phase strip (plan/gate/orchestrator decision
// history, via PHASE_EVENT_TYPES) and the Agents-tab run node (lifecycle
// narration, via RUN_LIFECYCLE_TYPES — the active-agent phases). Each
// event type carries different payload fields; this helper extracts the
// most informative label + detail for each. Returns null when the event
// payload is missing required fields (defensive — surfaces only render
// entries that have something useful to say).
//
// Exported for direct unit testing .
/**
 * Collapse consecutive identical phases into one entry with a
 * run count. Lifecycle phases fire per-iteration, so a multi-iteration turn
 * repeated "Working out the approach" / "Approach ready" 5× each. Adjacent
 * phases with the same `type` AND `label` are merged (keeping the first, whose
 * id stays the stable React key); `count` records how many were folded, and the
 * merged entry carries the LAST occurrence's iteration/detail so the timeline
 * still reflects the latest state. Non-adjacent repeats (a phase that recurs
 * after a different phase) are preserved — only runs of the same phase collapse.
 */
export function collapseAdjacentPhases(phases: AgentPhase[]): AgentPhase[] {
  const out: AgentPhase[] = [];
  for (const phase of phases) {
    const prev = out[out.length - 1];
    if (prev && prev.type === phase.type && prev.label === phase.label) {
      out[out.length - 1] = {
        ...prev,
        count: (prev.count ?? 1) + 1,
        iteration: phase.iteration ?? prev.iteration,
        detail: phase.detail ?? prev.detail,
      };
    } else {
      out.push(phase);
    }
  }
  return out;
}

export function buildAgentPhase(
  eventType: string | undefined,
  data: Record<string, unknown> | null | undefined,
): AgentPhase | null {
  const ts = Date.now();
  switch (eventType) {
    // Lifecycle phases (bootup-telemetry session) — narrate the whole turn
    // so the strip is never empty during the longest wait (the parent init
    // call on a slow model). Mirrors the backend build_agent_phases entries.
    case 'agent_initialization_start': {
      return {
        id: `phase-init-start-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'initializing',
        label: 'Getting started — understanding your request',
        timestamp: ts,
      };
    }
    case 'agent_initialization_understanding': {
      const text = String(data?.understanding ?? '').trim();
      if (!text) return null;
      return {
        id: `phase-understanding-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'understanding',
        label: 'Understanding your request',
        detail: text.slice(0, 160),
        timestamp: ts,
      };
    }
    case 'agent_initialization_ack': {
      const text = String(data?.acknowledgement ?? '').trim();
      if (!text) return null;
      return {
        id: `phase-ack-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'acknowledged',
        label: 'Acknowledged',
        detail: text.slice(0, 160),
        timestamp: ts,
      };
    }
    case 'agent_initialization_done': {
      const mode = String(data?.mode ?? '');
      const objective = String(data?.objective ?? '').slice(0, 160);
      return {
        id: `phase-init-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'initialized',
        label: mode ? `Understood — ${mode} mode` : 'Understood the request',
        detail: objective || undefined,
        timestamp: ts,
      };
    }
    case 'agent_thinker_start': {
      return {
        id: `phase-thinking-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'thinking',
        label: 'Working out the approach',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_thinker_done': {
      return {
        id: `phase-think-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'thinking_done',
        label: 'Approach ready',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_planning_done': {
      return {
        id: `phase-planned-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'planned',
        label: 'Plan ready — proceeding step by step',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_loop_start': {
      return {
        id: `phase-working-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'working',
        label: 'Working — executing the plan',
        timestamp: ts,
      };
    }
    case 'agent_loop_done': {
      const detailParts: string[] = [];
      if (data?.direct) detailParts.push('answered directly');
      if (data?.clarification) detailParts.push('asked for clarification');
      if (data?.hit_limit) detailParts.push('iteration limit reached');
      const iterations = Number(data?.iterations ?? 0);
      if (iterations > 0) detailParts.push(`${iterations} iterations`);
      return {
        id: `phase-turn-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'turn_done',
        label: 'Turn complete',
        detail: detailParts.length ? detailParts.join('; ') : undefined,
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'plan_nodes_created': {
      const count = Number(data?.node_count ?? 0);
      if (!count) return null;
      const ids: string[] = Array.isArray(data?.node_ids) ? data.node_ids : [];
      return {
        id: `phase-plan-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'plan_created',
        label: `Plan built — ${count} step${count === 1 ? '' : 's'}`,
        detail: ids.length ? ids.join(' → ') : undefined,
        timestamp: ts,
      };
    }
    case 'plan_node_advanced': {
      const nodeId = String(data?.node_id ?? '');
      const newStatus = String(data?.new_status ?? '');
      const subgoal = String(data?.subgoal ?? '').slice(0, 100);
      if (!nodeId) return null;
      const statusIcon = newStatus === 'completed' ? '✓' : newStatus === 'failed' ? '✗' : '~';
      return {
        id: `phase-adv-${nodeId}-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'node_advanced',
        label: `${nodeId} ${statusIcon} ${subgoal}`,
        detail: newStatus ? `status: ${newStatus}` : undefined,
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_loop_gate_passed': {
      const intent = String(data?.intent ?? '');
      return {
        id: `phase-gate-pass-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'gate_passed',
        label: intent ? `Verified — ${intent} acceptance gate passed` : 'Verified — acceptance gate passed',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_loop_gate_failed_replan': {
      const intent = String(data?.intent ?? '');
      const unmet: string[] = Array.isArray(data?.unmet) ? data.unmet : [];
      return {
        id: `phase-gate-fail-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'gate_failed_replan',
        label: intent
          ? `Replanning — ${intent} criteria unmet`
          : 'Replanning — acceptance criteria unmet',
        detail: unmet.length ? `Unmet: ${unmet.slice(0, 3).map(friendlyUnmet).join('; ')}` : undefined,
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'orchestrator_replan_start': {
      const intent = String(data?.intent ?? '');
      return {
        id: `phase-orch-start-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'orchestrator_replan_start',
        label: intent
          ? `Orchestrator notified — ${intent} failure`
          : 'Orchestrator notified of failure',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'orchestrator_replan_done': {
      const confidence = Number(data?.confidence ?? 0);
      const intent = String(data?.intent ?? '');
      return {
        id: `phase-orch-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'orchestrator_replan_done',
        label: intent
          ? `Orchestrator replanned — ${intent}, confidence ${confidence.toFixed(2)}`
          : `Orchestrator replanned — confidence ${confidence.toFixed(2)}`,
        timestamp: ts,
      };
    }
    case 'orchestrator_replan_failed': {
      const error = String(data?.error ?? '');
      return {
        id: `phase-orch-fail-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'orchestrator_replan_failed',
        label: 'Orchestrator replan failed (non-fatal — using fallback)',
        detail: error ? `Error: ${error.slice(0, 120)}` : undefined,
        timestamp: ts,
      };
    }
    case 'agent_loop_failure': {
      const reason = String(data?.reason ?? data?.failure_type ?? '');
      return {
        id: `phase-fail-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'agent_loop_failure',
        label: 'Agent loop terminated',
        detail: reason ? `Reason: ${reason.slice(0, 120)}` : undefined,
        timestamp: ts,
      };
    }
    case 'agent_loop_degraded': {
      // A provider death the loop survived: it kept its evidence and
      // delivered what the evidence supported (or said so honestly). The
      // strip names it — the run's outcome truth is part of the record.
      const code = String(data?.provider_error_code ?? '');
      const provider = String(data?.provider ?? '');
      const terminal = Boolean(data?.terminal);
      const preserved = Boolean(data?.evidence_preserved);
      const label = terminal
        ? 'Provider died — evidence delivered as gathered'
        : preserved
          ? 'Provider interrupted — partial evidence delivered'
          : 'Provider interrupted the run';
      const detailParts: string[] = [];
      if (provider) detailParts.push(`provider: ${provider}`);
      if (code) detailParts.push(`code: ${code}`);
      return {
        id: `phase-degraded-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'agent_loop_degraded',
        label,
        detail: detailParts.length ? detailParts.join('; ') : undefined,
        timestamp: ts,
      };
    }
    default:
      return null;
  }
}

const _PROMPT_LEAK_PATTERNS = [
  /^EXECUTION PLAN/,              // Planning output header
  /^UNDERSTANDING:/,              // Planning understanding section
  /^STEPS:/,                      // Planning steps section
  /^ARGS_PRECHECK:/,              // Planning args precheck
  /^CRITICAL SAFETY RULES:/,      // System prompt header
  /^TOOL ARGUMENT RULES/,         // System prompt rules
  /^VERIFICATION —/,             // System prompt verification
  /^Current intent:/,            // System prompt context
  /^Max iterations:/,            // System prompt context
  /^You are LocalMind/,          // System prompt identity
  /^Available tools:/,           // System prompt tool list
  /^FILE_WRITE WORKFLOW/,         // Intent template
  /^FILE_EDIT WORKFLOW/,          // Intent template
  /^CODE_EXEC WORKFLOW/,          // Intent template
  /^MEMORY_OP WORKFLOW/,          // Intent template
  /^SHELL TOOL GUIDANCE/,         // Shell guidance
  /^\[TOOL_CALL\]\s*<invoke/,     // Raw tool call: minimax format (first token)
  /^\[TOOL_CALL\]/,              // Raw tool call: bracket tag (streaming leak after first token)
  /^\[tool\s*=>/,                // Raw tool call: old bracket format
  /^<invoke\s+name=/,            // Raw tool call: XML open tag streaming
  /^\s*<\/invoke>\s*<\/minimax:tool_call>/, // Raw tool call: XML close tag streaming
  /^<invoke\s+name=["']tool/,   // Streaming tool call with tool name hint
  /^\[invoke/,                    // Streaming: generic invoke bracket
  /^\[\/invoke/,                   // Streaming: generic /invoke bracket
  /^\(Not entirely sure/,          // v0.5: Uncertainty prefix that models emit
  /^Not entirely sure/,            // v0.5: Uncertainty prefix without parens
  /^PART\s+1/,                     // v0.5: Chat Agent structured output markers
  /^PART\s+2/,                     // v0.5: Chat Agent structured output markers
  /^ACKNOWLEDGE/,                  // v0.5: Chat Agent label
  /^REFORMULATED INSTRUCTION/,     // v0.5: Chat Agent label
];


export function _isPromptLeak(token: string): boolean {
  if (!token || token.length < 3) return false;
  const trimmed = token.trim();
  // Check line-start patterns
  if (_PROMPT_LEAK_PATTERNS.some(p => p.test(trimmed))) return true;
  // v0.5: Also filter "(Not entirely sure...)" that appears mid-line
  // (e.g. at the start of a longer token that doesn't start with it)
  if (/\(Not entirely sure[^)]*\)\s*/i.test(trimmed)) return true;
  if (/Not entirely sure[^.]*\.\s*/i.test(trimmed)) return true;
  return false;
}

// ─── Tool label builder (FIX 2) ───────────────────────────────────────
// Builds human-readable labels from tool name + args for Task Progress
// and the turn view. Falls back to a cleaned-up tool name.

const TOOL_LABELS: Record<string, string> = {
  file_write: 'Creating file',
  file_read: 'Reading file',
  file_task: 'Reading file',
  edit_file: 'Editing file',
  code_exec: 'Running code',
  shell: 'Executing command',
  memory_op: 'Memory operation',
  web_search: 'Searching the web',
  sysinfo: 'Getting system info',
};

/** Tool args arrive as JSON from the wire — an object with string-ish
 *  fields, or occasionally a bare string. */
type ToolArgsWire = Record<string, unknown> | string | null | undefined;

export function _buildToolLabel(toolName: string, args: ToolArgsWire): string {
  // Try to extract a descriptive label from structured args
  if (args && typeof args === 'object') {
    const path = String(args.path ?? '');
    const command = String(args.command ?? '');
    const query = String(args.query ?? '');
    const code = String(args.code ?? '').slice(0, 30);
    const operation = String(args.operation ?? '');
    switch (toolName) {
      case 'file_write': return path ? `Creating ${path.split(/[\\/]/).pop()}` : 'Creating file';
      case 'file_task': return path ? `Reading ${path.split(/[\\/]/).pop()}` : 'Reading file';
      case 'edit_file': return path ? `Editing ${path.split(/[\\/]/).pop()}` : 'Editing file';
      case 'shell': return command ? `Running: ${command.slice(0, 60)}` : 'Executing command';
      case 'code_exec': return code ? `Executing: ${code}...` : 'Running code';
      case 'web_search': return query ? `Searching: ${query.slice(0, 60)}` : 'Searching the web';
      case 'memory_op': return operation ? `${operation.charAt(0).toUpperCase() + operation.slice(1)} fact` : 'Memory operation';
      case 'sysinfo': return query ? `System: ${query.slice(0, 30)}` : 'Getting system info';
    }
  }
  // If args is a string, try to extract useful info
  if (typeof args === 'string' && args.length > 0) {
    const preview = args.slice(0, 50);
    return `${TOOL_LABELS[toolName] || toolName}: ${preview}`;
  }
  return TOOL_LABELS[toolName] || toolName.replace(/_/g, ' ');
}

export function _buildToolInputPreview(toolName: string, args: ToolArgsWire): string {
  if (args && typeof args === 'object') {
    switch (toolName) {
      case 'file_write': return String(args.path ?? '');
      case 'file_task': return String(args.path ?? '');
      case 'edit_file': return String(args.path ?? '');
      case 'shell': return String(args.command ?? '');
      case 'code_exec': return String(args.code ?? '').slice(0, 80);
      case 'web_search': return String(args.query ?? '');
      case 'memory_op': return `${String(args.operation ?? '')} ${String(args.content ?? '')}`.trim();
      case 'sysinfo': return String(args.query ?? '');
    }
  }
  if (typeof args === 'string') return args.slice(0, 80);
  return '';
}

