'use client';

import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Brain, PanelRightClose, PanelRight, Settings } from 'lucide-react';
import { TerminalLine, MemoryFact, PerformanceMetrics as PerformanceMetricsType, CompletionSuggestion, SessionStats, AgentRun } from '@/types';
import { TerminalPanel } from '@/components/panels/TerminalPanel';
import { AgentWorkspace } from '@/components/panels/AgentWorkspace';
import { MemoryTab } from '@/components/panels/MemoryTab';
import { PerformanceMetrics } from '@/components/panels/PerformanceMetrics';
import { SettingsModal } from '@/components/shared/SettingsModal';

interface RightPanelProps {
  terminalLines: TerminalLine[];
  isTerminalRunning: boolean;
  onTerminalExecute: (command: string, cwd?: string) => Promise<unknown>;
  onTerminalClear: () => void;
  terminalCwd?: string;
  terminalSessionId?: string;
  terminalHistory?: string[];
  onTerminalTabComplete?: (partial: string) => Promise<CompletionSuggestion[]>;
  onTerminalSessionChange?: (sessionId: string) => void;
  memoryFacts: MemoryFact[];
  onMemoryDelete?: (id: string) => void;
  /** Persist a manually entered fact via the memory API (B-2026-08-23-14). */
  onMemoryStore?: (content: string, source: string) => Promise<void>;
  /** Correct a stored fact's content (B-2026-08-23-14 follow-up). */
  onMemoryEdit?: (id: string, content: string) => Promise<void>;
  /** Re-fetch memory facts (tab polls while visible). */
  onMemoryRefresh?: () => Promise<void>;
  metrics: PerformanceMetricsType;
  /** SSE-driven lastMetrics for instant token display */
  lastMetrics?: PerformanceMetricsType | null;
  /** Wall-clock request duration updated while the stream is active */
  elapsedMs?: number;
  /** Whether a request is in flight — the corner shows live values */
  isStreaming?: boolean;
  /** Cumulative per-chat totals (stats split) */
  sessionStats?: SessionStats | null;
  /** Live parent/child run tree for the Agent workspace. */
  agentRuns?: AgentRun[];
  /** Whether the parent loop is currently streaming. */
  agentStreaming?: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** FIX 4: Force the terminal tab to be active when agent runs shell/code_exec */
  forceTerminalTab?: boolean;
  /** Called after the terminal tab has been shown */
  onTerminalTabShown?: () => void;
  /** ADR-34 B-9: Force the Agents tab to be active when a parent turn starts
   * (initialization begins). The Agents workspace is the canonical live
   * surface for parent/child agent state. */
  forceAgentsTab?: boolean;
  /** Called after the Agents tab has been shown */
  onAgentsTabShown?: () => void;
  /** B-2026-08-23-15: Force the Memory tab when a memory_op tool runs. */
  forceMemoryTab?: boolean;
  /** Called after the Memory tab has been shown */
  onMemoryTabShown?: () => void;
  width?: number;
  /** Called when settings change so the parent can refresh its model list */
  onModelsRefresh?: () => Promise<void>;
}

// ADR-34 B-10: the Observe tab and its Intent Classification / Agent Pipeline
// visualization are retired. The Agents tab is the canonical live surface.
type RightTab = 'terminal' | 'memory' | 'agents';

