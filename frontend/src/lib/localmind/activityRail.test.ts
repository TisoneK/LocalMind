import { describe, expect, it } from 'vitest';
import { buildRail, filePathOf } from './activityRail';
import type { AgentRun, ToolCall } from '@/types';

const tool = (id: string, over: Partial<ToolCall> = {}): ToolCall => ({ id, name: 'shell', status: 'done', input: `cmd ${id}`, ...over });
const run = (id: string, tools: ToolCall[], over: Partial<AgentRun> = {}): AgentRun => ({
  id, name: id, role: 'parent', status: 'running', depth: 0, startedAt: 0, tools, ...over,
});

describe('buildRail', () => {
  it('is empty with no runs or files', () => {
    expect(buildRail({ runs: [] }).empty).toBe(true);
  });

  it('lists what is running now across parent and child agents', () => {
    const r = buildRail({
      runs: [
        run('p', [tool('a', { status: 'running' }), tool('b')]),
        run('c', [tool('x', { status: 'running', name: 'file_read' })], { role: 'child', title: 'Explorer' }),
      ],
    });
    expect(r.now.map((n) => `${n.agent}:${n.label}`)).toEqual(['p:Running command', 'Explorer:Reading file']);
    expect(r.agents.map((a) => [a.name, a.toolsDone, a.toolsTotal])).toEqual([['p', 1, 2], ['Explorer', 0, 1]]);
  });

  it('shows nothing running once the turn has settled', () => {
    const r = buildRail({ runs: [run('p', [tool('a', { status: 'running' })])], isStreaming: false });
    expect(r.now).toEqual([]);
    expect(r.agents[0].state).toBe('pending');
  });

  it('collects touched files once, with diff counts', () => {
    const r = buildRail({
      runs: [run('p', [
        tool('a', { name: 'file_write', input: '/w/a.txt:\nhello' }),
        tool('b', { name: 'edit_file', input: '/w/a.txt' }),
        tool('c', { name: 'shell', input: '/w/skip.txt' }),
      ])],
      fileDiffs: { '/w/a.txt': { hunks: [{ filePath: '/w/a.txt', oldStart: 0, oldLines: 0, newStart: 1, newLines: 2, lines: [
        { type: 'added', content: 'x' }, { type: 'added', content: 'y' }, { type: 'removed', content: 'z' },
      ] }] } as never },
    });
    expect(r.files).toEqual([{ path: '/w/a.txt', name: 'a.txt', state: 'done', additions: 2, deletions: 1 }]);
  });

  it('reads the file path from the first input line', () => {
    expect(filePathOf(tool('a', { input: '/w/a.txt:\nbody' }))).toBe('/w/a.txt');
    expect(filePathOf(tool('a', { input: 'no path here' }))).toBeNull();
  });

  it('resolves a length-truncated tool path through the captured diff', () => {
    const full = '/w/very/long/session-1/rail-c.txt';
    const r = buildRail({
      runs: [run('p', [tool('a', { name: 'file_write', input: '/w/very/long/sess:\ngamma' })])],
      fileDiffs: { [full]: { hunks: [] } as never },
    });
    expect(r.files.map((f) => f.path)).toEqual([full]);
    expect(r.files[0].name).toBe('rail-c.txt');
  });

  it('drops a truncated path that matches nothing', () => {
    const r = buildRail({ runs: [run('p', [tool('a', { name: 'file_write', input: '/w/very/long/sess' })])] });
    expect(r.files).toEqual([]);
  });

  it('keeps a tool that never reported back unfinished, even in a completed run', () => {
    const r = buildRail({
      runs: [run('p', [tool('a', { status: 'started', name: 'file_write', input: '/w/a.txt:\nx' })], { status: 'completed' })],
      isStreaming: false,
    });
    expect(r.agents[0]).toMatchObject({ toolsDone: 0, toolsTotal: 1 });
    expect(r.files[0].state).toBe('pending');
    expect(r.now).toEqual([]);
  });

  it('lists only the current turn\'s agents, not one "parent" per past turn', () => {
    const r = buildRail({
      runs: [
        run('p1', [tool('a')], { status: 'completed' }),
        run('p2', [tool('b')], { status: 'completed' }),
        run('p3', [tool('c', { status: 'running' })]),
        run('c3', [], { role: 'child', title: 'Explorer' }),
      ],
      isStreaming: true,
    });
    expect(r.agents.map((a) => a.id)).toEqual(['p3', 'c3']);
  });

  it('still reports files and running tools from earlier turns of the chat', () => {
    const r = buildRail({
      runs: [
        run('p1', [tool('a', { name: 'file_write', input: '/w/a.txt:\nx' })], { status: 'completed' }),
        run('p2', [tool('b')]),
      ],
      isStreaming: false,
    });
    expect(r.files.map((f) => f.name)).toEqual(['a.txt']);
  });
});
