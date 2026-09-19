import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createElement } from 'react';
import { render, screen, act } from '@testing-library/react';
import { WorkspaceLayout } from './WorkspaceLayout';

// All 13 useLocalMind hooks are mocked so the layout can be rendered
// hermetically (no real API calls, timers, or SSE connections). The panels
// are also mocked to plain stubs that record the props they receive — this
// turns the test into a wiring-contract check: WorkspaceLayout is the thing
// under test, and we assert exactly which data and callbacks flow into each
// panel.
const mockHooks = vi.hoisted(() => ({
  useSessions: vi.fn(),
  useChat: vi.fn(),
  useActions: vi.fn(),
  useFileTree: vi.fn(),
  useTodos: vi.fn(),
  useObjectives: vi.fn(),
  useTerminal: vi.fn(),
  useObservability: vi.fn(),
  useCapabilities: vi.fn(),
  useMetrics: vi.fn(),
  useModels: vi.fn(),
  useMemory: vi.fn(),
  useHealth: vi.fn(),
}));

const mockPanelProps = vi.hoisted(() => ({
  left: {} as Record<string, unknown>,
  center: {} as Record<string, unknown>,
  right: {} as Record<string, unknown>,
}));

const mockClient = vi.hoisted(() => ({
  restorePersistedAdapter: vi.fn(),
  getPersistedSettings: vi.fn(() => ({})),
  // WorkspaceLayout loads the persisted chat mode via
  // localmindClient.getSettings() on mount. The mock omitted it, so every
  // test threw "getSettings is not a function" in the effect.
  getSettings: vi.fn().mockResolvedValue({}),
}));

vi.mock('@/hooks/useLocalMind', () => mockHooks);

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: {
    restorePersistedAdapter: mockClient.restorePersistedAdapter,
    getSettings: mockClient.getSettings,
  },
  getPersistedSettings: mockClient.getPersistedSettings,
}));

interface SetupOverrides {
  activeToolCalls?: Array<Record<string, unknown>>;
  models?: Array<Record<string, unknown>>;
  currentModel?: string | null;
  provider?: string;
  persistedSettings?: Record<string, unknown>;
  liveObservation?: Record<string, unknown> | null;
  observation?: Record<string, unknown>;
  agentRuns?: Array<Record<string, unknown>>;
  isStreaming?: boolean;
  lastMetrics?: Record<string, unknown> | null;
  sessionStats?: Record<string, number>;
}

vi.mock('./LeftPanel', () => ({
  LeftPanel: (props: Record<string, unknown>) => {
    mockPanelProps.left = props;
    return createElement('div', { 'data-testid': 'left-panel' });
  },
}));

vi.mock('./CenterPanel', () => ({
  CenterPanel: (props: Record<string, unknown>) => {
    mockPanelProps.center = props;
    return createElement('div', { 'data-testid': 'center-panel' });
  },
}));

vi.mock('./RightPanel', () => ({
  RightPanel: (props: Record<string, unknown>) => {
    mockPanelProps.right = props;
    return createElement('div', { 'data-testid': 'right-panel' });
  },
}));

