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
  ChevronRight,
  ChevronDown,
} from 'lucide-react';
import { PackageInstaller } from './PackageInstaller';

// ─── Color Map ─────────────────────────────────────────────────────────
//
// Raw command output is deliberately DIMMED (brand-green-faint) so the eye
// scans the bright command headers first and reads output only when needed —
// the fix for the flat "everything is the same weight" hierarchy. Status
// colors each mean exactly ONE thing: amber = running, green = success,
// red = error, purple = agent. Blue is reserved for interactive affordances
// (copy, input focus) so interactivity is never mistaken for a status.

const lineColors: Record<TerminalLine['type'], string> = {
  command: 'text-brand-green-soft',
  output: 'text-brand-green-faint',
  error: 'text-brand-gh-red',
  info: 'text-brand-gh-amber',
  system: 'text-brand-green-muted',
  success: 'text-brand-gh-green',
};

// Keep the glyph set tiny and non-emoji: a red ✗, a green ✓, and a yellow !
// for warnings. Everything else leans on color + dimming, not a symbol —
// glyphs like ⓘ / ⚛ render as coloured emoji on some platforms and read as
// noise in a terminal.
const linePrefixes: Record<TerminalLine['type'], string> = {
  command: '',
  output: '',
  error: '✗ ',
  info: '! ',
  system: '',
  success: '✓ ',
};

// ─── Command block status ──────────────────────────────────────────────

type CmdStatus = 'running' | 'success' | 'error';

/** Honest per-command status: prefer the real exit code, then error output;
 *  never fabricate. A running command is only the last one while isRunning. */
function commandStatus(
  cmd: TerminalLine,
  children: TerminalLine[],
  isLastCommand: boolean,
  isRunning: boolean,
): CmdStatus {
  if (isLastCommand && isRunning) return 'running';
  if (typeof cmd.exitCode === 'number') return cmd.exitCode === 0 ? 'success' : 'error';
  if (children.some((c) => c.type === 'error')) return 'error';
  return 'success';
}

/** Format a real duration (ms). Returns '' when no duration was recorded —
 *  we show nothing rather than invent a number. */
