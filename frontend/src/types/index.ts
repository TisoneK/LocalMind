export type MessageRole = 'user' | 'assistant';
export type ToolStatus = 'running' | 'started' | 'in_progress' | 'done' | 'failed' | 'pending';
export type IntentType = 'code' | 'file' | 'chat' | 'search' | 'shell' | 'memory';

// Response Block System — structured output from Presentation Intelligence.
import type { ResponseBlock as _ResponseBlock } from './response-blocks';
export type ResponseBlock = _ResponseBlock;

export interface ToolCall {
  id: string;
  name: string;
  /** Name of the delegated child agent when this is child progress. */
  agent?: string;
  /** Parent/child run identifier when supplied by the runtime. */
  runId?: string;
  label?: string;
  status: ToolStatus;
  input: string;
  output?: string;
  error?: string;
  duration?: number;
  /** Agent loop step number — used to chain actions into a sequence. */
  iteration?: number;
  /** Plan todo this tool call serves (one todo → many actions). */
  todoId?: string;
  /** The model's reasoning that led to this tool call . */
  reasoning?: string;
  /** Which backend engine answered (e.g. web_search's winning provider —
   *  Rendered as a badge on the Actions card. */
  provider?: string;
  /** Timestamp when this tool call was first observed (HH:MM format) */
  timestamp?: string;
}

export interface ThinkingStep {
  id: string;
  content: string;
  collapsed: boolean;
}

/** One visible parent or delegated child execution in the agent workspace. */
export type AgentRunStatus = 'running' | 'completed' | 'failed' | 'timed_out' | 'canceled';

/** Bounded evidence entry handed to the parent model. */
export interface EvidenceEntry {
  tool: string;
  iteration: number;
  evidenceChars: number;
  failed: boolean;
  /** Wall-clock timestamp (ms) when the evidence was emitted. */
  timestamp: number;
}

export interface AgentRun {
  id: string;
  name: string;
  role: 'parent' | 'child' | 'parallel';
  parentId?: string;
  task?: string;
  /** Action-oriented turn heading ("Fetch Weather") produced by the parent's
   *  classify call and used instead of a bare "Turn N". Absent until the
   *  classify result streams in, or when the model omitted it. */
  title?: string;
  status: AgentRunStatus;
  depth: number;
  startedAt: number;
  completedAt?: number;
  error?: string;
  tools: ToolCall[];
  /** Evidence entries handed to the parent model after each tool. */
  evidence?: EvidenceEntry[];
  /** Active-agent lifecycle narration (bootup-telemetry session): the
   *  initialization / planning / thinker / loop phases fired by this run,
   *  rendered inside the run node on the Agents tab. Populated live from
   *  obs events and persisted server-side with the run tree. */
  phases?: AgentPhase[];
}

export interface PendingWrite {
  path: string;
  content: string;
  filename: string;
}

/** Canonical model/provider error. The backend's SSE error event
 *  carries this object instead of a raw provider payload; the ErrorMessage
 *  card renders it. `raw` is the original provider response, kept for the
 *  collapsed developer details — never rendered as chat content. */