function setup(overrides: SetupOverrides = {}) {
  mockClient.getPersistedSettings.mockReturnValue(overrides.persistedSettings ?? {});
  const fns = {
    refreshSessions: vi.fn(),
    deleteSession: vi.fn(),
    send: vi.fn(),
    abort: vi.fn(),
    steer: vi.fn(),
    setMessages: vi.fn(),
    resetSession: vi.fn(),
    refreshActions: vi.fn(),
    addTodo: vi.fn(),
    toggleTodo: vi.fn(),
    removeTodo: vi.fn(),
    createObjective: vi.fn(),
    pauseObjective: vi.fn(),
    resumeObjective: vi.fn(),
    cancelObjective: vi.fn(),
    selectModel: vi.fn(),
    refreshModels: vi.fn(),
    deleteFact: vi.fn(),
    execute: vi.fn(),
    clear: vi.fn(),
    changeSession: vi.fn(),
    tabComplete: vi.fn(),
    addToolOutput: vi.fn(),
  };

  mockHooks.useSessions.mockReturnValue({
    sessions: [],
    loading: false,
    refresh: fns.refreshSessions,
    deleteSession: fns.deleteSession,
  });
  mockHooks.useChat.mockReturnValue({
    messages: [],
    isStreaming: overrides.isStreaming ?? false,
    activeToolCalls: overrides.activeToolCalls ?? [],
    liveObservation: overrides.liveObservation !== undefined ? overrides.liveObservation : null,
    lastMetrics: overrides.lastMetrics !== undefined ? overrides.lastMetrics : null,
    elapsedMs: 0,
    sessionStats: overrides.sessionStats ?? { promptTokens: 0, completionTokens: 0, latencyMs: 0, genTimeMs: 0, turnCount: 0 },
    agentRuns: overrides.agentRuns ?? [],
    agentStreaming: overrides.isStreaming ?? false,
    send: fns.send,
    abort: fns.abort,
    steer: fns.steer,
    setMessages: fns.setMessages,
    resetSession: fns.resetSession,
    onTerminalEvent: vi.fn(),
  });
  mockHooks.useActions.mockReturnValue({ actions: [], loading: false, refresh: fns.refreshActions });
  mockHooks.useFileTree.mockReturnValue({ files: [], loading: false, refresh: vi.fn() });
  mockHooks.useTodos.mockReturnValue({
    todos: [],
    loading: false,
    addTodo: fns.addTodo,
    toggleTodo: fns.toggleTodo,
    removeTodo: fns.removeTodo,
  });
  mockHooks.useObjectives.mockReturnValue({
    objectives: [],
    loading: false,
    refresh: vi.fn(),
    create: fns.createObjective,
    pause: fns.pauseObjective,
    resume: fns.resumeObjective,
    cancel: fns.cancelObjective,
  });
  mockHooks.useTerminal.mockReturnValue({
    lines: [],
    isRunning: false,
    execute: fns.execute,
    clear: fns.clear,
    sessionId: 'default',
    cwd: '/tmp',
    history: [],
    changeSession: fns.changeSession,
    tabComplete: fns.tabComplete,
    addToolOutput: fns.addToolOutput,
  });
  mockHooks.useObservability.mockReturnValue({
    observation: overrides.observation ?? { contextTokens: 0, latency: 0, stages: [], vectorHits: 0, status: 'idle' },
    loading: false,
  });
  mockHooks.useCapabilities.mockReturnValue({ families: [] });
  mockHooks.useMetrics.mockReturnValue({
    metrics: { totalTokens: 0, latency: 0, promptTokens: 0, completionTokens: 0, tokensPerSec: 0 },
    refreshMetrics: vi.fn(),
  });
  mockHooks.useModels.mockReturnValue({
    models: overrides.models ?? [{ id: 'm1', name: 'Model One', provider: 'zen' }],
    current: overrides.currentModel === undefined ? 'm1' : overrides.currentModel,
    provider: overrides.provider ?? 'zen',
    loading: false,
    selectModel: fns.selectModel,
    refresh: fns.refreshModels,
  });
  mockHooks.useMemory.mockReturnValue({
    facts: [],
    loading: false,
    refresh: vi.fn(),
    storeFact: vi.fn(),
    deleteFact: fns.deleteFact,
  });
  mockHooks.useHealth.mockReturnValue({ status: 'online', version: '0.5.16', uptime: 42 });

  render(<WorkspaceLayout />);
  return fns;
}

