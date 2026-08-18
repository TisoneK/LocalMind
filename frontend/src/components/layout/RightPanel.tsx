'use client';

import React, { useState, useEffect } from 'react';
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
  width = 320,
  onModelsRefresh,
}: RightPanelProps) {
  // ADR-34 B-10: default to the Agents tab — it is the canonical live surface.
  const [activeTab, setActiveTab] = useState<RightTab>('agents');
  const [showSettings, setShowSettings] = useState(false);
  // Use the parent's refresh function instead of calling useModels() again.
  // Previously this created a SECOND useModels instance whose state was
  // independent from the one in WorkspaceLayout — so saving settings only
  // refreshed this instance, leaving the sidebar's model list stale.
  const refreshModels = onModelsRefresh || (() => Promise.resolve());
  const isCompact = width < 250;

  // FIX 4: When the parent signals to force the terminal tab, switch to it
  useEffect(() => {
    if (forceTerminalTab && activeTab !== 'terminal') {
      setActiveTab('terminal');
      onTerminalTabShown?.();
    }
  }, [forceTerminalTab, activeTab, onTerminalTabShown]);

  // ADR-34 B-9: When a parent turn starts (initialization begins), auto-activate
  // the Agents tab so the user sees the canonical live workspace immediately.
  // This does NOT fight forceTerminalTab — forceTerminalTab fires later (when a
  // shell/code_exec tool starts) and takes priority because it's a more specific
  // signal. forceAgentsTab fires once at turn start and is cleared by the parent.
  useEffect(() => {
    if (forceAgentsTab && activeTab !== 'agents') {
      setActiveTab('agents');
      onAgentsTabShown?.();
    }
  }, [forceAgentsTab, activeTab, onAgentsTabShown]);

  // Listen for 'localmind:activate-terminal' from code block Run buttons
  useEffect(() => {
    const handler = () => {
      if (activeTab !== 'terminal') {
        setActiveTab('terminal');
      }
    };
    window.addEventListener('localmind:activate-terminal', handler);
    return () => window.removeEventListener('localmind:activate-terminal', handler);
  }, [activeTab]);

  const iconSize = 'h-3 w-3';
  const tabs: { id: RightTab; label: string; icon: React.ReactNode }[] = [
    { id: 'terminal', label: 'Terminal', icon: <Terminal className={iconSize} /> },
    { id: 'agents', label: 'Agents', icon: <PanelRight className={iconSize} /> },
    { id: 'memory', label: 'Memory', icon: <Brain className={iconSize} /> },
  ];

  if (collapsed) {
    return (
      <div className="h-full bg-brand-bg-base border-l border-brand-border flex flex-col items-center py-3 gap-3">
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
    <div className="h-full flex flex-col bg-brand-bg-base border-l border-brand-border">
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
        {activeTab === 'memory' && <MemoryTab facts={memoryFacts} onDelete={onMemoryDelete} />}
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