function formatDuration(ms?: number): string {
  if (ms == null || !isFinite(ms) || ms < 0) return '';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  return `${s < 10 ? s.toFixed(1) : Math.round(s)}s`;
}

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
  // Collapsed command groups (by the command line's id): its following output
  // is hidden until re-expanded — the terminal equivalent of the Actions rows.
  const [collapsedCmds, setCollapsedCmds] = useState<Set<string>>(() => new Set());

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
  // Also re-scroll when execution starts so the live "executing…" cursor is
  // visible immediately, before the first output line lands.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, isRunning]);

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

  // Group lines into command BLOCKS: each command owns the output lines that
  // follow it until the next command. Output that precedes any command (agent
  // tool output, standalone system lines) collects into a "loose" block. One
  // header per command replaces the old one-timestamp-per-line repetition.
  type CmdBlock = { kind: 'command'; cmd: TerminalLine; children: TerminalLine[] };
  type LooseBlock = { kind: 'loose'; lines: TerminalLine[] };
  type TermBlock = CmdBlock | LooseBlock;

  const blocks: TermBlock[] = [];
  {
    let cur: CmdBlock | null = null;
    let loose: TerminalLine[] = [];
    const flushLoose = () => {
      if (loose.length) {
        blocks.push({ kind: 'loose', lines: loose });
        loose = [];
      }
    };
    for (const l of filteredLines) {
      if (l.type === 'command') {
        flushLoose();
        cur = { kind: 'command', cmd: l, children: [] };
        blocks.push(cur);
      } else if (cur) {
        cur.children.push(l);
      } else {
        loose.push(l);
      }
    }
    flushLoose();
  }

  // A live search reveals everything (a match may sit inside a collapsed group).
  const forceExpand = !!searchQuery;

  const renderContent = (content: string) =>
    searchQuery && content.toLowerCase().includes(searchQuery.toLowerCase())
      ? highlightSearch(content, searchQuery)
      : content;

  // ── Short CWD Display ──
  const shortCwd = cwd.replace(/^\/Users\/[^/]+/, '~').replace(/^\/home\/[^/]+/, '~');

  return (
    <div className={`font-mono text-[12px] leading-relaxed flex flex-col ${isMaximized ? 'fixed inset-0 z-50 bg-brand-bg-dark' : ''}`}>
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
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand-gh-amber animate-pulse" />
            <span className="text-[9px] text-brand-gh-amber">running</span>
          </div>
        )}
      </div>

      {/* ── Package Installer ── */}
      {onExecute && (
        <PackageInstaller onExecute={(cmd) => onExecute(cmd, cwd)} isRunning={isRunning} />
      )}

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
        {(() => {
          // The last command in the stream is the only one that can be "running".
          let lastCommandId: string | null = null;
          for (const b of blocks) if (b.kind === 'command') lastCommandId = b.cmd.id;

          // A single dimmed output row (used inside command blocks and loose
          // blocks). No per-row timestamp — the block header carries the time.
          const outputRow = (line: TerminalLine) => {
            const displayContent = stripAnsi(line.content);
            const isMatch =
              searchQuery && displayContent.toLowerCase().includes(searchQuery.toLowerCase());
            return (
              <div
                key={line.id}
                className={`group flex items-start gap-1.5 px-1 rounded-sm hover:bg-brand-bg-panel-alt transition-colors ${
                  isMatch ? 'bg-brand-border/50' : ''
                }`}
              >
                {line.source === 'agent' && (
                  <span className="mt-[5px] w-1 h-1 rounded-full bg-brand-gh-purple shrink-0" title="agent" />
                )}
                {line.source === 'agent' && line.toolName && (
                  <span className="text-[8px] px-1 rounded bg-brand-border text-brand-green-muted shrink-0 select-none mt-px">
                    {line.toolName}
                  </span>
                )}
                <span className={`flex-1 min-w-0 break-all [overflow-wrap:anywhere] ${lineColors[line.type]}`}>
                  {linePrefixes[line.type]}
                  {renderContent(displayContent)}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    copyLine(line.id, line.content);
                  }}
                  className="opacity-0 group-hover:opacity-100 ml-1 p-0.5 text-brand-green-deleted hover:text-brand-gh-blue transition-all shrink-0"
                  title="Copy line"
                >
                  <Copy className="h-2.5 w-2.5" />
                </button>
                {copiedLineId === line.id && (
                  <span className="text-[8px] text-brand-gh-green ml-1 shrink-0">Copied!</span>
                )}
              </div>
            );
          };

          return blocks.map((block) => {
            // Loose output (agent tool output or system lines with no owning
            // command) renders as a plain dimmed group.
            if (block.kind === 'loose') {
              return (
                <div key={`loose-${block.lines[0].id}`} className="py-0.5">
                  {block.lines.map(outputRow)}
                </div>
              );
            }

            // Command block: one bright header (status dot · time · ❯ command ·
            // duration · collapse · copy) with its output dimmed underneath.
            const { cmd, children } = block;
            const status = commandStatus(cmd, children, cmd.id === lastCommandId, !!isRunning);
            const collapsed = !forceExpand && collapsedCmds.has(cmd.id);
            const childCount = children.length;
            const dur = formatDuration(cmd.duration);
            const displayCmd = stripAnsi(cmd.content);
            const isMatch =
              searchQuery && displayCmd.toLowerCase().includes(searchQuery.toLowerCase());

            const dotClass =
              status === 'running'
                ? 'bg-brand-gh-amber shadow-[0_0_0_3px] shadow-brand-gh-amber/20 animate-pulse'
                : status === 'error'
                ? 'bg-brand-gh-red'
                : 'bg-brand-gh-green';
            const metaClass =
              status === 'running'
                ? 'text-brand-gh-amber'
                : status === 'error'
                ? 'text-brand-gh-red'
                : 'text-brand-green-faint';
            const metaText =
              status === 'running' ? 'running' : dur || (status === 'error' ? 'error' : '');

            return (
              <div key={cmd.id} className="mb-0.5">
                <div
                  className={`group flex items-center gap-2 px-1 py-0.5 rounded-sm hover:bg-brand-bg-panel-alt transition-colors ${
                    isMatch ? 'bg-brand-border/50' : ''
                  }`}
                >
                  <span className={`w-[7px] h-[7px] rounded-full shrink-0 ${dotClass}`} />
                  <span className="text-[9px] text-brand-green-deleted shrink-0 select-none tabular-nums">
                    {cmd.timestamp}
                  </span>
                  {cmd.source === 'agent' && (
                    <span className="w-1 h-1 rounded-full bg-brand-gh-purple shrink-0" title="agent" />
                  )}
                  {cmd.source === 'agent' && cmd.toolName && (
                    <span className="text-[8px] px-1 rounded bg-brand-border text-brand-green-muted shrink-0 select-none">
                      {cmd.toolName}
                    </span>
                  )}
                  <span className="text-brand-green shrink-0 select-none">❯</span>
                  <span className="flex-1 min-w-0 truncate text-brand-green-soft" title={displayCmd}>
                    {renderContent(displayCmd)}
                  </span>
                  {metaText && (
                    <span className={`text-[10px] shrink-0 tabular-nums ${metaClass}`}>{metaText}</span>
                  )}
                  {childCount > 0 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setCollapsedCmds((prev) => {
                          const next = new Set(prev);
                          if (next.has(cmd.id)) next.delete(cmd.id);
                          else next.add(cmd.id);
                          return next;
                        });
                      }}
                      className="flex items-center gap-1 text-brand-green-faint hover:text-brand-green-muted transition-colors shrink-0"
                      title={collapsed ? 'Expand output' : 'Collapse output'}
                      aria-expanded={!collapsed}
                    >
                      <span className="text-[9px] tabular-nums">{childCount}</span>
                      {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    </button>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      copyLine(cmd.id, cmd.content);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 text-brand-green-deleted hover:text-brand-gh-blue transition-all shrink-0"
                    title="Copy line"
                  >
                    <Copy className="h-2.5 w-2.5" />
                  </button>
                  {copiedLineId === cmd.id && (
                    <span className="text-[8px] text-brand-gh-green shrink-0">Copied!</span>
                  )}
                </div>
                {!collapsed && childCount > 0 && (
                  <div className="ml-[7px] pl-3 border-l border-brand-border/50">
                    {children.map(outputRow)}
                  </div>
                )}
              </div>
            );
          });
        })()}
        {/* Live execution cursor — a blinking block + "executing…" while a
            command runs, so the panel shows the shell working in realtime
            even before the first output line lands. */}
        {isRunning && (
          <div className="flex items-center gap-1.5 px-1 pt-1" data-testid="terminal-executing">
            <span className="terminal-cursor inline-block w-[7px] h-[13px] bg-brand-gh-amber align-middle" />
            <span className="text-[10px] text-brand-gh-amber">executing…</span>
          </div>
        )}
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
      {/* The focus ring is BLUE (the interactive accent), never green — so an
          active prompt is never confused with a green "success" above it. */}
      {onExecute && (
        <div className="px-2 py-1.5 bg-brand-bg-dark border-t border-brand-border">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-brand-bg-panel-alt border border-brand-border focus-within:border-brand-gh-blue/70 focus-within:ring-2 focus-within:ring-brand-gh-blue/15 transition-colors">
            <span className="text-brand-gh-blue text-[13px] shrink-0">❯</span>
            <div className="relative flex-1">
              {/* Idle prompt cursor — a blinking block at the start of an empty
                  prompt so the terminal looks live and ready to type. Hidden
                  once the user types (the native caret takes over) or while a
                  command is running. */}
              {!isRunning && input === '' && (
                <span className="terminal-cursor pointer-events-none absolute left-0 top-1/2 h-[12px] w-[6px] -translate-y-1/2 bg-brand-gh-blue/70" />
              )}
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  setCommandHistoryIndex(-1);
                }}
                onKeyDown={handleKeyDown}
                placeholder={isRunning ? 'Running...' : 'Enter command… (↑ history · Tab autocomplete)'}
                disabled={isRunning}
                className="w-full bg-transparent text-[12px] text-brand-green-soft placeholder:text-brand-green-faint outline-none font-mono caret-brand-gh-blue"
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
