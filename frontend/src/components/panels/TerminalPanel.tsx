'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { TerminalLine, TerminalTab, CompletionSuggestion, TerminalFilter } from '@/types';
import {
  Plus,
  X,
  Copy,
  Search,
  FolderOpen,
  RotateCcw,
  Maximize2,
  Minimize2,
} from 'lucide-react';

// ─── Color Map ─────────────────────────────────────────────────────────

const lineColors: Record<TerminalLine['type'], string> = {
  command: 'text-brand-green',
  output: 'text-brand-gh-text',
  error: 'text-brand-gh-red',
  info: 'text-brand-gh-amber',
  system: 'text-brand-gh-blue',
  success: 'text-brand-gh-green',
};

const linePrefixes: Record<TerminalLine['type'], string> = {
  command: '',
  output: '  ',
  error: '✗ ',
  info: 'ℹ ',
  system: '● ',
  success: '✓ ',
};

// ─── ANSI Stripping (for display safety) ───────────────────────────────

function stripAnsi(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/\x1b\[[0-9;]*m/g, '');
}

// ─── Props ─────────────────────────────────────────────────────────────

interface TerminalPanelProps {
  lines: TerminalLine[];
  onExecute?: (command: string, cwd?: string) => Promise<unknown>;
  onClear?: () => void;
  isRunning?: boolean;
  cwd?: string;
  sessionId?: string;
  onTabComplete?: (partial: string) => Promise<CompletionSuggestion[]>;
  history?: string[];
  onSessionChange?: (sessionId: string) => void;
  /** Called when the user clicks Cancel or presses Ctrl+C on a running command */
  onAbort?: () => void;
}

// ─── Component ─────────────────────────────────────────────────────────

