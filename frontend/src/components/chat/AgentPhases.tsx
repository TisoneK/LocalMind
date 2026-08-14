/**
 * AgentPhases — renders the agent's decision history as a phase strip
 * (Session 181 — F4 Frontend Phase Visibility).
 *
 * Each entry corresponds to one backend obs event (gate pass/fail,
 * orchestrator replan, plan node advance, etc.). The strip renders
 * between the ThinkingBlock and the ToolSteps so the user sees:
 *
 *   "I planned X → I verified Y → I replanned because Z → I switched
 *    to a different approach"
 *
 * — the literal difference between a chat-with-tools and an agent.
 *
 * Empty list = no phases fired this turn (legacy behavior — the
 * component renders nothing).
 */

import { memo } from 'react';
import type { AgentPhase } from '../../types';

interface AgentPhasesProps {
  phases?: AgentPhase[];
  /** True while the message is being streamed — controls spinner state
   *  on the most recent in-progress phase. */
  isStreaming?: boolean;
}

// ── Phase → icon + color ────────────────────────────────────────────────────
//
// Each phase type gets a small icon + tailwind color class. The colors
// are deliberately distinct so the user can scan the strip at a glance:
//   plan_created     → blue (planning)
//   node_advanced    → green (progress)
//   gate_passed      → green ✓ (verified)
//   gate_failed_replan → amber ⚠ (replanning)
//   orchestrator_replan_* → purple (orchestrator)
//   agent_loop_failure → red ✗ (failed)

const PHASE_META: Record<
  AgentPhase['type'],
  { icon: string; color: string; label: string }
> = {
  plan_created: { icon: '📋', color: 'text-brand-blue', label: 'Plan built' },
  node_advanced: { icon: '→', color: 'text-brand-green', label: 'Step advanced' },
  gate_passed: { icon: '✓', color: 'text-brand-green', label: 'Verified' },
  gate_failed_replan: { icon: '⚠', color: 'text-brand-amber', label: 'Replanning' },
  orchestrator_replan_start: { icon: '🔄', color: 'text-brand-purple', label: 'Orchestrator notified' },
  orchestrator_replan_done: { icon: '🔄', color: 'text-brand-purple', label: 'Orchestrator replanned' },
  orchestrator_replan_failed: { icon: '🔄', color: 'text-brand-purple', label: 'Orchestrator replan failed' },
  agent_loop_failure: { icon: '✗', color: 'text-brand-red', label: 'Agent loop failed' },
};

function AgentPhasesBase({ phases, isStreaming }: AgentPhasesProps) {
  if (!phases || phases.length === 0) {
    return null;
  }

  return (
    <div
      className="my-2 rounded-md border border-brand-border/40 bg-brand-bg-panel/40 px-3 py-2"
      data-testid="agent-phases-strip"
    >
      <div className="flex flex-col gap-1.5">
        {phases.map((phase, idx) => {
          const meta = PHASE_META[phase.type] || PHASE_META.plan_created;
          const isLast = idx === phases.length - 1;
          const isInProgress = isStreaming && isLast && (
            phase.type === 'gate_failed_replan' ||
            phase.type === 'orchestrator_replan_start' ||
            phase.type === 'agent_loop_failure'
          );
          return (
            <div
              key={phase.id}
              className="flex items-start gap-2 text-xs"
              data-testid={`agent-phase-${phase.type}`}
            >
              <span className={`${meta.color} ${isInProgress ? 'animate-pulse' : ''} font-mono w-4 text-center`}>
                {meta.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`${meta.color} font-medium`}>
                    {meta.label}
                  </span>
                  {phase.iteration !== undefined && (
                    <span className="text-brand-green-faint text-[10px]">
                      iter {phase.iteration}
                    </span>
                  )}
                </div>
                <div className="text-brand-green-muted text-xs leading-tight mt-0.5 break-words">
                  {phase.label}
                </div>
                {phase.detail && (
                  <div className="text-brand-green-faint text-[11px] leading-tight mt-0.5 break-words">
                    {phase.detail}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export const AgentPhases = memo(AgentPhasesBase);
