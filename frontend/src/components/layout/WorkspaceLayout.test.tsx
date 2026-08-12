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
}));

vi.mock('@/hooks/useLocalMind', () => mockHooks);

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: { restorePersistedAdapter: mockClient.restorePersistedAdapter },
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
    isStreaming: false,
    currentIntent: 'CONVERSATION',
    currentConfidence: 0.98,
    activeToolCalls: overrides.activeToolCalls ?? [],
    liveObservation: overrides.liveObservation !== undefined ? overrides.liveObservation : null,
    lastMetrics: null,
    elapsedMs: 0,
    sessionStats: { promptTokens: 0, completionTokens: 0, latencyMs: 0, genTimeMs: 0, turnCount: 0 },
    send: fns.send,
    abort: fns.abort,
    steer: fns.steer,
    setMessages: fns.setMessages,
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
    expect(left.objectives).toEqual([]);
    expect(left.currentSessionId).toBeNull();
    // Callback props are all wired as functions.
    expect(typeof left.onSelectSession).toBe('function');
    expect(typeof left.onDeleteSession).toBe('function');
    expect(typeof left.onNewChat).toBe('function');
    expect(typeof left.onModelChange).toBe('function');
    expect(typeof left.onToggleTodo).toBe('function');
  });

  it('wires messages/streaming/health/model into CenterPanel', () => {
    setup();
    const center = mockPanelProps.center;
    expect(center.messages).toEqual([]);
    expect(center.isStreaming).toBe(false);
    expect(center.health).toMatchObject({ status: 'online', version: '0.5.16' });
    // currentModel fallback resolves to the backend-reported model.
    expect(center.selectedModel).toMatchObject({ id: 'm1', name: 'Model One', provider: 'zen' });
    expect(center.currentIntent).toBe('CONVERSATION');
    // Stats split: the redundant confidence badge is gone from the top bar —
    // it only lives in the Observe panel now. Its slot is the context-window
    // occupancy meter, fed by the model's window size + live prompt tokens.
    expect(center.currentConfidence).toBeUndefined();
    expect(center.contextWindowSize).toBeUndefined();
    expect(center.contextTokens).toBe(0);
    expect(center.memoryCount).toBe(0);
    expect(typeof center.onSend).toBe('function');
    expect(typeof center.onAbort).toBe('function');
    expect(typeof center.onSteer).toBe('function');
  });

  it('passes the model context window + live prompt tokens to the center meter', () => {
    setup({
      models: [{ id: 'm1', name: 'Model One', provider: 'zen', contextWindow: 32768 }],
      liveObservation: {
        intent: 'chat',
        confidence: 0.9,
        toolsUsed: [],
        memoryHits: 0,
        contextTokens: 12000,
        latency: 0,
      },
    });
    const center = mockPanelProps.center;
    expect(center.contextWindowSize).toBe(32768);
    expect(center.contextTokens).toBe(12000);
  });

  it('wires terminal/metrics/observation/capabilities into RightPanel', () => {
    setup();
    const right = mockPanelProps.right;
    expect(right.terminalLines).toEqual([]);
    expect(right.isTerminalRunning).toBe(false);
    expect(right.terminalCwd).toBe('/tmp');
    expect(right.metrics).toMatchObject({ totalTokens: 0, latency: 0 });
    expect(right.observation).toMatchObject({ contextTokens: 0, latency: 0 });
    // Stats split wiring: the corner bar receives the session totals + the
    // live-stream flag so it can show cumulative values (with live overrides).
    expect(right.sessionStats).toMatchObject({ promptTokens: 0, completionTokens: 0, turnCount: 0 });
    expect(right.isStreaming).toBe(false);
    expect(right.capabilities).toEqual({ families: [] });
    expect(right.memoryFacts).toEqual([]);
    expect(typeof right.onTerminalExecute).toBe('function');
    expect(typeof right.onMemoryDelete).toBe('function');
    expect(typeof right.onModelsRefresh).toBe('function');
  });

  it('starts a new chat: clears messages and refreshes the session list', () => {
    const fns = setup();
    act(() => {
      (mockPanelProps.left.onNewChat as () => void)();
    });
    expect(fns.setMessages).toHaveBeenCalledWith([]);
    expect(fns.refreshSessions).toHaveBeenCalledTimes(1);
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

  // Regression: the live per-turn contextTokens (including a truthful 0 from
  // a fast-path turn that built no context) must win over a stale polled
  // value — the old `||` chain let the polled observation mask the current
  // turn's number.
  it('prefers live per-turn contextTokens over a stale polled observation', () => {
    setup({
      observation: { contextTokens: 3500, latency: 0, stages: [], vectorHits: 0, status: 'idle' },
      liveObservation: {
        intent: 'chat',
        confidence: 0.99,
        toolsUsed: [],
        memoryHits: 0,
        contextTokens: 0,
        latency: 2300,
      },
    });
    const right = mockPanelProps.right;
    const obs = right.observation as { contextTokens: number };
    expect(obs.contextTokens).toBe(0);
  });

  it('falls back to the polled observation when the stream has not reported a turn yet', () => {
    setup({
      observation: { contextTokens: 3500, latency: 2900, stages: [], vectorHits: 0, status: 'idle' },
      liveObservation: null,
    });
    const right = mockPanelProps.right;
    const obs = right.observation as { contextTokens: number };
    expect(obs.contextTokens).toBe(3500);
  });
});
