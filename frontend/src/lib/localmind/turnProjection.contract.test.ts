import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { projectTrajectory, type ProjectionEvent } from './turnProjection';

/**
 * Cross-language contract: the frontend's live projection (turnProjection.ts)
 * must produce the SAME trajectory as the backend's persist-time projection
 * (agent_workspace.build_run_tree / build_agent_phases / collect_injected_items)
 * for the same recorded obs stream. Both sides pin to one generated expected
 * artifact (tests/fixtures/trajectory_projection.expected.json, written by
 * scripts/gen_trajectory_expected.py from the real backend). The backend side
 * is tests/core/test_trajectory_projection_contract.py.
 *
 * This is what keeps the two ports from silently drifting: change one side's
 * projection and this test (or its backend twin) goes red until they agree.
 */

// vitest runs with cwd = frontend/; the shared fixtures live at the repo root.
const FIXTURES = resolve(process.cwd(), '..', 'tests', 'fixtures');
const fixture = JSON.parse(readFileSync(resolve(FIXTURES, 'trajectory_projection.json'), 'utf8'));
const expected = JSON.parse(readFileSync(resolve(FIXTURES, 'trajectory_projection.expected.json'), 'utf8'));

const VOLATILE = new Set(['timestamp', 'startedAt', 'completedAt']);

/** Same normalization the generator applies: drop volatile wall-clock keys and
 *  absent-ish scalars (null/undefined/''), keep lists. */
function norm(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(norm);
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (VOLATILE.has(k)) continue;
      const nv = norm(v);
      if (nv === null || nv === undefined || nv === '') continue;
      out[k] = nv;
    }
    return out;
  }
  return value;
}

describe('trajectory projection contract (frontend ↔ backend)', () => {
  for (const testCase of fixture.cases as Array<{ name: string; task?: string; rootError?: string | null; events: ProjectionEvent[] }>) {
    it(`matches the backend projection for "${testCase.name}"`, () => {
      const proj = projectTrajectory(testCase.events, {
        task: testCase.task,
        rootError: testCase.rootError ?? null,
        now: 0,
      });
      const got = norm({
        agentRuns: proj.agentRuns,
        agentPhases: proj.agentPhases,
        injectedItems: proj.injectedItems ?? null,
      });
      expect(got).toEqual(norm(expected[testCase.name]));
    });
  }
});
