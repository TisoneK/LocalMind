/**
 * Auto-switch between Terminal / Agents / Memory tabs on
 * activity — with the unconditional-flag-consume fix (forceChatTab pattern).
 *
 * The key regression: a force flag must be consumed EVEN when the user is
 * already on the target tab, so a later event (another force flag, a tool
 * event) can't re-fire it and yank the panel away from the user's choice.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { RightPanel } from './RightPanel';

// RightPanel is heavy (TerminalPanel, AgentWorkspace, MemoryTab, SettingsModal);
// the force-flag effects are what we're testing, so stub the tab content by
// mocking the panel components to lightweight divs.
vi.mock('@/components/panels/TerminalPanel', () => ({
  TerminalPanel: () => <div data-testid="terminal-panel" />,
}));
vi.mock('@/components/panels/AgentWorkspace', () => ({
  AgentWorkspace: () => <div data-testid="agents-panel" />,
}));
vi.mock('@/components/panels/MemoryTab', () => ({
  MemoryTab: () => <div data-testid="memory-panel" />,
}));
vi.mock('@/components/panels/PerformanceMetrics', () => ({
  PerformanceMetrics: () => <div data-testid="metrics" />,
}));
vi.mock('@/components/shared/SettingsModal', () => ({
  SettingsModal: () => <div data-testid="settings" />,
}));

const baseProps = {
  terminalLines: [],
  isTerminalRunning: false,
  onTerminalExecute: vi.fn(),
  onTerminalClear: vi.fn(),
  memoryFacts: [],
  metrics: { tokensPerSecond: 0, latency: 0, totalTokens: 0, promptTokens: 0, completionTokens: 0 },
  collapsed: false,
  onToggleCollapse: vi.fn(),
};

function renderPanel(over: Partial<React.ComponentProps<typeof RightPanel>> = {}) {
  return render(<RightPanel {...baseProps} {...over} />);
}

describe('RightPanel force-tab switching', () => {
  it('switches to the Terminal tab on forceTerminalTab and consumes the flag', () => {
    const shown = vi.fn();
    const { rerender } = renderPanel({ forceTerminalTab: true, onTerminalTabShown: shown });
    expect(screen.getByTestId('terminal-panel')).toBeInTheDocument();
    expect(shown).toHaveBeenCalledTimes(1);
    // Rerender with the flag consumed by the parent: no re-fire.
    rerender(<RightPanel {...baseProps} forceTerminalTab={false} onTerminalTabShown={shown} />);
    expect(shown).toHaveBeenCalledTimes(1);
  });

  it('switches to the Memory tab on forceMemoryTab', () => {
    const shown = vi.fn();
    renderPanel({ forceMemoryTab: true, onMemoryTabShown: shown });
    expect(screen.getByTestId('memory-panel')).toBeInTheDocument();
    expect(shown).toHaveBeenCalledTimes(1);
  });

  it('switches to the Agents tab on forceAgentsTab', () => {
    const shown = vi.fn();
    renderPanel({ forceAgentsTab: true, onAgentsTabShown: shown });
    expect(screen.getByTestId('agents-panel')).toBeInTheDocument();
    expect(shown).toHaveBeenCalledTimes(1);
  });

  it('consumes the flag even when already on the target tab (no later fight)', () => {
    // Start on Memory (default is agents; click Memory), then fire
    // forceMemoryTab while already there. The consumed ref must still reset
    // (flag cleared) so a subsequent forceTerminalTab isn't blocked, and the
    // later flag wins without being yanked back.
    const memoryShown = vi.fn();
    const terminalShown = vi.fn();
    const { rerender } = renderPanel({ onMemoryTabShown: memoryShown, onTerminalTabShown: terminalShown });
    fireEvent.click(screen.getByText('Memory'));
    expect(screen.getByTestId('memory-panel')).toBeInTheDocument();

    // Force Memory while already on Memory — must consume (call shown) so the
    // flag is gone, not left set.
    rerender(<RightPanel {...baseProps} forceMemoryTab onMemoryTabShown={memoryShown} onTerminalTabShown={terminalShown} />);
    expect(memoryShown).toHaveBeenCalledTimes(1);

    // A later terminal event must win and stay.
    rerender(<RightPanel {...baseProps} forceMemoryTab={false} forceTerminalTab onMemoryTabShown={memoryShown} onTerminalTabShown={terminalShown} />);
    expect(terminalShown).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('terminal-panel')).toBeInTheDocument();
    // And nothing yanks back to Memory afterwards.
    rerender(<RightPanel {...baseProps} forceTerminalTab={false} onMemoryTabShown={memoryShown} onTerminalTabShown={terminalShown} />);
    expect(screen.getByTestId('terminal-panel')).toBeInTheDocument();
    expect(memoryShown).toHaveBeenCalledTimes(1);
  });

  it('does not switch when no force flag is set', () => {
    renderPanel();
    // Default tab is agents.
    expect(screen.getByTestId('agents-panel')).toBeInTheDocument();
  });
});