export interface ModelError {
  status: 'error';
  /** 'model_provider' — a provider/API failure; 'internal' — LocalMind-side. */
  source: 'model_provider' | 'internal';
  /** Provider name (zen, ollama, openai, ...) when detectable. */
  provider?: string | null;
  /** Canonical classification: rate_limit | auth_error | payment_required |
   *  model_not_found | context_overflow | timeout | server_error |
   *  network_error | error */
  code: string;
  /** Human-friendly, provider-agnostic explanation. */
  message: string;
  /** Whether retrying is likely to help — drives the Try again action. */
  retryable: boolean;
  /** Original provider/adapter error — debug surface only. */
  raw?: string | unknown;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  /** Raw epoch seconds from the store, preserved for the v3 chat export and
   *  real dates. The display `timestamp` is reduced to HH:MM and must not be
   *  re-parsed — always prefer this field when an absolute time is needed. */
  timestampEpoch?: number;
  /** Canonical error object when this reply failed — rendered as a
   *  friendly card (never the raw provider payload). Mutually exclusive with
   *  normal content (error replies stream no tokens). */
  error?: ModelError;
  toolCalls?: ToolCall[];
  thinkingBlock?: ThinkingStep;
  thinking?: string;
  thinkMs?: number;
  /** The reasoning, one entry per phase (before each round of tools), so it can be shown where it happened. */
  thinkingSegments?: { text: string; ms: number; afterTools: number }[];
  /** Wall time spent streaming the final answer (first→last token), for the
   *  Turn Anatomy strip. Distinct from thinkMs (reasoning) and tool durations. */
  answerMs?: number;
  isAgent?: boolean;
  /** The Agent's opening acknowledgement, streamed during parent
   *  initialization. Belongs in chat as the first line of the reply —
   *  distinct from `content` (the final answer that follows tool work). */
  acknowledgement?: string;
  codeBlocks?: CodeBlock[];
  fileResults?: FileResult[];
  pendingWrite?: PendingWrite;
  /** Chat mode asked to switch to Agent for an action.
   *  Carries the original user message so Accept can resend it as an agent turn. */
  switchToAgent?: { message: string };
  /** Structured diff data from edit_file tool results */
  diffData?: DiffData;
  /** System status feedback — reflects real pipeline stage
   * (e.g., "Let me search the web...", "Understanding your request...").
   * Distinct from `thinking` which is the model's actual reasoning trace. */
  statusText?: string;
  /** Per-message performance metadata, attached
   * when the turn completes. Optional — messages without it render as before.
   * Latency/tokens are per-TURN, not session-global. */
  performance?: {
    latencyMs?: number;
    promptTokens?: number;
    completionTokens?: number;
    tokensPerSecond?: number;
    /** Provider-reported cache-hit input tokens for this turn (0/absent when
     *  the provider doesn't report caching). */
    cachedTokens?: number;
    /** LLM calls that reported usage this turn. */
    llmCalls?: number;
    /** Which model + provider answered this turn (persisted with the reply;
     *  a chat may switch models mid-way, so identity is per turn). */
    model?: string;
    provider?: string;
  };
  /** Best-of-N editor candidates, rendered
   * as an expandable section in the message. Populated from the tool result
   *  metadata when the backend sends a best_of_n_edit tool result. */
  candidates?: BestOfNCandidate[];
  /** Frontend Phase Visibility. Agentic phase entries
   *  surfaced from the backend's now-live obs events:
   *  agent_loop_gate_passed, agent_loop_gate_failed_replan,
   *  orchestrator_replan_start/_done/_failed, agent_loop_failure,
   *  plan_nodes_created, plan_node_advanced. Rendered as a phase strip
   *  above the tool cards so the user can see "I am verifying /
   *  replanning / switching to a different approach" — the literal
   *  difference between a chat-with-tools and an agent. */
  agentPhases?: AgentPhase[];
  /** Structured response blocks from the Presentation Intelligence
   *  layer. When present, the frontend renders these natively (tables, charts,
   *  diagrams, metrics) instead of forcing everything through Markdown.
   *  The agent decides WHAT to show; the UI decides HOW it looks. */
  responseBlocks?: ResponseBlock[];
  /** The Agent Workspace run tree for this turn (rebuilt
   *  server-side from obs events and persisted with the message). The Agents
   *  tab restores the last turn's tree from here on reload. */
  agentRuns?: AgentRun[];
  /** Set on the synthetic user bubble that marks a goal-round boundary in a
   *  live deep dive. Absent on ordinary user messages. */
  goalRound?: GoalRound;
}

/** One goal-round boundary inside the open turn. */
export interface GoalRound {
  round: number;
  maxRounds: number;
  objective: string;
}

/** The chat's durable goal: one objective this session keeps working across
 *  turns until it completes, blocks, or is paused/cleared. `armed` is
 *  process-local — a restarted backend comes back disarmed until the goal is
 *  explicitly resumed, so reloading the chat never restarts autonomous work. */
export type GoalPhase = 'active' | 'paused' | 'blocked' | 'complete';

export interface GoalState {
  id: string;
  objective: string;
  phase: GoalPhase;
  revision: number;
  roundsStarted: number;
  maxGoalRounds: number;
  blockedReason?: string | null;
  armed: boolean;
}

