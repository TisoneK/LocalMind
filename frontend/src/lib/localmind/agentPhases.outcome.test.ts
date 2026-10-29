import { describe, expect, it } from 'vitest';
import { buildAgentPhase } from './agentPhases';

describe('agent_loop_degraded phase mapping (§U item 3)', () => {
  it('names a terminal death with its provider and code', () => {
    const p = buildAgentPhase('agent_loop_degraded', {
      provider_error_code: 'payment_required',
      provider: 'stub-provider',
      evidence_preserved: true,
      terminal: true,
    });
    expect(p).not.toBeNull();
    expect(p!.type).toBe('agent_loop_degraded');
    expect(p!.label).toBe('Provider died — evidence delivered as gathered');
    expect(p!.detail).toContain('stub-provider');
    expect(p!.detail).toContain('payment_required');
  });

  it('distinguishes a retryable cutoff from a terminal death', () => {
    const p = buildAgentPhase('agent_loop_degraded', {
      provider_error_code: 'rate_limit',
      evidence_preserved: true,
      terminal: false,
    });
    expect(p!.label).toBe('Provider interrupted — partial evidence delivered');
  });

  it('renders even with an empty payload (never hidden)', () => {
    const p = buildAgentPhase('agent_loop_degraded', {});
    expect(p!.label).toBe('Provider interrupted the run');
    expect(p!.detail).toBeUndefined();
  });
});
