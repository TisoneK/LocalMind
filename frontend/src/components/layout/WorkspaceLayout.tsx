'use client';

import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { LeftPanel } from './LeftPanel';
import { CommandPalette } from './CommandPalette';
import { CenterPanel } from './CenterPanel';
import { StateExplorer } from '@/components/engine/StateExplorer';
import { RightPanel } from './RightPanel';
import { TitleBar } from './TitleBar';
import { ToolExecutionEvent, ActionItem } from '@/types';
import {
  useSessions,
  useChat,
  useActions,
  useFileTree,
  useTodos,
  useObjectives,
  useTerminal,
  useMetrics,
  useModels,
  useMemory,
  useHealth,
} from '@/hooks/useLocalMind';
import { localmindClient, getPersistedSettings } from '@/lib/localmind/client';
import { isActiveToolStatus } from '@/lib/localmind/progress';
import { exportSessions, copySessionsToClipboard, type ExportFormat } from '@/lib/localmind/exportChats';
import { RecoveryBoundary } from '@/components/shared/RecoveryBoundary';

export function WorkspaceLayout() {
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  // Chat mode state ("auto" | "agent" | "direct").
  const [chatMode, setChatMode] = useState<string>('auto');
  // Agent engine ("classic" | "state"). "state" replaces the chat pane with the State Explorer — the
  // engine works a goal as a search over states, so showing it as a conversation would misrepresent it.
  const [engine, setEngine] = useState<string>('classic');
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
  // Initial state reads the persisted choice directly (no effect-time
  // setState); FIX 8 below re-syncs from the backend's "current" field once
  // it loads. Previously defaulted to '' then was set again in the mount
  // effect, which cascaded an extra render on every cold start.
  const [selectedModel, setSelectedModel] = useState(() => getPersistedSettings()?.model || '');

  // FIX 8: Actions derive directly from live tool_calls during render (no
  // effect-time setState): the Actions panel is never empty during agent
  // execution, and the API-backed actions are the fallback for historical
  // data (merged by ID below).

  // Terminal hook — created first so we can reference addToolOutput in useChat
  const terminal = useTerminal();

  // Ref to avoid re-running the resume logic on every
  // sessions update — only fire once on the first non-empty session load.
  const hasAutoSelectedRef = useRef(false);

  // FIX 8: Restore persisted adapter on mount (the persisted model is read
  // in the selectedModel initializer above — no effect-time setState here).
  useEffect(() => {
    localmindClient.restorePersistedAdapter();
    // Load persisted chat mode from backend settings.
    localmindClient.getSettings().then((s) => {
      if (s.chat_mode) setChatMode(s.chat_mode);
      if (s.engine) setEngine(s.engine);
    }).catch(() => {});
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
  const { sessions, loading: sessionsLoading, refresh: refreshSessions, deleteSession, deleteSessions } = useSessions();

  // Auto-resume the most recent session on startup when
  // the user has configured startup_session = "resume". Sessions are sorted
  // by last_active descending from the backend, so sessions[0] is the most
  // recent. Fires only once (guarded by hasAutoSelectedRef) and only when
  // the session list first populates.
  useEffect(() => {
    if (hasAutoSelectedRef.current || sessionsLoading || sessions.length === 0) return;
    hasAutoSelectedRef.current = true;
    localmindClient.getSettings().then((settings) => {
      if (settings.startup_session === 'resume' && sessions[0]?.id) {
        setCurrentSessionId(sessions[0].id);
      }
    }).catch(() => {
      // Non-fatal — default to new chat.
    });
  }, [sessions, sessionsLoading]);
  const { messages, fileDiffs, isStreaming, isResponseReady, activeToolCalls, agentRuns, liveObservation, lastMetrics, reflectionLessons, passiveMemories, elapsedMs, sessionStats, goal, send, abort, steer, setMessages, resetSession } =
    useChat(currentSessionId, handleTerminalEvent);
  const { actions: apiActions, refresh: refreshActions } = useActions(currentSessionId, isStreaming);
  const { files, refresh: refreshFiles } = useFileTree();
  const { todos, toggleTodo, addTodo } = useTodos(currentSessionId);
  // useObjectives keeps running for backend sync, but the
  // sidebar no longer renders the ObjectivesPanel. The create/pause/resume/
  // cancel functions are intentionally unused — the objective persistence
  // layer stays warm for a future product decision.
  useObjectives(currentSessionId);
  // useCapabilities() was retired — the Capability Catalog was
  // only rendered in the Observe tab, which is now removed.
  const { metrics: polledMetrics } = useMetrics(isStreaming);
  const { models, current: currentModelId, selectModel, refresh: refreshModels } = useModels();
  const { facts: memoryFacts, deleteFact, storeFact, editFact, refresh: refreshMemory } = useMemory();

  // Sync selectedModel from the backend's /api/models "current" field.
  // Runs whenever the models list refreshes (on mount, after model switch,
  // etc.) so the UI always reflects the backend's active model — adjusted
  // during render (state-mirrors-a-prop pattern; no effect-time setState).
  const [lastBackendCurrent, setLastBackendCurrent] = useState(currentModelId);
  if (lastBackendCurrent !== currentModelId) {
    setLastBackendCurrent(currentModelId);
    if (currentModelId) setSelectedModel(currentModelId);
  }

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

  // Context-window occupancy for the top-bar meter: the LAST model call's
  // prompt (liveObservation.contextTokens = last turn's call; the live
  // lastMetrics estimate while streaming), NOT the session-cumulative prompt
  // sum. The old basis (cumulative ÷ window) always raced to 100% within a
  // few turns regardless of real occupancy — the window fills by per-call
  // prompt size, not by adding whole turns' re-sent prompts (each call
  // re-sends history, so per-turn prompt tokens overlap, they don't stack).
  const lastCallPromptTokens = Math.max(
    Number(liveObservation?.contextTokens || 0),
    lastMetrics?.promptTokens || 0,
  );
  const meterBasisTokens = lastCallPromptTokens || 0;
  const cachedTokensForMeter = lastCallPromptTokens > 0
    ? Math.min(lastCallPromptTokens, lastMetrics?.cachedTokens || 0)
    : 0;

  // FIX 3: Actions derived from live tool_calls so the Actions panel
  // always shows what's happening. When the API returns historical
  // actions, we merge them below — live actions take priority (they're
  // more recent and accurate), and switching sessions drops the previous
  // session's live rows (one-frame empty, then whatever the new session
  // streams in).
  const [lastActionsSession, setLastActionsSession] = useState(currentSessionId);
  if (lastActionsSession !== currentSessionId) {
    setLastActionsSession(currentSessionId);
  }
  const liveActions = useMemo<ActionItem[]>(
    () =>
      lastActionsSession === currentSessionId
        ? activeToolCalls.map((tc) => ({
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
          }))
        : [],
    [activeToolCalls, currentSessionId, lastActionsSession],
  );

  // Merge: live actions override API actions by ID; API actions fill in the rest
  const actions = (() => {
    if (liveActions.length === 0) return apiActions;
    if (apiActions.length === 0) return liveActions;
    // Build a merged list: live actions first, then API actions not already present
    const liveIds = new Set(liveActions.map(a => a.id));
    const extras = apiActions.filter(a => !liveIds.has(a.id));
    return [...liveActions, ...extras];
  })();

  // A shell command's output is shown inside the chat turn itself, so the right rail no longer
  // jumps to the Terminal tab when the agent runs one: that hid the plan and tasks the user was
  // following. The Terminal tab is still one click away (and `localmind:activate-terminal`).
  // Auto-switch right panel to Agents tab when a parent turn
  // starts. The Agents workspace is the canonical live surface for
  // parent/child agent state — the user should see the initialization
  // events (ack, understanding, plan, tool evidence, synthesis) arrive
  // in real-time, not be hidden behind the Observe tab.
  const [forceAgentsTab, setForceAgentsTab] = useState(false);
  // Auto-switch right panel to Memory tab when the agent
  // runs a memory_op tool (store/recall/forget) so the user sees the fact
  // land in memory immediately. Flag consumed by RightPanel exactly like
  // forceTerminalTab/forceAgentsTab (unconditional consume).
  const [forceMemoryTab, setForceMemoryTab] = useState(false);
  // "New Chat" returns the left sidebar to the Chat tab (it may be stuck on
  // Actions/Files from the previous session's tool activity).
  const [forceChatTab, setForceChatTab] = useState(false);
  // Fire only on the rising edge (turn start), not on every render while
  // streaming — derived during render (state-mirrors-the-data pattern; no
  // effect-time setState), so this also cannot re-fight forceTerminalTab
  // after a shell/code_exec tool starts.
  const parentRunning = (agentRuns || []).some(
    (r) => r.role === 'parent' && r.status === 'running'
  );
  const [wasParentRunning, setWasParentRunning] = useState(false);
  if (parentRunning !== wasParentRunning) {
    setWasParentRunning(parentRunning);
    if (parentRunning) {
      setForceAgentsTab(true);
      if (rightPanelCollapsed) {
        setRightPanelCollapsed(false);
      }
    }
  }

  // memory_op tool activity → Memory tab (like the shell →
  // Terminal switch above). memory_op is the agent's explicit memory tool
  // (store/recall/forget/list) — a real signal the user should see. Derived
  // during render on the activity's start edge (no effect-time setState).
  const memoryOpActive = activeToolCalls.some(
    (tc) => tc.name === 'memory_op' && isActiveToolStatus(tc.status)
  );
  const [wasMemoryOpActive, setWasMemoryOpActive] = useState(false);
  if (memoryOpActive !== wasMemoryOpActive) {
    setWasMemoryOpActive(memoryOpActive);
    if (memoryOpActive) {
      setForceMemoryTab(true);
      if (rightPanelCollapsed) {
        setRightPanelCollapsed(false);
      }
    }
  }

  // Handle new chat
  const handleNewChat = useCallback(() => {
    const newId = `session-${Date.now()}`;
    // Start from a clean slate: context counter back to 0, no lingering
    // metrics/agent runs from the previous session.
    resetSession();
    setCurrentSessionId(newId);
    setMessages([]);
    // Return both panels to their canonical tabs for a fresh conversation:
    // left → Chat, right → Agents.
    setForceChatTab(true);
    setForceAgentsTab(true);
    refreshSessions();
  }, [resetSession, setMessages, refreshSessions]);

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

  // Bulk delete for the multi-select chat actions.
  const handleDeleteSessions = useCallback(
    async (sessionIds: string[]) => {
      const deleted = await deleteSessions(sessionIds);
      // If the active session was among those deleted, clear the transcript.
      if (currentSessionId && deleted.includes(currentSessionId)) {
        setCurrentSessionId(null);
        setMessages([]);
      }
      refreshSessions();
    },
    [currentSessionId, deleteSessions, setMessages, refreshSessions]
  );

  // Bulk export selected chats to a downloaded Markdown/JSON file.
  const handleExportSessions = useCallback(
    async (sessionIds: string[], format: ExportFormat) => {
      await exportSessions(
        sessions,
        sessionIds,
        format,
        (id) => localmindClient.getSessionHistory(id),
        // Include each session's todo checklist in the export.
        (id) => localmindClient.getTodos(id),
      );
    },
    [sessions]
  );

  // Copy-to-clipboard bulk action: the same export payload, written to the
  // clipboard. Rejections propagate so the sidebar can flash the failure.
  const handleCopySessions = useCallback(
    async (sessionIds: string[], format: ExportFormat) => {
      await copySessionsToClipboard(
        sessions,
        sessionIds,
        format,
        (id) => localmindClient.getSessionHistory(id),
        (id) => localmindClient.getTodos(id),
      );
    },
    [sessions]
  );

  // Handle model change
  const handleModelChange = useCallback(
    async (modelId: string) => {
      setSelectedModel(modelId);
      await selectModel(modelId);
    },
    [selectModel]
  );

  // Handle chat mode change — persist to backend.
  const handleChatModeChange = useCallback(
    async (mode: 'auto' | 'agent' | 'direct') => {
      setChatMode(mode);
      try {
        await localmindClient.setChatMode(mode);
      } catch {
        // Non-fatal — the UI still reflects the change immediately.
      }
    },
    []
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

  // Retry re-runs the last question in place: the failed reply and its error card are
  // replaced rather than kept above the new attempt.
  const handleRetry = useCallback(
    (message: string, edited?: boolean) => {
      if (!currentSessionId) return;
      send(message, currentSessionId, undefined, edited ? 'edit' : true);
      refreshSessions();
    },
    [currentSessionId, send, refreshSessions]
  );

  // Settings can change the chat mode too; keep the message box's picker in step.
  useEffect(() => {
    const onMode = (e: Event) => {
      const m = (e as CustomEvent<{ mode?: 'auto' | 'agent' | 'direct' }>).detail?.mode;
      if (m) setChatMode(m);
    };
    window.addEventListener('localmind:chat-mode-changed', onMode);
    return () => window.removeEventListener('localmind:chat-mode-changed', onMode);
  }, []);

  // Choosing the engine in Settings swaps what the center of the app is; apply it without a reload.
  useEffect(() => {
    const onEngine = (e: Event) => {
      const next = (e as CustomEvent<{ engine?: string }>).detail?.engine;
      if (next === 'classic' || next === 'state') setEngine(next);
    };
    window.addEventListener('localmind:engine-changed', onEngine);
    return () => window.removeEventListener('localmind:engine-changed', onEngine);
  }, []);

  // The Chat→Agent gate (in ChatMessage) dispatches this when
  // the user accepts. Switch to Agent mode (persist to backend) THEN resend the
  // original message as an agent turn — the await ensures the backend has the
  // new mode before the turn runs.
  useEffect(() => {
    const onSwitch = async (e: Event) => {
      const msg = (e as CustomEvent).detail?.message as string | undefined;
      await handleChatModeChange('agent');
      if (msg && msg.trim()) handleSend(msg);
    };
    window.addEventListener('localmind:switch-to-agent', onSwitch);
    return () => window.removeEventListener('localmind:switch-to-agent', onSwitch);
  }, [handleChatModeChange, handleSend]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-brand-bg-app">
      <CommandPalette
        sessions={sessions}
        currentSessionId={currentSessionId}
        isStreaming={isStreaming}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onAbort={abort}
        onToggleRightPanel={() => setRightPanelCollapsed((c) => !c)}
      />
      {/* Deliberate LocalMind title-bar chrome */}
      <TitleBar version="v0.5.16" />
      {/* Three-panel workspace */}
      <div className="flex flex-1 min-h-0">
      {/* Left Panel */}
      <div style={{ width: leftPanelWidth }} className="shrink-0 relative">
        {/* A crash in the sidebar stays in the sidebar: the conversation and the
            side panel keep working, and Try again remounts just this region. */}
        <RecoveryBoundary label="The sidebar">
          <LeftPanel
          sessions={sessions}
          files={files}
          models={models}
          selectedModel={effectiveModelId}
          onModelChange={handleModelChange}
          currentSessionId={currentSessionId}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          onDeleteSession={handleDeleteSession}
          onDeleteSessions={handleDeleteSessions}
          onExportSessions={handleExportSessions}
          onCopySessions={handleCopySessions}
          forceChatTab={forceChatTab}
          onChatTabShown={() => setForceChatTab(false)}
          onFilesChanged={refreshFiles}
          width={leftPanelWidth}
          fileDiffs={fileDiffs}
          isStreaming={isStreaming}
        />
        </RecoveryBoundary>
        {/* Left resize handle */}
        <div
          className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand-green/30 transition-colors"
          onMouseDown={() => setIsResizingLeft(true)}
        />
      </div>

      {/* Center Panel - flex: 1 */}
      <div className="flex-1 min-w-0 min-h-0">
        {/* A crash in the conversation stays here: the sidebar and side panel keep
            working, and Try again remounts just this region (a full reload stays available below the card). */}
        <RecoveryBoundary label="The conversation panel">
        {engine === 'state' ? (
          <StateExplorer />
        ) : (
        <CenterPanel
          messages={messages}
          title={sessions.find((x) => x.id === currentSessionId)?.title}
          isStreaming={isStreaming}
          responseReady={isResponseReady}
          health={health}
          onSend={handleSend}
          onRetry={handleRetry}
          onAbort={abort}
          onSteer={steer}
          memoryCount={memoryFacts.length}
          todos={todos}
          sessionId={currentSessionId || undefined}
          chatMode={chatMode}
          onChatModeChange={handleChatModeChange}
          // Context-window occupancy meter: the freed top-bar slot that used
          // to show the redundant confidence badge now shows how full the
          // model's input window is — the LAST call's prompt / the window.
          // currentModel.contextWindow is absent when the window is unknown
          // (backend omits it rather than sending the "default" guess), and
          // CenterPanel then shows the token count without a percentage.
          contextWindowSize={currentModel?.contextWindow}
          contextTokens={meterBasisTokens}
          cachedTokens={cachedTokensForMeter}
          contextBreakdown={lastMetrics?.contextBreakdown}
          injectedItems={(() => {
            // The last turn's injected-item ledger — what its prompts
            // actually carried (audit view in the context popover).
            for (let i = messages.length - 1; i >= 0; i--) {
              const m = messages[i];
              if (m.role === 'assistant') return m.injectedItems;
            }
            return undefined;
          })()}
          reflectionLessons={reflectionLessons}
          passiveMemories={passiveMemories}
          fileDiffs={fileDiffs}
          sessionStats={sessionStats}
          lastMetrics={lastMetrics}
          elapsedMs={elapsedMs}
          goal={goal}
        />
        )}
        </RecoveryBoundary>
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
        <RecoveryBoundary label="The side panel">
        <RightPanel
          chatSessionId={currentSessionId}
          terminalLines={terminal.lines}
          isTerminalRunning={terminal.isRunning}
          onTerminalExecute={terminal.execute}
          onTerminalClear={terminal.clear}
          terminalCwd={terminal.cwd}
          terminalSessionId={terminal.sessionId}
          terminalHistory={terminal.history}
          onTerminalTabComplete={terminal.tabComplete}
          onTerminalSessionChange={terminal.changeSession}
          memoryFacts={memoryFacts}
          onMemoryDelete={deleteFact}
          onMemoryStore={storeFact}
          onMemoryEdit={editFact}
          onMemoryRefresh={refreshMemory}
          metrics={metrics}
          lastMetrics={lastMetrics}
          elapsedMs={elapsedMs}
          isStreaming={isStreaming}
          sessionStats={sessionStats}
          agentRuns={agentRuns}
          agentStreaming={isStreaming}
          todos={todos}
          actions={actions}
          onToggleTodo={toggleTodo}
          onAddTodo={addTodo}
          onAbort={abort}
          fileDiffs={fileDiffs}
          answering={isStreaming && !!messages[messages.length - 1]?.content?.trim()}
          collapsed={rightPanelCollapsed}
          onToggleCollapse={() => setRightPanelCollapsed(!rightPanelCollapsed)}
          forceTerminalTab={false}
          forceAgentsTab={forceAgentsTab}
          onAgentsTabShown={() => setForceAgentsTab(false)}
          forceMemoryTab={forceMemoryTab}
          onMemoryTabShown={() => setForceMemoryTab(false)}
          width={rightPanelWidth}
          onModelsRefresh={refreshModels}
        />
        </RecoveryBoundary>
      </div>
      </div>
    </div>
  );
}
