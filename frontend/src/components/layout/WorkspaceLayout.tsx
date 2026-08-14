'use client';

import { useState, useCallback, useEffect } from 'react';
import { LeftPanel } from './LeftPanel';
import { CenterPanel } from './CenterPanel';
import { RightPanel } from './RightPanel';
import { ToolExecutionEvent, ActionItem } from '@/types';
import {
  useSessions,
  useChat,
  useActions,
  useFileTree,
  useTodos,
  useObjectives,
  useTerminal,
  useObservability,
  useCapabilities,
  useMetrics,
  useModels,
  useMemory,
  useHealth,
} from '@/hooks/useLocalMind';
import { localmindClient, getPersistedSettings } from '@/lib/localmind/client';
import { isActiveToolStatus } from '@/lib/localmind/progress';

export function WorkspaceLayout() {
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  const [leftPanelWidth, setLeftPanelWidth] = useState(280);
  const [rightPanelWidth, setRightPanelWidth] = useState(320);
  const [isResizingLeft, setIsResizingLeft] = useState(false);
  const [isResizingRight, setIsResizingRight] = useState(false);

  // Handle left panel resize
  const handleMouseMoveLeft = useCallback((e: MouseEvent) => {
    if (!isResizingLeft) return;
    const newWidth = Math.min(Math.max(e.clientX, 180), 400);
    setLeftPanelWidth(newWidth);
  }, [isResizingLeft]);

  const handleMouseUpLeft = useCallback(() => {
    setIsResizingLeft(false);
  }, []);

  // Handle right panel resize
  const handleMouseMoveRight = useCallback((e: MouseEvent) => {
    if (!isResizingRight) return;
    const newWidth = Math.min(Math.max(window.innerWidth - e.clientX, 200), 500);
    setRightPanelWidth(newWidth);
  }, [isResizingRight]);

  const handleMouseUpRight = useCallback(() => {
    setIsResizingRight(false);
  }, []);

  // Add/remove global mouse listeners
  useEffect(() => {
    if (isResizingLeft) {
      document.addEventListener('mousemove', handleMouseMoveLeft);
      document.addEventListener('mouseup', handleMouseUpLeft);
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMoveLeft);
      document.removeEventListener('mouseup', handleMouseUpLeft);
    };
  }, [isResizingLeft, handleMouseMoveLeft, handleMouseUpLeft]);

  useEffect(() => {
    if (isResizingRight) {
      document.addEventListener('mousemove', handleMouseMoveRight);
      document.addEventListener('mouseup', handleMouseUpRight);
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMoveRight);
      document.removeEventListener('mouseup', handleMouseUpRight);
    };
  }, [isResizingRight, handleMouseMoveRight, handleMouseUpRight]);

  // Session state
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  // selectedModel starts empty — synced from the backend's /api/models
  // "current" field once it loads. Previously defaulted to 'qwen3-235b'
  // (a hardcoded Ollama model), which caused a UI/backend desync: the
  // sidebar showed "Qwen3-235B-A22B" even when the backend was using Zen.
  const [selectedModel, setSelectedModel] = useState('');

  // FIX 8: Persisted actions — derived from live tool_calls so the Actions
  // panel is never empty during agent execution. The API-backed actions are
  // used as a fallback for historical data.
  const [liveActions, setLiveActions] = useState<ActionItem[]>([]);

  // Terminal hook — created first so we can reference addToolOutput in useChat
  const terminal = useTerminal();

  // FIX 8: Restore persisted adapter on mount
  useEffect(() => {
    localmindClient.restorePersistedAdapter();
    // Also restore persisted model selection
    const saved = getPersistedSettings();
    if (saved?.model) {
      setSelectedModel(saved.model);
    }
  }, []);

  // Terminal event callback — bridges AI tool output to the terminal panel.
  // When the agent executes a shell or code_exec tool, the SSE stream
  // includes terminal_event messages. This callback receives them and
  // pushes the command + output into the terminal panel so the user can
  // see exactly what the AI is doing in real-time.
  const handleTerminalEvent = useCallback(
    (event: ToolExecutionEvent) => {
      terminal.addToolOutput(event);
    },
    [terminal]
  );

  // Hook data — useChat receives the terminal event callback
  const health = useHealth();
  const { sessions, refresh: refreshSessions, deleteSession } = useSessions();
  const { messages, isStreaming, currentIntent, activeToolCalls, agentRuns, liveObservation, lastMetrics, elapsedMs, sessionStats, send, abort, steer, setMessages } =
    useChat(currentSessionId, handleTerminalEvent);
  const { actions: apiActions, refresh: refreshActions } = useActions(currentSessionId, isStreaming);
  const { files } = useFileTree();
  const { todos, toggleTodo, addTodo } = useTodos(currentSessionId);
  const { objectives, create: createObjective, pause: pauseObjective, resume: resumeObjective, cancel: cancelObjective } = useObjectives(currentSessionId);
  const { observation } = useObservability(currentSessionId);
  const capabilities = useCapabilities();
  const { metrics: polledMetrics } = useMetrics(isStreaming);
  const { models, current: currentModelId, provider: modelProvider, selectModel, refresh: refreshModels } = useModels();
  const { facts: memoryFacts, deleteFact } = useMemory();

  // Sync selectedModel from the backend's /api/models "current" field.
  // This runs whenever the models list refreshes (on mount, after model
  // switch, etc.) so the UI always reflects the backend's active model.
  useEffect(() => {
    if (currentModelId && currentModelId !== selectedModel) {
      setSelectedModel(currentModelId);
    }
  }, [currentModelId, selectedModel]);

  // effectiveModelId prefers the backend-reported current model, falling
  // back to selectedModel (which is also synced above). This ensures the
  // UI never shows a stale/hardcoded model name.
  const effectiveModelId = currentModelId || selectedModel;
  const currentModel = models.find((m) => m.id === effectiveModelId);

  // Merge metrics: prefer SSE-driven lastMetrics (instant) over polled metrics.
  // When a turn_complete event arrives, lastMetrics is populated immediately
  // with tokens_approx and total_latency_ms. The polled metrics lag behind
  // by up to 5s. Use lastMetrics when available, otherwise fall back to poll.
  const metrics = lastMetrics && (lastMetrics.totalTokens > 0 || lastMetrics.latency > 0)
    ? lastMetrics
    : polledMetrics;

  // Bridge the live request metrics into observability without changing their
  // meaning. The stream owns timing, while promptTokens is the only valid
  // source for Context Tokens; completion/total tokens must not be displayed
  // as context. Preserve structured observation values when the backend has
  // already supplied them, and use the live wall clock while it has not.
  const liveObservationForPanel = (() => {
    const live = liveObservation;
    const promptTokens = lastMetrics?.promptTokens || 0;
    const liveLatency = elapsedMs > 0
      ? elapsedMs
      : (lastMetrics?.latency || 0);

    return {
      ...observation,
      ...live,
      // Prefer a positive value from either observation source before using
      // the stream fallback. This prevents a partial live observation from
      // hiding valid backend/historical values.
      // Prefer the live per-turn value whenever the stream has populated it
      // (including a truthful 0 from a fast-path turn that built no context) —
      // a `||` chain here would let a stale polled value mask the current
      // turn's number. Fall back to the polled observation, then the metric
      // stream, only when the stream hasn't reported this turn yet.
      contextTokens: live?.contextTokens !== undefined
        ? live.contextTokens
        : isStreaming
          ? promptTokens || 0
          : observation.contextTokens || promptTokens || 0,
      latency: isStreaming && liveLatency > 0
        ? liveLatency
        : live?.latency || observation.latency || liveLatency,
    };
  })();

  // Clear liveActions when switching sessions so the Actions panel doesn't
  // show the previous session's tool calls.
  useEffect(() => {
    setLiveActions([]);
  }, [currentSessionId]);

  // FIX 3: Derive actions from live tool_calls so the Actions panel
  // always shows what's happening. When the API returns historical
  // actions, we merge them — live actions take priority.
  useEffect(() => {
    if (activeToolCalls.length > 0) {
      const newActions: ActionItem[] = activeToolCalls.map((tc) => ({
        id: tc.id,
        type: tc.name as ActionItem['type'],
        label: tc.label || tc.name.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase()),
        detail: tc.input || '',
        input: tc.input,
        output: tc.output,
        error: tc.error,
        iteration: tc.iteration,
        todoId: tc.todoId,
        reasoning: tc.reasoning,
        status: tc.status,
        timestamp: new Date().toLocaleTimeString('en-GB', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        }),
        duration: tc.duration ? tc.duration / 1000 : undefined,
      }));
      setLiveActions(newActions);
    } else {
      // Clear live actions when no tool calls are active so the panel
      // doesn't show stale data from the previous turn.
      setLiveActions([]);
    }
  }, [activeToolCalls]);

  // FIX: Don't clear liveActions when streaming ends — keep them visible
  // until the API catches up. Previously, liveActions were cleared after 5s,
  // causing the sidebar to flash "No actions yet" when apiActions was still
  // empty. Now we merge live and API actions, deduplicating by ID, with live
  // actions taking priority (they're more recent and accurate).
  // Live actions are only cleared when a NEW streaming session starts
  // (handled in the send() function via setActiveToolCalls([])).

  // Merge: live actions override API actions by ID; API actions fill in the rest
  const actions = (() => {
    if (liveActions.length === 0) return apiActions;
    if (apiActions.length === 0) return liveActions;
    // Build a merged list: live actions first, then API actions not already present
    const liveIds = new Set(liveActions.map(a => a.id));
    const extras = apiActions.filter(a => !liveIds.has(a.id));
    return [...liveActions, ...extras];
  })();

  // FIX 4: Auto-switch right panel to Terminal tab when agent runs
  // shell or code_exec commands, so the user sees the output immediately.
  const [forceTerminalTab, setForceTerminalTab] = useState(false);
  useEffect(() => {
    if (activeToolCalls.some(tc => (tc.name === 'shell' || tc.name === 'code_exec') && isActiveToolStatus(tc.status))) {
      setForceTerminalTab(true);
      // Auto-uncollapse the right panel if it's collapsed
      if (rightPanelCollapsed) {
        setRightPanelCollapsed(false);
      }
    }
  }, [activeToolCalls, rightPanelCollapsed]);

  // Handle new chat
  const handleNewChat = useCallback(() => {
    const newId = `session-${Date.now()}`;
    setCurrentSessionId(newId);
    setMessages([]);
    refreshSessions();
  }, [setMessages, refreshSessions]);

  // Handle session selection
  const handleSelectSession = useCallback(
    (sessionId: string) => {
      setCurrentSessionId(sessionId);
    },
    []
  );

  // FIX: Handle session deletion — must reset active session state
  // when the currently active session is deleted. Without this fix,
  // deleting the active chat removes it from the sidebar but the
  // center panel keeps showing the deleted session's messages.
  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      await deleteSession(sessionId);
      // If the deleted session is the active one, clear everything
      if (sessionId === currentSessionId) {
        setCurrentSessionId(null);
        setMessages([]);
      }
      // Always refresh the session list after deletion
      refreshSessions();
    },
    [currentSessionId, deleteSession, setMessages, refreshSessions]
  );

  // Handle model change
  const handleModelChange = useCallback(
    async (modelId: string) => {
      setSelectedModel(modelId);
      await selectModel(modelId);
    },
    [selectModel]
  );

  // Handle chat send
  const handleSend = useCallback(
    (message: string, tool?: string) => {
      let activeSessionId = currentSessionId;
      if (!activeSessionId) {
        activeSessionId = `session-${Date.now()}`;
        setCurrentSessionId(activeSessionId);
      }
      send(message, activeSessionId, tool);
      // Refresh sessions list so the new message appears in the sidebar immediately
      refreshSessions();
      setTimeout(() => refreshActions(), 2000);
    },
    [currentSessionId, send, refreshSessions, refreshActions]
  );

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-brand-bg-base">
      {/* Left Panel */}
      <div style={{ width: leftPanelWidth }} className="shrink-0 relative">
        <LeftPanel
          sessions={sessions}
          actions={actions}
          files={files}
          todos={todos}
          objectives={objectives}
          onCreateObjective={createObjective}
          onPauseObjective={pauseObjective}
          onResumeObjective={resumeObjective}
          onCancelObjective={cancelObjective}
          activeToolCalls={activeToolCalls}
          models={models}
          selectedModel={effectiveModelId}
          onModelChange={handleModelChange}
          currentSessionId={currentSessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          onDeleteSession={handleDeleteSession}
          onToggleTodo={toggleTodo}
          onAddTodo={addTodo}
          onAbort={abort}
          width={leftPanelWidth}
        />
        {/* Left resize handle */}
        <div
          className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand-green/30 transition-colors"
          onMouseDown={() => setIsResizingLeft(true)}
        />
      </div>

      {/* Center Panel - flex: 1 */}
      <div className="flex-1 min-w-0 min-h-0">
        <CenterPanel
          messages={messages}
          selectedModel={currentModel || { id: effectiveModelId, name: effectiveModelId, provider: modelProvider || '' }}
          isStreaming={isStreaming}
          health={health}
          onSend={handleSend}
          onAbort={abort}
          onSteer={steer}
          currentIntent={currentIntent}
          memoryCount={memoryFacts.length}
          sessionId={currentSessionId || undefined}
          // Context-window occupancy meter: the freed top-bar slot that used
          // to show the redundant confidence badge now shows how full the
          // model's input window is (this turn's prompt / adapter max).
          contextWindowSize={currentModel?.contextWindow}
          contextTokens={lastMetrics && lastMetrics.promptTokens > 0
            ? lastMetrics.promptTokens
            : (liveObservationForPanel.contextTokens || 0)}
        />
      </div>

      {/* Right Panel - 320px, collapsible */}
      <div
        className={`shrink-0 relative transition-all duration-300 ${
          rightPanelCollapsed ? 'w-10' : ''
        }`}
        style={{ width: rightPanelCollapsed ? undefined : rightPanelWidth }}
      >
        {/* Right resize handle */}
        {!rightPanelCollapsed && (
          <div
            className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand-green/30 transition-colors z-10"
            onMouseDown={() => setIsResizingRight(true)}
          />
        )}
        <RightPanel
          terminalLines={terminal.lines}
          isTerminalRunning={terminal.isRunning}
          onTerminalExecute={terminal.execute}
          onTerminalClear={terminal.clear}
          terminalCwd={terminal.cwd}
          terminalSessionId={terminal.sessionId}
          terminalHistory={terminal.history}
          onTerminalTabComplete={terminal.tabComplete}
          onTerminalSessionChange={terminal.changeSession}
          observation={liveObservationForPanel}
          capabilities={capabilities}
          memoryFacts={memoryFacts}
          onMemoryDelete={deleteFact}
          metrics={metrics}
          lastMetrics={lastMetrics}
          elapsedMs={elapsedMs}
          isStreaming={isStreaming}
          sessionStats={sessionStats}
          agentRuns={agentRuns}
          agentStreaming={isStreaming}
          collapsed={rightPanelCollapsed}
          onToggleCollapse={() => setRightPanelCollapsed(!rightPanelCollapsed)}
          forceTerminalTab={forceTerminalTab}
          onTerminalTabShown={() => setForceTerminalTab(false)}
          width={rightPanelWidth}
          onModelsRefresh={refreshModels}
        />
      </div>
    </div>
  );
}