export function TerminalPanel({
  lines,
  onExecute,
  onClear,
  isRunning,
  cwd = '~',
  sessionId: _sessionId = 'default',
  onTabComplete,
  history = [],
  onSessionChange,
  onAbort,
}: TerminalPanelProps) {
  // ── State ──
  const [input, setInput] = useState('');
  const [tabs, setTabs] = useState<TerminalTab[]>([
    { id: 'tab-1', label: 'bash', sessionId: 'default' },
  ]);
  const [activeTabId, setActiveTabId] = useState('tab-1');
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isMaximized, setIsMaximized] = useState(false);
  const [suggestions, setSuggestions] = useState<CompletionSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedSuggestion, setSelectedSuggestion] = useState(0);
  const [copiedLineId, setCopiedLineId] = useState<string | null>(null);
  const [commandHistoryIndex, setCommandHistoryIndex] = useState(-1);
  const [savedInput, setSavedInput] = useState('');
  const [lineFilter, setLineFilter] = useState<TerminalFilter>('all');
  const [terminalDims, setTerminalDims] = useState('80x24');

  // ── Refs ──
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const suggestionsRef = useRef<HTMLDivElement>(null);

  // Detect platform-appropriate shell name for the status bar
  const shellName = typeof navigator !== 'undefined' && navigator.platform?.includes('Win')
    ? 'powershell'
    : 'bash';

  // Compute terminal dimensions from the scroll container size
  useEffect(() => {
    const update = () => {
      if (!scrollRef.current) return;
      const cols = Math.max(1, Math.floor(scrollRef.current.clientWidth / 7.2));
      const rows = Math.max(1, Math.floor(scrollRef.current.clientHeight / 14));
      setTerminalDims(`${cols}x${rows}`);
    };
    update();
    const ro = new ResizeObserver(update);
    if (scrollRef.current) ro.observe(scrollRef.current);
    return () => ro.disconnect();
  }, []);

  // ── Auto-scroll ──
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines]);

  // ── Focus input on mount ──
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // FIX 6: Listen for 'localmind:run-code' events from ChatMessage code blocks.
  // When the user clicks "Run" on a code block, the code is dispatched
  // to the terminal for execution.
  //
  // FIX 7 (Windows compat): The heredoc syntax `<<'EOF'` is Unix-only and fails
  // on Windows CMD with "<< was unexpected at this time." On Windows we use
  // `python -c "..."` (with escaped quotes) instead. We detect the platform
  // from navigator.userAgent.
  useEffect(() => {
    const isWindows = /Windows/.test(navigator.userAgent);
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (!detail?.code) return;
      if (isRunning) return;
      if (!onExecute) return;
      setTimeout(() => { try {
        const { code, language } = detail;
        const lang = language?.toLowerCase() || '';
        if (['python', 'py'].includes(lang)) {
          if (isWindows) {
            // Windows: base64-encode to avoid \n-escaping issues that turn
            // multi-line code into a single line with literal \n chars.
            const b64 = btoa(unescape(encodeURIComponent(code)));
            onExecute(`python -c "import base64,sys;exec(base64.b64decode('${b64}').decode())"`);
          } else {
            onExecute(`python3 - <<'PYEOF'\n${code}\nPYEOF`);
          }
        } else if (['js', 'javascript', 'ts', 'typescript'].includes(lang)) {
          if (isWindows) {
            const b64 = btoa(unescape(encodeURIComponent(code)));
            onExecute(`node -e "const b=Buffer.from('${b64}','base64');eval(b.toString())"`);
          } else {
            onExecute(`node - <<'NODEEOF'\n${code}\nNODEEOF`);
          }
        } else if (['bash', 'sh', 'shell'].includes(lang)) {
          if (isWindows) {
            onExecute(code);
          } else {
            onExecute(`bash - <<'BASHEOF'\n${code}\nBASHEOF`);
          }
         } else {
           onExecute(code);
         }
       } catch (err) { console.error("[TerminalPanel] Execute error:", err); }
      }, 100); // End setTimeout
    };
    window.addEventListener('localmind:run-code', handler);
    return () => window.removeEventListener('localmind:run-code', handler);
  }, [onExecute, isRunning]);

  // ── Close suggestions on outside click ──
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // ── Tab completion ──
  const requestCompletion = useCallback(
    async (partial: string) => {
      if (onTabComplete && partial.trim()) {
        try {
          const results = await onTabComplete(partial);
          setSuggestions(results);
          setShowSuggestions(results.length > 0);
          setSelectedSuggestion(0);
        } catch {
          setSuggestions([]);
          setShowSuggestions(false);
        }
      }
    },
    [onTabComplete]
  );

  // ── Debounced completion ──
  const completionTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    if (completionTimerRef.current) clearTimeout(completionTimerRef.current);
    if (input.trim() && input.length > 1) {
      completionTimerRef.current = setTimeout(() => requestCompletion(input), 150);
    } else {
      setSuggestions([]);
      setShowSuggestions(false);
    }
    return () => {
      if (completionTimerRef.current) clearTimeout(completionTimerRef.current);
    };
  }, [input, requestCompletion]);

  // ── Command Submission ──
  const handleSubmit = useCallback(async () => {
    const cmd = input.trim();
    if (!cmd || isRunning) return;

    setInput('');
    setCommandHistoryIndex(-1);
    setSavedInput('');
    setShowSuggestions(false);
    await onExecute?.(cmd);
  }, [input, isRunning, onExecute]);

  // ── Copy Line ──
  const copyLine = useCallback(async (lineId: string, content: string) => {
    try {
      await navigator.clipboard.writeText(stripAnsi(content));
      setCopiedLineId(lineId);
      setTimeout(() => setCopiedLineId(null), 1500);
    } catch {
      // Fallback: no clipboard support
    }
  }, []);

  // ── Copy All Output ──
  const copyAll = useCallback(async () => {
    const text = lines
      .map((l) => stripAnsi(l.content))
      .join('\n');
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // no clipboard
    }
  }, [lines]);

  // ── Keyboard Handling ──
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Tab completion
      if (e.key === 'Tab') {
        e.preventDefault();
        if (showSuggestions && suggestions.length > 0) {
          const selected = suggestions[selectedSuggestion];
          setInput(selected.text);
          setShowSuggestions(false);
        }
        return;
      }

      // Suggestion navigation
      if (showSuggestions) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSelectedSuggestion((prev) => Math.min(prev + 1, suggestions.length - 1));
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSelectedSuggestion((prev) => Math.max(prev - 1, 0));
          return;
        }
        if (e.key === 'Escape') {
          setShowSuggestions(false);
          return;
        }
      }

      // Command history navigation (when suggestions are NOT showing)
      if (!showSuggestions) {
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (commandHistoryIndex === -1) {
            setSavedInput(input);
          }
          const newIndex = Math.min(commandHistoryIndex + 1, history.length - 1);
          if (newIndex >= 0 && history[history.length - 1 - newIndex]) {
            setCommandHistoryIndex(newIndex);
            setInput(history[history.length - 1 - newIndex]);
          }
          return;
        }
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (commandHistoryIndex > 0) {
            const newIndex = commandHistoryIndex - 1;
            setCommandHistoryIndex(newIndex);
            setInput(history[history.length - 1 - newIndex]);
          } else if (commandHistoryIndex === 0) {
            setCommandHistoryIndex(-1);
            setInput(savedInput);
          }
          return;
        }
      }

      // Ctrl+L to clear
      if (e.key === 'l' && e.ctrlKey) {
        e.preventDefault();
        onClear?.();
        return;
      }

      // Ctrl+C to cancel running command
      if (e.key === 'c' && e.ctrlKey && isRunning) {
        e.preventDefault();
        onAbort?.();
        return;
      }

      // Enter to submit
      if (e.key === 'Enter') {
        e.preventDefault();
        if (showSuggestions && suggestions.length > 0) {
          const selected = suggestions[selectedSuggestion];
          setInput(selected.text);
          setShowSuggestions(false);
        } else {
          handleSubmit();
        }
      }
    },
    [
      input,
      isRunning,
      showSuggestions,
      suggestions,
      selectedSuggestion,
      commandHistoryIndex,
      history,
      savedInput,
      onClear,
      handleSubmit,
      onAbort,
    ]
  );

  // ── Tab Management ──
  const addTab = useCallback(() => {
    const newId = `tab-${Date.now()}`;
    const newSessionId = `term-${Date.now()}`;
    setTabs((prev) => [...prev, { id: newId, label: `bash ${prev.length + 1}`, sessionId: newSessionId }]);
    setActiveTabId(newId);
    onSessionChange?.(newSessionId);
  }, [onSessionChange]);

  const removeTab = useCallback(
    (tabId: string) => {
      setTabs((prev) => {
        if (prev.length <= 1) return prev; // keep at least one tab
        const filtered = prev.filter((t) => t.id !== tabId);
        if (activeTabId === tabId) {
          const last = filtered[filtered.length - 1];
          setActiveTabId(last.id);
          onSessionChange?.(last.sessionId);
        }
        return filtered;
      });
    },
    [activeTabId, onSessionChange]
  );

  // ── Search + Source Filtering ──
  const filteredLines = lines
    .filter((l) => {
      if (lineFilter === 'user') return l.source !== 'agent';
      if (lineFilter === 'agent') return l.source === 'agent';
      return true;
    })
    .filter((l) => searchQuery ? stripAnsi(l.content).toLowerCase().includes(searchQuery.toLowerCase()) : true);

  const searchMatchCount = searchQuery ? filteredLines.length : 0;

  // ── Short CWD Display ──
  const shortCwd = cwd.replace(/^\/Users\/[^/]+/, '~').replace(/^\/home\/[^/]+/, '~');

  return (
    <div className={`font-mono text-[11px] leading-relaxed flex flex-col ${isMaximized ? 'fixed inset-0 z-50 bg-brand-bg-dark' : ''}`}>
      {/* ── Tab Bar ── */}
      <div className="flex items-center bg-brand-bg-panel-alt border-b border-brand-border">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            onClick={() => {
              setActiveTabId(tab.id);
              onSessionChange?.(tab.sessionId);
            }}
            className={`group flex items-center gap-1.5 px-3 py-1.5 cursor-pointer border-r border-brand-border text-[10px] transition-colors ${
              activeTabId === tab.id
                ? 'bg-brand-bg-dark text-brand-green-soft border-t-2 border-t-brand-green'
                : 'text-brand-green-muted hover:text-brand-green-soft hover:bg-brand-bg-dark/50 border-t-2 border-t-transparent'
            }`}
          >
            <span className="truncate max-w-[80px]">{tab.label}</span>
            {tabs.length > 1 && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  removeTab(tab.id);
                }}
                className="opacity-0 group-hover:opacity-100 hover:text-brand-gh-red transition-opacity"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            )}
          </div>
        ))}
        <button
          onClick={addTab}
          className="px-2 py-1.5 text-brand-green-muted hover:text-brand-green transition-colors"
          title="New terminal tab"
        >
          <Plus className="h-3 w-3" />
        </button>

        {/* ── Filter Tabs ── */}
        <div className="flex items-center gap-0.5 ml-2">
          {(['all', 'user', 'agent'] as TerminalFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setLineFilter(f)}
              className={`px-1.5 py-0.5 rounded text-[9px] transition-colors ${
                lineFilter === f
                  ? 'bg-brand-border text-brand-green-soft'
                  : 'text-brand-green-muted hover:text-brand-green-soft'
              }`}
            >
              {f === 'all' ? 'All' : f === 'user' ? 'Mine' : 'Agent'}
            </button>
          ))}
        </div>

        {/* Toolbar */}
        <div className="ml-auto flex items-center gap-0.5 pr-1.5">
          <button
            onClick={() => setShowSearch(!showSearch)}
            className={`p-1 rounded transition-colors ${
              showSearch ? 'text-brand-green bg-brand-border' : 'text-brand-green-muted hover:text-brand-green-soft'
            }`}
            title="Search (Ctrl+F)"
          >
            <Search className="h-3 w-3" />
          </button>
          <button
            onClick={copyAll}
            className="p-1 rounded text-brand-green-muted hover:text-brand-green-soft transition-colors"
            title="Copy all output"
          >
            <Copy className="h-3 w-3" />
          </button>
          <button
            onClick={onClear}
            className="p-1 rounded text-brand-green-muted hover:text-brand-green-soft transition-colors"
            title="Clear (Ctrl+L)"
          >
            <RotateCcw className="h-3 w-3" />
          </button>
          <button
            onClick={() => setIsMaximized(!isMaximized)}
            className="p-1 rounded text-brand-green-muted hover:text-brand-green-soft transition-colors"
            title={isMaximized ? 'Minimize' : 'Maximize'}
          >
            {isMaximized ? <Minimize2 className="h-3 w-3" /> : <Maximize2 className="h-3 w-3" />}
          </button>
        </div>
      </div>

      {/* ── Search Bar ── */}
      {showSearch && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-brand-bg-panel-alt border-b border-brand-border">
          <Search className="h-3 w-3 text-brand-green-muted shrink-0" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search output..."
            className="flex-1 bg-brand-bg-dark text-[11px] text-brand-green-soft placeholder:text-brand-green-muted outline-none border border-brand-border rounded px-2 py-0.5 focus:border-brand-green/50"
            autoFocus
          />
          {searchQuery && (
            <span className="text-[9px] text-brand-green-muted">
              {searchMatchCount} match{searchMatchCount !== 1 ? 'es' : ''}
            </span>
          )}
          <button
            onClick={() => {
              setShowSearch(false);
              setSearchQuery('');
            }}
            className="text-brand-green-muted hover:text-brand-green-soft"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* ── Terminal Header ── */}
      <div className="flex items-center gap-2 px-3 py-1 bg-brand-bg-dark border-b border-brand-border">
        <div className="flex gap-1">
          <div className="w-2 h-2 rounded-full bg-brand-gh-red" />
          <div className="w-2 h-2 rounded-full bg-brand-gh-amber" />
          <div className="w-2 h-2 rounded-full bg-brand-gh-green" />
        </div>
        <div className="flex items-center gap-1 text-[10px] text-brand-green-muted ml-1">
          <FolderOpen className="h-2.5 w-2.5" />
          <span className="truncate max-w-[150px]" title={cwd}>{shortCwd}</span>
        </div>
        {isRunning && (
          <div className="flex items-center gap-1 ml-auto">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand-green animate-pulse" />
            <span className="text-[9px] text-brand-green">running</span>
          </div>
        )}
      </div>

      {/* ── Terminal Output ── */}
      <div
        ref={scrollRef}
        className="flex-1 p-2 space-y-0 overflow-y-auto custom-scrollbar bg-brand-bg-dark min-h-0"
        style={{ maxHeight: isMaximized ? 'calc(100vh - 120px)' : '288px' }}
        onClick={() => inputRef.current?.focus()}
      >
        {filteredLines.length === 0 && !searchQuery && (
          <div className="space-y-2 py-3 px-1">
            <div className="text-[10px] text-brand-green-muted">
              Type a command and press Enter to execute...
            </div>
            <div className="text-[9px] text-brand-green-deleted space-y-0.5">
              <div><span className="text-brand-gh-blue">↑/↓</span> Navigate history</div>
              <div><span className="text-brand-gh-blue">Tab</span> Autocomplete</div>
              <div><span className="text-brand-gh-blue">Ctrl+L</span> Clear screen</div>
              <div><span className="text-brand-gh-blue">Ctrl+C</span> Cancel command</div>
            </div>
          </div>
        )}
        {filteredLines.map((line) => {
          const displayContent = stripAnsi(line.content);
          const isSearchMatch =
            searchQuery && displayContent.toLowerCase().includes(searchQuery.toLowerCase());

          return (
            <div
              key={line.id}
              className={`group flex items-start hover:bg-brand-bg-panel-alt rounded-sm transition-colors ${
                isSearchMatch ? 'bg-brand-border/50' : ''
              }`}
            >
              <span className="text-[9px] text-brand-green-deleted w-16 shrink-0 select-none pt-px">
                {line.timestamp}
              </span>
              {/* Tool badge for agent lines */}
              {line.source === 'agent' && line.toolName && (
                <span className="text-[8px] px-1 rounded bg-brand-border text-brand-gh-blue shrink-0 select-none mr-1">
                  {line.toolName}
                </span>
              )}
              <span className={`flex-1 break-all [overflow-wrap:anywhere] ${lineColors[line.type]}`}>
                {linePrefixes[line.type]}
                {line.source === 'agent' && (
                  <span className="text-brand-gh-purple mr-1">&#9883;</span>
                )}
                {isSearchMatch
                  ? highlightSearch(displayContent, searchQuery)
                  : displayContent}
              </span>
              {/* Copy button per line */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  copyLine(line.id, line.content);
                }}
                className="opacity-0 group-hover:opacity-100 ml-1 p-0.5 text-brand-green-deleted hover:text-brand-green-muted transition-opacity shrink-0"
                title="Copy line"
              >
                <Copy className="h-2.5 w-2.5" />
              </button>
              {/* Copied indicator */}
              {copiedLineId === line.id && (
                <span className="text-[8px] text-brand-gh-green ml-1 shrink-0">Copied!</span>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Autocomplete Suggestions ── */}
      {showSuggestions && suggestions.length > 0 && (
        <div
          ref={suggestionsRef}
          className="border-t border-brand-border bg-brand-bg-panel-alt max-h-32 overflow-y-auto"
        >
          {suggestions.map((s, i) => (
            <div
              key={`${s.text}-${i}`}
              onClick={() => {
                setInput(s.text);
                setShowSuggestions(false);
                inputRef.current?.focus();
              }}
              className={`flex items-center gap-2 px-3 py-1 cursor-pointer transition-colors ${
                i === selectedSuggestion
                  ? 'bg-brand-border text-brand-green-soft'
                  : 'text-brand-green-muted hover:bg-brand-border/50'
              }`}
            >
              <span className="text-[9px] px-1 rounded bg-brand-border text-brand-gh-blue shrink-0">
                {s.type === 'command' ? 'cmd' : s.type === 'path' ? 'dir' : 'file'}
              </span>
              <span className="truncate text-[11px]">{s.text}</span>
              {s.description && (
                <span className="ml-auto text-[9px] text-brand-green-deleted shrink-0">{s.description}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Command Input ── */}
      {onExecute && (
        <div className="flex items-center gap-1 px-2 py-1.5 bg-brand-bg-dark border-t border-brand-border">
          <span className="text-brand-green text-[11px] shrink-0">$</span>
          <div className="relative flex-1">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                setCommandHistoryIndex(-1);
              }}
              onKeyDown={handleKeyDown}
              placeholder={isRunning ? 'Running...' : 'Enter command... (↑ history, Tab autocomplete)'}
              disabled={isRunning}
              className="w-full bg-transparent text-[11px] text-brand-green-soft placeholder:text-brand-green-deleted outline-none font-mono caret-brand-green"
              spellCheck={false}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
            />
          </div>
          {isRunning && (
            <button
              onClick={() => onAbort?.()}
              className="px-1.5 py-0.5 text-[9px] text-brand-gh-red hover:bg-brand-border rounded transition-colors shrink-0"
              title="Cancel (Ctrl+C)"
            >
              Cancel
            </button>
          )}
        </div>
      )}

      {/* ── Status Bar ── */}
      <div className="flex items-center justify-between px-3 py-0.5 bg-brand-bg-panel-alt border-t border-brand-border">
        <div className="flex items-center gap-3 text-[9px] text-brand-green-deleted">
          <span>{shortCwd}</span>
          <span>{lines.length} lines</span>
          {history.length > 0 && <span>{history.length} cmds</span>}
          {lines.filter(l => l.source === 'agent').length > 0 && (
            <span className="text-brand-gh-purple">{lines.filter(l => l.source === 'agent').length} agent</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[9px] text-brand-green-deleted">
          <span>{shellName}</span>
          <span>{terminalDims}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ───────────────────────────────────────────────────────────

function highlightSearch(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;

  let index = lowerText.indexOf(lowerQuery);
  while (index !== -1) {
    if (index > lastIndex) {
      parts.push(text.slice(lastIndex, index));
    }
    parts.push(
      <mark key={index} className="bg-brand-gh-amber/30 text-brand-gh-amber rounded-sm px-px">
        {text.slice(index, index + query.length)}
      </mark>
    );
    lastIndex = index + query.length;
    index = lowerText.indexOf(lowerQuery, lastIndex);
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}