/** Frontend Phase Visibility.
 *  A single entry in the agent phase strip. Each entry corresponds to
 *  one backend obs event (gate pass/fail, orchestrator replan,
 *  plan node advance, etc.). The strip renders in order so the user
 *  sees the agent's decision history for this turn. */
export interface AgentPhase {
  /** Stable unique id within the message (used as React key). */
  id: string;
  /** Canonical phase type — drives the icon + label. */
  type:
    | 'initializing'       // agent_initialization_start — parent init began
    | 'understanding'      // agent_initialization_understanding — thinker line (workspace)
    | 'acknowledged'       // agent_initialization_ack — opening acknowledgement (workspace)
    | 'initialized'        // agent_initialization_done — mode decided (execute/direct/clarify)
    | 'planned'            // agent_planning_done — plan produced
    | 'thinking'           // agent_thinker_start — thinking through evidence (workspace)
    | 'thinking_done'      // agent_thinker_done — analysis ready (workspace)
    | 'working'            // agent_loop_start — execute loop began
    | 'turn_done'          // agent_loop_done — loop finished (direct/clarify/iterations/hit_limit)
    | 'plan_created'        // plan_nodes_created — structured DAG built
    | 'node_advanced'       // plan_node_advanced — a node transitioned state
    | 'gate_passed'         // agent_loop_gate_passed — criteria verified ✓
    | 'gate_failed_replan'  // agent_loop_gate_failed_replan — criteria unmet, replanning
    | 'orchestrator_replan_start'  // orchestrator notified of failure
    | 'orchestrator_replan_done'   // orchestrator produced a new plan
    | 'orchestrator_replan_failed' // orchestrator.replan() raised (non-fatal)
    | 'agent_loop_failure';  // agent_loop_failure — empty stream / iter cap / criteria unmet at cap
  /** Human-readable label (e.g., "Verified: file exists at /tmp/foo"). */
  label: string;
  /** Optional detail string — the unmet criteria list, the failed tool,
   *  the new plan summary, etc. Rendered as a sub-line. */
  detail?: string;
  /** ISO timestamp or ms since epoch — when the phase fired. */
  timestamp: number;
  /** Iteration the phase fired at (1-indexed). Optional — some phases
   *  (plan_created) fire before iteration 1. */
  iteration?: number;
  /** How many consecutive identical phases this entry collapses.
   *  Undefined/1 = a single occurrence; >1 renders as a "×N" run count so the
   *  lifecycle shows one line instead of the same phase repeated per iteration. */
  count?: number;
}

/** A single candidate in a best-of-N edit result. */
export interface BestOfNCandidate {
  index: number;
  strategy: string;
  rationale: string;
  isWinner: boolean;
}

/** Structured diff data for rendering DiffBlock in chat messages */
export interface DiffData {
  hunks: DiffHunk[];
  language?: string;
  filePath?: string;
  additions?: number;
  deletions?: number;
  /** Set when the write can be undone (see /api/files/undo). */
  undoId?: string;
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
  /** Live SSE shape: the file's base name. */
  filename: string;
  path: string;
  status: 'created' | 'modified' | 'deleted';
  lines?: number;
  /** Restored-history shape (backend GET /history sends name/size/type). */
  name?: string;
  size?: number;
  type?: string;
}

export interface FileContent {
  path: string;
  name: string;
  extension: string;
  size: number;
  truncated: boolean;
  /** Text preview for text/code/office files (docx/pdf/xlsx parsed server-side). */
  text?: string;
  /** Inline data URL for image files. */
  image_data_url?: string;
  /** Whether the file is a plain text/code file safe to edit in place (office
   *  docs are parsed text only and must not be written back). */
  editable?: boolean;
  /** Structured per-sheet rows for CSV/XLSX previews (rows[0] is the header). */
  sheets?: SpreadsheetSheet[];
}

export interface SpreadsheetSheet {
  name: string;
  rows: string[][];
  /** True when rows/columns were capped server-side. */
  truncated?: boolean;
}