export function RightPanel({
  terminalLines,
  isTerminalRunning,
  onTerminalExecute,
  onTerminalClear,
  terminalCwd,
  terminalSessionId,
  terminalHistory,
  onTerminalTabComplete,
  onTerminalSessionChange,
  memoryFacts,
  onMemoryDelete,
  onMemoryStore,
  onMemoryEdit,
  onMemoryRefresh,
  metrics,
  lastMetrics,
  elapsedMs,
  isStreaming,
  sessionStats,
  agentRuns = [],
  agentStreaming = false,
  collapsed,
  onToggleCollapse,
  forceTerminalTab,
  onTerminalTabShown,
  forceAgentsTab,
  onAgentsTabShown,
  forceMemoryTab,
  onMemoryTabShown,
  width = 320,
  onModelsRefresh,
}: RightPanelProps) {
  // ADR-34 B-10: default to the Agents tab — it is the canonical live surface.
  const [activeTab, setActiveTab] = useState<RightTab>('agents');
  const [showSettings, setShowSettings] = useState(false);

  // B-2026-08-23-4: the chat tool timeline's "Open Settings" guide button
  // dispatches a window event (ToolSteps is deep in the chat tree, outside
  // this panel) — open the Settings modal here when it fires.
  useEffect(() => {
    const open = () => setShowSettings(true);
    window.addEventListener('localmind:open-settings', open);
    return () => window.removeEventListener('localmind:open-settings', open);
  }, []);
  // Use the parent's refresh function instead of calling useModels() again.
  // Previously this created a SECOND useModels instance whose state was
  // independent from the one in WorkspaceLayout — so saving settings only
  // refreshed this instance, leaving the sidebar's model list stale.
  const refreshModels = onModelsRefresh || (() => Promise.resolve());
  const isCompact = width < 250;

  // B-2026-08-23-15: consume the force flags UNCONDITIONALLY (the forceChatTab
  // fix). The old guarded consume (`activeTab !== target`) left the flag set
  // when the user was already on the target tab, so a LATER event (another
  // force flag, a tool event) could re-fire it and yank the panel away from
  // the user's current tab. Consuming always — even when already on the target
  // — means the flag is gone before any later signal can race it. Each flag
  // fires at most once per activation (a consumed ref, since the setActiveTab
  // below re-runs this effect via the activeTab dep).
  const terminalConsumed = useRef(false);
  useEffect(() => {
    if (!forceTerminalTab) {
      terminalConsumed.current = false;
      return;
    }
    if (terminalConsumed.current) return;
    terminalConsumed.current = true;
    if (activeTab !== 'terminal') setActiveTab('terminal');
    onTerminalTabShown?.();
  }, [forceTerminalTab, activeTab, onTerminalTabShown]);

  const agentsConsumed = useRef(false);
  useEffect(() => {
    if (!forceAgentsTab) {
      agentsConsumed.current = false;
      return;
    }
    if (agentsConsumed.current) return;
    agentsConsumed.current = true;
    if (activeTab !== 'agents') setActiveTab('agents');
    onAgentsTabShown?.();
  }, [forceAgentsTab, activeTab, onAgentsTabShown]);

  const memoryConsumed = useRef(false);
  useEffect(() => {
    if (!forceMemoryTab) {
      memoryConsumed.current = false;
      return;
    }
    if (memoryConsumed.current) return;
    memoryConsumed.current = true;
    if (activeTab !== 'memory') setActiveTab('memory');
    onMemoryTabShown?.();
  }, [forceMemoryTab, activeTab, onMemoryTabShown]);

  // Listen for 'localmind:activate-terminal' from code block Run buttons
  // and 'localmind:focus-terminal' from the left panel's ⋮ overflow menu.
  useEffect(() => {
    const handler = () => {
      if (collapsed) onToggleCollapse();
      if (activeTab !== 'terminal') setActiveTab('terminal');
    };
    window.addEventListener('localmind:activate-terminal', handler);
    window.addEventListener('localmind:focus-terminal', handler);
    return () => {
      window.removeEventListener('localmind:activate-terminal', handler);
      window.removeEventListener('localmind:focus-terminal', handler);
    };
  }, [activeTab, collapsed, onToggleCollapse]);

  // B-2026-08-23-26: left panel ⋮ menu → focus Agents tab.
  useEffect(() => {
    const handler = () => {
      if (collapsed) onToggleCollapse();
      if (activeTab !== 'agents') setActiveTab('agents');
    };
    window.addEventListener('localmind:focus-agents', handler);
    return () => window.removeEventListener('localmind:focus-agents', handler);
  }, [activeTab, collapsed, onToggleCollapse]);

  // B-2026-08-23-26: left panel ⋮ menu → focus Memory tab.
  useEffect(() => {
    const handler = () => {
      if (collapsed) onToggleCollapse();
      if (activeTab !== 'memory') setActiveTab('memory');
    };
    window.addEventListener('localmind:focus-memory', handler);
    return () => window.removeEventListener('localmind:focus-memory', handler);
  }, [activeTab, collapsed, onToggleCollapse]);

  const iconSize = 'h-3 w-3';
  const tabs: { id: RightTab; label: string; icon: React.ReactNode }[] = [
    { id: 'terminal', label: 'Terminal', icon: <Terminal className={iconSize} /> },
    { id: 'agents', label: 'Agents', icon: <PanelRight className={iconSize} /> },
    { id: 'memory', label: 'Memory', icon: <Brain className={iconSize} /> },
  ];

  if (collapsed) {
    return (
      <div className="h-full bg-brand-bg-app border-l border-brand-border flex flex-col items-center py-3 gap-3">
        <button
          onClick={() => setShowSettings(true)}
          className="p-1.5 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
          title="Settings"
        >
          <Settings className="h-4 w-4" />
        </button>
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
          title="Expand panel"
        >
          <PanelRight className="h-4 w-4" />
        </button>
        <div className="w-px flex-1 bg-brand-border" />
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => {
              setActiveTab(tab.id);
              onToggleCollapse();
            }}
            className="p-1.5 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
            title={tab.label}
          >
            {tab.icon}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-brand-bg-app border-l border-brand-border">
      {/* Header */}
      <div className="flex items-center justify-center gap-2 px-2 py-2 border-b border-brand-border">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center ${isCompact ? 'p-2.5' : 'gap-1 px-2 py-1'} rounded text-[10px] font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-brand-border text-brand-green-soft'
                : 'text-brand-green-muted hover:text-brand-green-soft hover:bg-brand-border/50'
            }`}
            title={isCompact ? tab.label : undefined}
          >
            {tab.icon}
            {!isCompact && tab.label}
          </button>
        ))}
        <button
          onClick={() => setShowSettings(true)}
          className="p-2.5 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
          title="Settings"
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onToggleCollapse}
          className="p-2.5 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft transition-colors"
          title="Collapse panel"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Tab content — min-h-0 lets this flex child actually SCROLL its own
          overflow (Agent Workspace cards, terminal, memory) instead of growing
          and pushing the panel/page. */}
      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        {activeTab === 'terminal' && (
          <TerminalPanel
            lines={terminalLines}
            onExecute={onTerminalExecute}
            onClear={onTerminalClear}
            isRunning={isTerminalRunning}
            cwd={terminalCwd}
            sessionId={terminalSessionId}
            onTabComplete={onTerminalTabComplete}
            history={terminalHistory}
            onSessionChange={onTerminalSessionChange}
          />
        )}
        {activeTab === 'agents' && <AgentWorkspace runs={agentRuns} isStreaming={agentStreaming} />}
        {activeTab === 'memory' && (
          <MemoryTab
            facts={memoryFacts}
            onDelete={onMemoryDelete}
            onStore={onMemoryStore}
            onEdit={onMemoryEdit}
            onRefresh={onMemoryRefresh}
          />
        )}
      </div>

      {/* Performance metrics — session cumulative (stats split) */}
      <PerformanceMetrics
        metrics={metrics}
        lastMetrics={lastMetrics}
        elapsedMs={elapsedMs}
        isStreaming={isStreaming}
        sessionStats={sessionStats}
      />

      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} onSave={refreshModels} />
      )}
    </div>
  );
}
