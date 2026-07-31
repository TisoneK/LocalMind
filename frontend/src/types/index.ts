export type MessageRole = 'user' | 'assistant';
export type ToolStatus = 'running' | 'started' | 'in_progress' | 'done' | 'failed' | 'pending';
export type IntentType = 'code' | 'file' | 'chat' | 'search' | 'shell' | 'memory';

export interface ToolCall {
  id: string;
  name: string;
  label?: string;
  status: ToolStatus;
  input: string;
  output?: string;
  duration?: number;
  /** Timestamp when this tool call was first observed (HH:MM format) */
  timestamp?: string;
}

export interface ThinkingStep {
  id: string;
  content: string;
  collapsed: boolean;
}

export interface PendingWrite {
  path: string;
  content: string;
  filename: string;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  toolCalls?: ToolCall[];
  thinkingBlock?: ThinkingStep;
  thinking?: string;
  thinkMs?: number;
  isAgent?: boolean;
  codeBlocks?: CodeBlock[];
  fileResults?: FileResult[];
  pendingWrite?: PendingWrite;
  /** Structured diff data from edit_file tool results */
  diffData?: DiffData;
  /** Session 30: system status feedback — reflects real pipeline stage
   * (e.g., "Let me search the web...", "Understanding your request...").
   * Distinct from `thinking` which is the model's actual reasoning trace. */
  statusText?: string;
}

/** Structured diff data for rendering DiffBlock in chat messages */
export interface DiffData {
  hunks: DiffHunk[];
  language?: string;
  filePath?: string;
  additions?: number;
  deletions?: number;
}

/** A single diff hunk from the backend's edit_file tool */
export interface DiffHunk {
  filePath: string;
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: DiffLine[];
}

/** A single line in a diff hunk */
export interface DiffLine {
  type: 'context' | 'added' | 'removed' | 'hunk_header';
  content: string;
  oldLine?: number;
  newLine?: number;
}

export interface CodeBlock {
  id: string;
  language: string;
  code: string;
  filename?: string;
}

export interface FileResult {
  id: string;
  filename: string;
  path: string;
  status: 'created' | 'modified' | 'deleted';
  lines?: number;
}

export interface Session {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: string;
  messageCount: number;
  active: boolean;
  /** Human-readable date from the backend (e.g. "14:30" or "Jan 05") */
  formattedDate?: string;
}

export interface ActionItem {
  id: string;
  type: 'file_write' | 'file_read' | 'file_task' | 'grep' | 'code_exec' | 'shell' | 'memory_op' | 'web_search' | 'sysinfo';
  label: string;
  detail: string;
  status: ToolStatus;
  timestamp: string;
  duration?: number;
}

export interface TodoItem {
  id: string;
  /** Canonical UI label. The backend calls this field `content`. */
  text: string;
  completed: boolean;
  status?: ToolStatus;
  order?: number;
  sessionId?: string;
  subtasks?: TodoItem[];
}

export interface FileNode {
  name: string;
  type: 'file' | 'folder';
  path: string;
  children?: FileNode[];
  expanded?: boolean;
}

// ─── Terminal Types ────────────────────────────────────────────────────

export type TerminalLineType = 'command' | 'output' | 'error' | 'info' | 'system' | 'success';

export interface TerminalSession {
  sessionId: string;
  cwd: string;
  historyCount: number;
  envCount: number;
}

export interface TerminalTab {
  id: string;
  label: string;
  sessionId: string;
}

export interface CompletionSuggestion {
  text: string;
  type: 'command' | 'path' | 'file';
  description?: string;
}

// ─── Tool-Terminal Bridge Types ──────────────────────────────────────

/** Source of a terminal command or tool execution */
export type TerminalEventSource = 'user' | 'agent';

/** Tool badge type for terminal line display */
export type ToolBadgeType = 'shell' | 'code' | 'file' | 'edit' | 'search' | 'memory' | 'system' | 'terminal';

/** Extended terminal line with tool-terminal bridge fields */
export interface TerminalLine {
  id: string;
  type: TerminalLineType;
  content: string;
  timestamp: string;
  /** Optional ANSI style codes for colored output */
  ansiStyle?: string;
  /** Duration in ms for command lines */
  duration?: number;
  /** Exit code for command result lines */
  exitCode?: number;
  /** Source: 'user' for manual commands, 'agent' for AI-initiated */
  source?: TerminalEventSource;
  /** Tool name badge (e.g., 'shell', 'code', 'file', 'search') */
  toolName?: string;
  /** Human-readable label for the tool action */
  toolLabel?: string;
}

/** Tool execution event from the SSE stream */
export interface ToolExecutionEvent {
  tool: string;
  command: string;
  output: string;
  success: boolean;
  latencyMs: number;
  label?: string;
  toolArgs?: string;
}

/** Tool execution log entry from the terminal session */
export interface ToolExecutionLogEntry {
  tool: string;
  command: string;
  source: TerminalEventSource;
  exitCode: number;
  duration: number;
  success: boolean;
  timestamp: number;
}

/** Filter for terminal line display */
export type TerminalFilter = 'all' | 'user' | 'agent';

// ─── Other Types ───────────────────────────────────────────────────────

export interface ObservationData {
  intent: IntentType;
  confidence: number;
  toolsUsed: string[];
  memoryHits: number;
  contextTokens: number;
  latency: number;
}

export interface MemoryFact {
  id: string;
  content: string;
  source: string;
  relevance: number;
  timestamp: string;
}

export interface PerformanceMetrics {
  tokensPerSecond: number;
  latency: number;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
}

export interface ModelOption {
  id: string;
  name: string;
  provider: string;
  size?: string;
}