export interface Session {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: string;
  messageCount: number;
  active: boolean;
  /** This session's artifact folder (files deleted with the chat). */
  workspacePath?: string;
  /** Human-readable date from the backend (e.g. "14:30" or "Jan 05") */
  formattedDate?: string;
  /** Raw epoch seconds (v3 export + real dates): the list endpoint's merged
   *  timestamp (last_active ?? created_at), plus the explicit bounds. */
  timestampEpoch?: number;
  createdAtEpoch?: number;
  lastActiveEpoch?: number;
}

export interface ActionItem {
  id: string;
  type: 'file_write' | 'file_read' | 'file_task' | 'grep' | 'code_exec' | 'shell' | 'memory_op' | 'web_search' | 'sysinfo';
  label: string;
  detail: string;
  status: ToolStatus;
  timestamp: string;
  duration?: number;
  /** Verbatim command/args sent to the tool. */
  input?: string;
  /** Actual tool output (truncated by backend bounds). */
  output?: string;
  /** Error/status message when the tool failed. */
  error?: string;
  /** Agent loop step number — used to chain actions into a sequence. */
  iteration?: number;
  /** Plan todo this action serves (one todo → many actions). */
  todoId?: string | null;
  /** The model's reasoning that led to this action . */
  reasoning?: string | null;
  /** Which backend engine answered — badge on the card. */
  provider?: string | null;
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
  /** Short user-facing title ("Create a.txt") — shown
   *  instead of the full content when present. */
  title?: string;
  /** The full agent-facing content (paths/commands),
   *  kept for tooltips + re-persistence even when a title is shown. */
  content?: string;
}

export type ObjectiveStatus = 'queued' | 'running' | 'paused' | 'blocked' | 'completed' | 'failed' | 'canceled';

export interface Objective {
  id: string;
  sessionId: string;
  prompt: string;
  status: ObjectiveStatus;
  priority: number;
  result?: string | null;
  error?: string | null;
  approval?: string | null;
  resumeMessage?: string | null;
  lastEvent?: string | null;
  attempts: number;
  cancelRequested: boolean;
  createdAt: number;
  updatedAt: number;
  startedAt?: number | null;
  completedAt?: number | null;
}

export interface FileNode {
  name: string;
  type: 'file' | 'folder';
  path: string;
  children?: FileNode[];
  expanded?: boolean;
  size?: number;
  modified?: string;
}