describe('WorkspaceLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPanelProps.left = {};
    mockPanelProps.center = {};
    mockPanelProps.right = {};
  });

  it('renders the three-panel layout shell', () => {
    setup();
    expect(screen.getByTestId('left-panel')).toBeInTheDocument();
    expect(screen.getByTestId('center-panel')).toBeInTheDocument();
    expect(screen.getByTestId('right-panel')).toBeInTheDocument();
  });

  it('wires sessions/models/objectives into LeftPanel', () => {
    setup();
    const left = mockPanelProps.left;
    expect(left.sessions).toEqual([]);
    expect(left.models).toHaveLength(1);
    expect(left.selectedModel).toBe('m1');
    // Objective props are retired from the sidebar.
    expect(left.objectives).toBeUndefined();
    expect(left.currentSessionId).toBeNull();
    // Callback props are all wired as functions.
    expect(typeof left.onSelectSession).toBe('function');
    expect(typeof left.onDeleteSession).toBe('function');
    expect(typeof left.onNewChat).toBe('function');
    expect(typeof left.onModelChange).toBe('function');
    // Tasks moved to the Activity rail: the sidebar no longer takes them.
    expect(left.onToggleTodo).toBeUndefined();
    expect(left.todos).toBeUndefined();
    expect(typeof mockPanelProps.right.onToggleTodo).toBe('function');
    expect(typeof mockPanelProps.right.onAddTodo).toBe('function');
    expect(typeof mockPanelProps.right.onAbort).toBe('function');
  });

  it('wires messages/streaming/health/model into CenterPanel', () => {
    setup();
    const center = mockPanelProps.center;
    expect(center.messages).toEqual([]);
    expect(center.isStreaming).toBe(false);
    expect(center.health).toMatchObject({ status: 'online', version: '0.5.16' });
    // currentModel fallback resolves to the backend-reported model.
    expect(center.selectedModel).toMatchObject({ id: 'm1', name: 'Model One', provider: 'zen' });
    // The intent badge is retired — currentIntent is no longer
    // a CenterPanel prop. The context-window occupancy meter fills the slot.
    expect(center.currentIntent).toBeUndefined();
    expect(center.currentConfidence).toBeUndefined();
    expect(center.contextWindowSize).toBeUndefined();
    expect(center.contextTokens).toBe(0);
    expect(center.memoryCount).toBe(0);
    expect(typeof center.onSend).toBe('function');
    expect(typeof center.onAbort).toBe('function');
    expect(typeof center.onSteer).toBe('function');
  });

  it('passes the model context window + the LAST CALL prompt to the center meter', () => {
    setup({
      models: [{ id: 'm1', name: 'Model One', provider: 'zen', contextWindow: 32768 }],
      // Addendum (user-reported false 100%): the meter measures the
      // LAST model call's prompt against the window — NOT the session
      // cumulative (prompts re-send history; per-turn prompts overlap,
      // they don't stack). Falls back to sessionStats only when no
      // per-call source has reported yet.
      sessionStats: { promptTokens: 12000, completionTokens: 9, latencyMs: 2300, genTimeMs: 500, turnCount: 2 },
      liveObservation: {
        intent: 'chat',
        confidence: 0.99,
        toolsUsed: [],
        memoryHits: 0,
        contextTokens: 4200, // last call's prompt — wins over the cumulative
        latency: 2300,
      },
    });
    const center = mockPanelProps.center;
    expect(center.contextWindowSize).toBe(32768);
    expect(center.contextTokens).toBe(4200);
  });

  it('wires terminal/metrics/observation/capabilities into RightPanel', () => {
    setup();
    const right = mockPanelProps.right;
    expect(right.terminalLines).toEqual([]);
    expect(right.isTerminalRunning).toBe(false);
    expect(right.terminalCwd).toBe('/tmp');
    expect(right.metrics).toMatchObject({ totalTokens: 0, latency: 0 });
    // The Observe tab is retired — observation and capabilities
    // are no longer RightPanel props. The Agents tab is the canonical surface.
    expect(right.observation).toBeUndefined();
    expect(right.capabilities).toBeUndefined();
    // Stats split wiring: the corner bar receives the session totals + the
    // live-stream flag so it can show cumulative values (with live overrides).
    expect(right.sessionStats).toMatchObject({ promptTokens: 0, completionTokens: 0, turnCount: 0 });
    expect(right.isStreaming).toBe(false);
    expect(right.memoryFacts).toEqual([]);
    expect(typeof right.onTerminalExecute).toBe('function');
    expect(typeof right.onMemoryDelete).toBe('function');
    expect(typeof right.onModelsRefresh).toBe('function');
  });

  it('starts a new chat: clears messages, resets context, and returns panels to canonical tabs', () => {
    const fns = setup();
    act(() => {
      (mockPanelProps.left.onNewChat as () => void)();
    });
    expect(fns.setMessages).toHaveBeenCalledWith([]);
    expect(fns.resetSession).toHaveBeenCalledTimes(1);
    expect(fns.refreshSessions).toHaveBeenCalledTimes(1);
    // Left panel → Chat tab, right panel → Agents tab.
    expect(mockPanelProps.left.forceChatTab).toBe(true);
    expect(mockPanelProps.right.forceAgentsTab).toBe(true);
  });

  it('sends a message through the chat hook with a generated session id', () => {
    const fns = setup();
    act(() => {
      (mockPanelProps.center.onSend as (msg: string, tool?: string) => void)('hello', undefined);
    });
    expect(fns.send).toHaveBeenCalledTimes(1);
    expect(fns.send).toHaveBeenCalledWith('hello', expect.stringMatching(/^session-/), undefined);
    expect(fns.refreshSessions).toHaveBeenCalledTimes(1);
  });

  it('aborts the current turn via the abort callback', () => {
    const fns = setup();
    act(() => {
      (mockPanelProps.center.onAbort as () => void)();
    });
    expect(fns.abort).toHaveBeenCalledTimes(1);
  });

  it('selects a model via the model-change callback', () => {
    const fns = setup();
    act(() => {
      (mockPanelProps.left.onModelChange as (id: string) => void)('m2');
    });
    expect(fns.selectModel).toHaveBeenCalledWith('m2');
  });

  it('deletes a session and refreshes the session list', async () => {
    const fns = setup();
    // handleDeleteSession is async: refreshSessions() runs after the
    // awaited deleteSession microtask, so flush the promise inside act.
    await act(async () => {
      await (mockPanelProps.left.onDeleteSession as (id: string) => Promise<void>)('session-1');
    });
    expect(fns.deleteSession).toHaveBeenCalledWith('session-1');
    expect(fns.refreshSessions).toHaveBeenCalledTimes(1);
  });

  it('auto-switches the right panel to the Terminal tab when a shell tool runs (FIX 4)', () => {
    setup({
      activeToolCalls: [
        { id: 'call_1', name: 'shell', status: 'running', input: 'ls', label: '', duration: undefined },
      ],
    });
    const right = mockPanelProps.right;
    expect(right.forceTerminalTab).toBe(true);
    // Terminal lines are bridged from the active tool call into the panel.
    expect(right.terminalLines).toEqual([]);
  });

  it('auto-switches the right panel to the Memory tab when a memory_op tool runs', () => {
    setup({
      activeToolCalls: [
        { id: 'call_m1', name: 'memory_op', status: 'running', input: 'store', label: '', duration: undefined },
      ],
    });
    const right = mockPanelProps.right;
    expect(right.forceMemoryTab).toBe(true);
    expect(right.onMemoryTabShown).toBeTypeOf('function');
  });

  it('does not force the Memory tab for non-memory tools', () => {
    setup({
      activeToolCalls: [
        { id: 'call_s', name: 'shell', status: 'running', input: 'ls', label: '', duration: undefined },
      ],
    });
    const right = mockPanelProps.right;
    expect(right.forceMemoryTab).toBe(false);
    expect(right.forceTerminalTab).toBe(true); // shell still switches Terminal
  });

  it('auto-activates the Agents tab when a parent turn starts', () => {
    setup({
      isStreaming: true,
      agentRuns: [
        {
          id: 'parent-1',
          name: 'parent',
          role: 'parent',
          status: 'running',
          depth: 0,
          startedAt: Date.now(),
          tools: [],
        },
      ],
    });
    const right = mockPanelProps.right;
    expect(right.forceAgentsTab).toBe(true);
    const runs = (right.agentRuns as Array<Record<string, unknown>>) ?? [];
    expect(runs).toHaveLength(1);
    expect(runs[0].role).toBe('parent');
  });

  it('falls back to the persisted model when the backend reports no current model', () => {
    setup({
      models: [],
      currentModel: null,
      provider: '',
      persistedSettings: { model: 'm2' },
    });
    // effectiveModelId = persisted 'm2' (backend reports none); models is
    // empty so currentModel is undefined and CenterPanel gets the fallback.
    const left = mockPanelProps.left;
    expect(left.selectedModel).toBe('m2');
    const center = mockPanelProps.center;
    expect(center.selectedModel).toMatchObject({ id: 'm2', name: 'm2', provider: '' });
  });

  // Addendum (user-reported false 100%): the meter basis is the LAST
  // model call's prompt (liveObservation.contextTokens), NOT the session
  // cumulative — the old cumulative basis sent the meter to 100%
  // after a few short turns. These tests pin the corrected wiring.
  it('meter shows the last call prompt, not the session cumulative', () => {
    setup({
      sessionStats: { promptTokens: 7500, completionTokens: 29, latencyMs: 7300, genTimeMs: 1000, turnCount: 2 },
      liveObservation: {
        intent: 'chat',
        confidence: 0.99,
        toolsUsed: [],
        memoryHits: 0,
        contextTokens: 1200, // last call's prompt — the meter's basis
        latency: 2300,
      },
      observation: { contextTokens: 3500, latency: 0, stages: [], vectorHits: 0, status: 'idle' },
    });
    const center = mockPanelProps.center;
    expect(center.contextTokens).toBe(1200);
  });

  it('meter uses the live in-flight prompt estimate while streaming', () => {
    setup({
      isStreaming: true,
      sessionStats: { promptTokens: 3500, completionTokens: 0, latencyMs: 0, genTimeMs: 0, turnCount: 1 },
      lastMetrics: { promptTokens: 4000, completionTokens: 0, totalTokens: 0, latency: 0 },
    });
    const center = mockPanelProps.center;
    expect(center.contextTokens).toBe(4000);
  });

  it('does NOT pass observation/capabilities/currentIntent to any panel', () => {
    // The Observe tab and intent badge are retired. No panel should receive
    // these props — they are internal compat only.
    setup();
    const right = mockPanelProps.right;
    const center = mockPanelProps.center;
    expect(right.observation).toBeUndefined();
    expect(right.capabilities).toBeUndefined();
    expect(center.currentIntent).toBeUndefined();
    // The RightTab union no longer includes 'observability'.
    expect(right.forceAgentsTab).toBe(false); // no parent running → no force
  });
});
