import { afterEach, describe, expect, it, vi } from 'vitest';
import { localmindClient } from './client';

describe('getObservability', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('preserves the legacy shape when no structured snapshot is available', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-1',
        intent: null,
        confidence: null,
        tools_used: '',
        memory_hits: 0,
        context_tokens: 0,
        latency_ms: 0,
        tool_timeline: [],
        observation: null,
      }),
    }));

    await expect(localmindClient.getObservability('session-1')).resolves.toMatchObject({
      intent: 'chat',
      confidence: 0,
      toolsUsed: [],
      observation: null,
    });
  });

  it('normalizes malformed snapshot fields without crashing the UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-2',
        intent: 'file',
        confidence: 0.9,
        tools_used: 'file_read',
        memory_hits: 1,
        context_tokens: 42,
        latency_ms: 125,
        tool_timeline: [],
        observation: {
          timestamp: 'not-a-number',
          workspace: {
            git_available: true,
            git_branch: { unexpected: true },
            git_status: null,
            git_diff_stat: 123,
            open_files: ['README.md', null, { path: 'secret' }],
            last_build_result: {
              result: { unexpected: true },
              command: null,
              output_tail: 456,
              exit_code: 'zero',
            },
          },
          recent_events: [
            null,
            { type: 42, data: null },
            { type: 'tool_complete', data: { tool: 'file_read' } },
          ],
        },
      }),
    }));

    await expect(localmindClient.getObservability('session-2')).resolves.toMatchObject({
      intent: 'file',
      toolsUsed: ['file_read'],
      observation: {
        timestamp: 0,
        workspace: {
          gitAvailable: true,
          gitBranch: '',
          gitStatus: '',
          gitDiffStat: '',
          openFiles: ['README.md'],
          lastBuildResult: {
            result: '',
            command: '',
            outputTail: '',
            exitCode: undefined,
          },
        },
        recentEvents: [
          { type: 'event', data: {} },
          { type: 'tool_complete', data: { tool: 'file_read' } },
        ],
      },
    });
  });
});