/** One entry in a session's workspace artifact listing. */
export interface SessionFileEntry {
  name: string;
  type: 'file' | 'folder';
  path: string;
  relPath: string;
  size: number;
  modified: string;
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

export interface ObservationWorkspaceSummary {
  gitAvailable: boolean;
  gitBranch: string;
  gitHead: string;
  gitStatus: string;
  gitDiffStat: string;
  lastBuildResult?: {
    result?: string;
    command?: string;
    outputTail?: string;
    exitCode?: number | null;
    timestamp?: number | null;
  } | null;
  openFiles: string[];
}

export interface ObservationEventSummary {
  type: string;
  data: Record<string, unknown>;
}

export interface ObservationSummary {
  timestamp: number;
  workspace: ObservationWorkspaceSummary;
  recentEvents: ObservationEventSummary[];
}

/** A single pipeline stage's real timing, reported by the engine's
 * _StageClock. `status` is authoritative: "done" or "skipped"
 * (the stage never ran — e.g. Tool Select on a no-tool turn). */
export interface StageTiming {
  latencyMs: number;
  status: 'done' | 'skipped' | 'running' | 'pending';
}

/** A detected anomaly on a completed turn. The backend's
 * engine detects these (stall: >60s with near-zero output; token leak:
 * a fresh session inheriting the previous session's context count) and
 * emits them so the Observe panel can ALERT instead of silently showing
 * bad numbers. */
export interface AnomalyData {
  kind: string;
  severity: 'high' | 'medium' | 'low';
  title: string;
  detail: string;
  metrics?: Record<string, number>;
}

export interface ObservationData {
  /** Free-form intent string from the wire. '' = nothing classified yet
   *  (the empty-state sentinel); the backend also emits internal routing
   *  placeholders like 'dispatch' that never fit a fixed union, so this
   *  stays a string rather than the classified-intent literals. */
  intent: string;
  confidence: number;
  toolsUsed: string[];
  memoryHits: number;
  contextTokens: number;
  latency: number;
  /** Structured workspace/runtime state captured after the last completed turn. */
  observation?: ObservationSummary | null;
  /** Real per-stage timings from the backend (keyed by stage name). When
   * present, the pipeline panel renders these instead of a heuristic. */
  stageTimings?: Record<string, StageTiming>;
  /** Alerts from the last completed turn, newest first. */
  anomalies?: AnomalyData[];
}

export interface CapabilityItem {
  id: string;
  description: string;
  toolNames: string[];
  cognitive: boolean;
}

export interface CapabilityFamilySummary {
  id: string;
  label: string;
  capabilities: CapabilityItem[];
}

export interface CapabilitiesData {
  families: CapabilityFamilySummary[];
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
  /** Provider-reported cache-hit input tokens for the last request (P0
   *  Context Engineering Step 1). 0/undefined when the provider doesn't
   *  report caching — the display hides the cached/fresh split then. */
  cachedTokens?: number;
  /** LLM calls that reported usage this turn (multi-call agent turns). */
  llmCalls?: number;
  /** Per-category token shares of the LAST model call's prompt (system prompt,
   *  tool schemas, history, ...), scaled to the provider-reported prompt total.
   *  Absent/empty when the turn never reached the agent loop (fast path). */
  contextBreakdown?: Record<string, number>;
}

/** A durable self-fact the agent picked up incidentally — from ordinary
 *  conversation with no "remember this" trigger — and stored to memory on
 *  its own (B-2026-09-15-15). Same visible-log surface and owner decision as
 *  ReflectionLesson: silent learning is unauditable, so every autonomous
 *  memory write shows up here. */
export interface PassiveMemory {
  id: string;
  /** The stored fact (preview, as the SSE event carries it). */
  text: string;
  memory_type: string;
  subject: string;
  ts: number;
}

/** A pattern-level lesson the self-reflection loop noticed and stored to
 *  memory on its own — the visible-log surface for proactive memory writes
 *  (owner decision 2026-09-18, B-2026-09-15-14: silent learning is
 *  unauditable, so every autonomous lesson write shows up here). */
export interface ReflectionLesson {
  id: string;
  /** The generalized pattern behind the mistake, not the one-off instance. */
  text: string;
  intent: string;
  score: number;
  confidence: string;
  ts: number;
}

export interface ModelOption {
  id: string;
  name: string;
  provider: string;
  size?: string;
  /** Turned off for this provider: kept on the provider but left out of the picker. */
  hidden?: boolean;
  /** The model's max input-token budget (backend adapter effective_context_window).
   *  Used by the top-bar context-window occupancy meter. ABSENT when the
   *  window is unknown (provider doesn't report it and the model isn't in
   *  the backend registry) — the meter then shows tokens without a %. */
  contextWindow?: number;
  /** Where contextWindow came from: "table" (backend registry), "fetched"
   *  (provider /models metadata), "detected" (Ollama /api/show), or
   *  "default" (conservative guess — contextWindow is absent then). */
  contextWindowSource?: 'table' | 'fetched' | 'detected' | 'default';
}

/** Cumulative per-chat performance totals (stats split — bottom-right corner).
 *  Distinct from per-message stats under each bubble: these answer "how is
 *  this session doing overall" — summed tokens, throughput weighted by output
 *  tokens, and average turn latency. Resets on new chat / session switch. */
export interface SessionStats {
  promptTokens: number;
  completionTokens: number;
  /** Sum of per-turn latencies (ms) — average = latencyMs / turnCount. */
  latencyMs: number;
  /** Sum of per-turn generation time (ms) — weighted speed = completionTokens / genTimeMs. */
  genTimeMs: number;
  turnCount: number;
  /** Sum of provider-reported cache-hit input tokens across turns (0 when
   *  the provider never reports caching). */
  cachedTokens: number;
  /** Total LLM calls that reported usage across turns. */
  llmCalls: number;
  /** Each turn's latency (ms), oldest first — the corner reports the median, not the mean. */
  turnLatencies?: number[];
}
