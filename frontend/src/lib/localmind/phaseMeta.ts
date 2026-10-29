import type { AgentPhase } from '@/types';

/** Icon, colour and label per agent phase — shared by the run details view. */
export const PHASE_META: Record<
  AgentPhase['type'],
  { icon: string; color: string; label: string }
> = {
  // Lifecycle phases — narrated on the run node in the run details view,
  // including the init call (the longest wait on slow models).
  initializing: { icon: '⚡', color: 'text-brand-amber', label: 'Getting started' },
  understanding: { icon: '💡', color: 'text-brand-blue', label: 'Understanding' },
  acknowledged: { icon: '👋', color: 'text-brand-blue', label: 'Acknowledged' },
  initialized: { icon: '✓', color: 'text-brand-green', label: 'Understood' },
  planned: { icon: '📋', color: 'text-brand-blue', label: 'Plan ready' },
  thinking: { icon: '🧠', color: 'text-brand-purple', label: 'Approach' },
  thinking_done: { icon: '✓', color: 'text-brand-green', label: 'Approach ready' },
  working: { icon: '🔧', color: 'text-brand-amber', label: 'Working' },
  turn_done: { icon: '🏁', color: 'text-brand-green', label: 'Turn complete' },
  plan_created: { icon: '📋', color: 'text-brand-blue', label: 'Plan built' },
  node_advanced: { icon: '→', color: 'text-brand-green', label: 'Step advanced' },
  gate_passed: { icon: '✓', color: 'text-brand-green', label: 'Verified' },
  gate_failed_replan: { icon: '⚠', color: 'text-brand-amber', label: 'Replanning' },
  orchestrator_replan_start: { icon: '🔄', color: 'text-brand-purple', label: 'Orchestrator notified' },
  orchestrator_replan_done: { icon: '🔄', color: 'text-brand-purple', label: 'Orchestrator replanned' },
  orchestrator_replan_failed: { icon: '🔄', color: 'text-brand-purple', label: 'Orchestrator replan failed' },
  agent_loop_failure: { icon: '✗', color: 'text-brand-red', label: 'Agent loop failed' },
  agent_loop_degraded: { icon: '⚠', color: 'text-brand-amber', label: 'Provider interrupted' },
};
