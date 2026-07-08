'use client';

import React, { useState, useEffect } from 'react';
import { Terminal, Eye, Brain, PanelRightClose, PanelRight, Settings } from 'lucide-react';
import { TerminalLine, ObservationData, MemoryFact, PerformanceMetrics as PerformanceMetricsType, CompletionSuggestion } from '@/types';
import { TerminalPanel } from '@/components/panels/TerminalPanel';
import { ObservabilityTab } from '@/components/panels/ObservabilityTab';
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
  observation: ObservationData;
  memoryFacts: MemoryFact[];
  metrics: PerformanceMetricsType;
  /** SSE-driven lastMetrics for instant token display */
  lastMetrics?: PerformanceMetricsType | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** FIX 4: Force the terminal tab to be active when agent runs shell/code_exec */
  forceTerminalTab?: boolean;
  /** Called after the terminal tab has been shown */
  onTerminalTabShown?: () => void;
  width?: number;
  /** Called when settings change so the parent can refresh its model list */
  onModelsRefresh?: () => Promise<void>;
}

type RightTab = 'terminal' | 'observability' | 'memory' | 'actions';

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
  observation,
  memoryFacts,
  metrics,
  lastMetrics,
  collapsed,
  onToggleCollapse,
  forceTerminalTab,
  onTerminalTabShown,
  width = 320,
  onModelsRefresh,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<RightTab>('observability');
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
  }, [forceTerminalTab]);

  // v0.7: Auto-switch to Observe tab when a tool call fires
  // This ensures users see real-time action progress instead of
  // having to manually switch tabs.
  useEffect(() => {
    const handler = () => {
      if (activeTab !== 'observability') {
        setActiveTab('observability');
      }
    };
    window.addEventListener('localmind:tool-call-started', handler);
    return () => window.removeEventListener('localmind:tool-call-started', handler);
  }, [activeTab]);

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
    { id: 'observability', label: 'Observe', icon: <Eye className={iconSize} /> },
    { id: 'memory', label: 'Memory', icon: <Brain className={iconSize} /> },
  ];

  if (collapsed) {
    return (
      <div className="h-full bg-[#0a0f0a] border-l border-[#1a2a1a] flex flex-col items-center py-3 gap-3">
        <button
          onClick={() => setShowSettings(true)}
          className="p-1.5 rounded hover:bg-[#1a2a1a] text-[#8ab08a] hover:text-[#d4e8d4] transition-colors"
          title="Settings"
        >
          <Settings className="h-4 w-4" />
        </button>
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded hover:bg-[#1a2a1a] text-[#8ab08a] hover:text-[#d4e8d4] transition-colors"
          title="Expand panel"
        >
          <PanelRight className="h-4 w-4" />
        </button>
        <div className="w-px flex-1 bg-[#1a2a1a]" />
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => {
              setActiveTab(tab.id);
              onToggleCollapse();
            }}
            className="p-1.5 rounded hover:bg-[#1a2a1a] text-[#8ab08a] hover:text-[#d4e8d4] transition-colors"
            title={tab.label}
          >
            {tab.icon}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[#0a0f0a] border-l border-[#1a2a1a]">
      {/* Header */}
      <div className="flex items-center justify-center gap-2 px-2 py-2 border-b border-[#1a2a1a]">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center ${isCompact ? 'p-2.5' : 'gap-1 px-2 py-1'} rounded text-[10px] font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-[#1a2a1a] text-[#d4e8d4]'
                : 'text-[#8ab08a] hover:text-[#d4e8d4] hover:bg-[#1a2a1a]/50'
            }`}
            title={isCompact ? tab.label : undefined}
          >
            {tab.icon}
            {!isCompact && tab.label}
          </button>
        ))}
        <button
          onClick={() => setShowSettings(true)}
          className="p-2.5 rounded hover:bg-[#1a2a1a] text-[#8ab08a] hover:text-[#d4e8d4] transition-colors"
          title="Settings"
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={onToggleCollapse}
          className="p-2.5 rounded hover:bg-[#1a2a1a] text-[#8ab08a] hover:text-[#d4e8d4] transition-colors"
          title="Collapse panel"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
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
        {activeTab === 'observability' && <ObservabilityTab observation={observation} />}
        {activeTab === 'memory' && <MemoryTab facts={memoryFacts} />}
      </div>

      {/* Performance metrics */}
      <PerformanceMetrics metrics={metrics} lastMetrics={lastMetrics} />

      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} onSave={refreshModels} />
      )}
    </div>
  );
}
