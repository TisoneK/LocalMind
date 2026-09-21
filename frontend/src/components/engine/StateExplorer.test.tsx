/**
 * The State Explorer as the user meets it: it opens on a real captured run, works with no backend
 * (live runs are offered, not assumed), streams a live run into the tree, and its timeline and
 * inspector answer to the mouse and the keyboard.
 */

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StateExplorer } from './StateExplorer';
import { localmindClient } from '@/lib/localmind/client';
import type { EngineEvent, RunMeta } from '@/lib/localmind/stateEngine';

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: {
    getStateEngineInfo: vi.fn(),
    runStateEngine: vi.fn(),
  },
}));

const mockClient = localmindClient as unknown as Record<string, ReturnType<typeof vi.fn>>;

const INFO = {
  experimental: true,
  read_only: true,
  provider: 'deepseek',
  model: 'deepseek-chat',
  tools: [
    { name: 'file_read', description: 'read a file' },
    { name: 'dir_explorer', description: 'list a folder' },
  ],
};

const META: RunMeta = {
  provider: 'deepseek',
  model: 'deepseek-chat',
  budget: { max_depth: 6, max_branches: 3, max_model_calls: 16, max_backtracks: 2 },
};

/** A short but complete live run: one move chosen, then the goal settled. */
const LIVE_EVENTS: EngineEvent[] = [
  { seq: 1, t_ms: 0, kind: 'state', node: 'n0', parent: null, facts: 0, progress: 0, goal: 'how many notes files' },
  {
    seq: 2,
    t_ms: 900,
    kind: 'candidates',
    at: 'n0',
    moves: [{ fp: 'aa', label: 'dir_explorer(~)', tool: 'dir_explorer', why: 'see the folders' }],
  },
  { seq: 3, t_ms: 1200, kind: 'probe', at: 'n0', fp: 'aa', ok: true, ms: 40, chars: 120, excerpt: 'notes/ notes.md' },
  { seq: 4, t_ms: 1500, kind: 'evaluation', at: 'n0', fp: 'aa', progress: 0.7, reason: 'names the files' },
  { seq: 5, t_ms: 1600, kind: 'selected', at: 'n0', fp: 'aa', move: 'dir_explorer(~)', progress: 0.7 },
  { seq: 6, t_ms: 1900, kind: 'state', node: 'n1', parent: 'n0', facts: 2, progress: 0.7 },
  { seq: 7, t_ms: 2100, kind: 'done', at: 'n1', answer: 'Three: notes.md and two more.', trail: ['dir_explorer(~)'], model_calls: 2, settled: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  mockClient.getStateEngineInfo.mockResolvedValue(INFO);
});

describe('StateExplorer', () => {
  it('opens on the built-in captured run instead of an empty page', async () => {
    render(<StateExplorer />);
    expect(await screen.findByTestId('state-explorer')).toBeInTheDocument();
    expect(screen.getByTestId('run-pill')).toHaveTextContent('SETTLED'); // the sample run settled
    expect(screen.getByTestId('meters')).toHaveTextContent('MODEL CALLS4');
    expect(screen.getByText(/Find the README of the LocalMind project/)).toBeInTheDocument();
    expect(screen.getAllByTestId('state-node').length).toBeGreaterThan(1);
  });

  it('says where a live run will go, and what the engine may use', async () => {
    render(<StateExplorer />);
    expect(await screen.findByTestId('engine-note')).toHaveTextContent('deepseek · deepseek-chat · 2 read-only tools');
  });

  it('offers live runs but says so plainly when there is no backend', async () => {
    mockClient.getStateEngineInfo.mockRejectedValue(new Error('connection refused'));
    render(<StateExplorer />);
    expect(await screen.findByTestId('engine-note')).toHaveTextContent('Live runs need the LocalMind backend.');
    expect(screen.getByRole('button', { name: '▶ run live' })).toBeDisabled();
    expect(screen.getByLabelText('Goal')).toBeDisabled();
  });

  it('streams a live run into the tree and settles it', async () => {
    let handlers: { onMeta: (m: RunMeta) => void; onEvent: (e: EngineEvent) => void } | null = null;
    let finish: (() => void) | null = null;
    mockClient.runStateEngine.mockImplementation(
      (_goal: string, h: typeof handlers) =>
        new Promise<void>((resolve) => {
          handlers = h;
          finish = resolve;
        })
    );
    render(<StateExplorer />);
    await screen.findByTestId('engine-note');

    await userEvent.type(screen.getByLabelText('Goal'), 'how many notes files');
    await userEvent.click(screen.getByRole('button', { name: '▶ run live' }));
    await waitFor(() => expect(mockClient.runStateEngine).toHaveBeenCalledWith('how many notes files', expect.anything(), expect.anything()));

    act(() => {
      handlers!.onMeta(META);
      handlers!.onEvent(LIVE_EVENTS[0]);
      handlers!.onEvent(LIVE_EVENTS[1]);
    });
    expect(await screen.findByTestId('run-pill')).toHaveTextContent('LIVE');

    act(() => {
      for (const e of LIVE_EVENTS.slice(2)) handlers!.onEvent(e);
      finish!();
    });
    await waitFor(() => expect(screen.getByTestId('run-pill')).toHaveTextContent('SETTLED'));
    expect(screen.getByTestId('end-banner')).toHaveTextContent('GOAL SETTLED · 2 model calls');
  });

  it('rewinds the timeline and shows the real observation behind a move', async () => {
    render(<StateExplorer />);
    const pane = await screen.findByTestId('state-explorer');
    expect(screen.getByTestId('run-pill')).toHaveTextContent('SETTLED');

    fireEvent.keyDown(pane, { key: 'ArrowLeft' });
    expect(screen.getByTestId('run-pill')).toHaveTextContent('RUNNING'); // rewound before the end
    fireEvent.keyDown(pane, { key: 'End' });
    expect(screen.getByTestId('run-pill')).toHaveTextContent('SETTLED');

    await userEvent.click(screen.getAllByTestId(/card-/)[0]);
    const inspector = screen.getByRole('complementary', { name: 'Inspector' });
    expect(within(inspector).getByText('OBSERVATION (real tool result)')).toBeInTheDocument();
    expect(within(inspector).getByText(/^ok · \d+ms · \d+ chars$/)).toBeInTheDocument(); // the real probe
    expect(within(inspector).getByText('why')).toBeInTheDocument();
  });
});
