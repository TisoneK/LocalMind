export type MessageRole = 'user' | 'assistant';
export type ToolStatus = 'running' | 'started' | 'in_progress' | 'done' | 'failed' | 'pending';
export type IntentType = 'code' | 'file' | 'chat' | 'search' | 'shell' | 'memory';

// Session 344: Response Block System — structured output from Presentation Intelligence.
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
  /** The model's reasoning that led to this tool call (Session 122). */
  reasoning?: string;
  /** Which backend engine answered (e.g. web_search's winning provider —
   *  Session 271). Rendered as a badge on the Actions card. */
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

/** ADR-34 B-8: bounded evidence entry handed to the parent model. */
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
  /** ADR-34 B-8: evidence entries handed to the parent model after each tool. */
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

/** Canonical model/provider error (ADR-20). The backend's SSE error event
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
  /** ADR-20: canonical error object when this reply failed — rendered as a
   *  friendly card (never the raw provider payload). Mutually exclusive with
   *  normal content (error replies stream no tokens). */
  error?: ModelError;
  toolCalls?: ToolCall[];
  thinkingBlock?: ThinkingStep;
  thinking?: string;
  thinkMs?: number;
  isAgent?: boolean;
  /** ADR-36: the Agent's opening acknowledgement, streamed during parent
   *  initialization. Belongs in chat as the first line of the reply —
   *  distinct from `content` (the final answer that follows tool work). */
  acknowledgement?: string;
  codeBlocks?: CodeBlock[];
  fileResults?: FileResult[];
  pendingWrite?: PendingWrite;
  /** Structured diff data from edit_file tool results */
  diffData?: DiffData;
  /** Session 30: system status feedback — reflects real pipeline stage
   * (e.g., "Let me search the web...", "Understanding your request...").
   * Distinct from `thinking` which is the model's actual reasoning trace. */
  statusText?: string;
  /** Per-message performance metadata (B-2026-08-09-3 / ADR-13), attached
   * when the turn completes. Optional — messages without it render as before.
   * Latency/tokens are per-TURN, not session-global. */
  performance?: {
    latencyMs?: number;
    promptTokens?: number;
    completionTokens?: number;
    tokensPerSecond?: number;
  };
  /** Best-of-N editor candidates (B-2026-08-09-12 / C2 spec step 7), rendered
   * as an expandable section in the message. Populated from the tool result
   *  metadata when the backend sends a best_of_n_edit tool result. */
  candidates?: BestOfNCandidate[];
  /** Session 181 — F4 Frontend Phase Visibility. Agentic phase entries
   *  surfaced from the backend's now-live obs events:
   *  agent_loop_gate_passed, agent_loop_gate_failed_replan,
   *  orchestrator_replan_start/_done/_failed, agent_loop_failure,
   *  plan_nodes_created, plan_node_advanced. Rendered as a phase strip
   *  above the tool cards so the user can see "I am verifying /
   *  replanning / switching to a different approach" — the literal
   *  difference between a chat-with-tools and an agent. */
  agentPhases?: AgentPhase[];
  /** Session 344: structured response blocks from the Presentation Intelligence
   *  layer. When present, the frontend renders these natively (tables, charts,
   *  diagrams, metrics) instead of forcing everything through Markdown.
   *  The agent decides WHAT to show; the UI decides HOW it looks. */
  responseBlocks?: ResponseBlock[];
  /** Session 267: the Agent Workspace run tree for this turn (rebuilt
   *  server-side from obs events and persisted with the message). The Agents
   *  tab restores the last turn's tree from here on reload. */
  agentRuns?: AgentRun[];
}

/** Session 181 — F4 Frontend Phase Visibility.
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
}

/** A single candidate in a best-of-N edit result (B-2026-08-09-12). */
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
  /** The model's reasoning that led to this action (Session 122). */
  reasoning?: string | null;
  /** Which backend engine answered — badge on the card (Session 271). */
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
 * _StageClock (ADR-12). `status` is authoritative: "done" or "skipped"
 * (the stage never ran — e.g. Tool Select on a no-tool turn). */
export interface StageTiming {
  latencyMs: number;
  status: 'done' | 'skipped' | 'running' | 'pending';
}

/** A detected anomaly on a completed turn (Session 123). The backend's
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
  intent: IntentType;
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
}

export interface ModelOption {
  id: string;
  name: string;
  provider: string;
  size?: string;
  /** The model's max input-token budget (backend adapter effective_context_window).
   *  Used by the top-bar context-window occupancy meter. */
  contextWindow?: number;
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
}
