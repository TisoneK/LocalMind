/**
 * LocalMind API Client
 *
 * Singleton client that wraps all backend HTTP and SSE endpoints.
 * Used by the React hooks in @/hooks/useLocalMind.ts.
 *
 * Design notes:
 * - Base URL defaults to '' (same-origin via Vite dev proxy in dev, or
 *   same-origin when served by FastAPI in production). Can be overridden
 *   via window.__LOCALMIND_API__ (set by Electron preload in desktop mode).
 * - All methods return typed data (already unwrapped from response envelopes).
 * - streamChat returns an abort function so the caller can cancel the stream.
 * - No external dependencies — uses native fetch + ReadableStream.
 */

import type {
  ChatMessage,
  Session,
  ActionItem,
  TodoItem,
  FileNode,
  MemoryFact,
  PerformanceMetrics,
  ObservationData,
  ObservationSummary,
  StageTiming,
  CapabilitiesData,
  ModelOption,
  CompletionSuggestion,
} from '@/types';
import { createSSEParser } from './sse';
import type { CapabilitiesResponseWire } from './capabilities-response';

// ─── Client-side intent hint (B-2026-08-09-6 / ADR-11 client half) ──────
// Deterministic, strictly-conservative classifier that suggests a 'chat'
// intent hint for OBVIOUS conversational sends (greetings, thanks, short
// non-tool questions) so the backend can skip the dispatcher LLM call.
//
// Deliberately a SUBSET of the server's own detectors (trivial_input.py):
// the engine's trivial + conversational short-circuits run first and would
// catch the same messages anyway, so the hint must NEVER claim 'chat' for
// anything that needs tools/live data/system info — a wrong hint would
// bypass the dispatcher's correct routing. When in doubt, return undefined
// (no hint → normal pipeline).

const _HINT_GREETING_RE = /^(?:hi|hello|hey|heya|howdy|yo|sup|good\s*(?:morning|afternoon|evening|day)|greetings|nice to (?:meet you|see you)|what'?s up|how'?s it going|how are you)\b[!.?]*$/i;
const _HINT_FAREWELL_RE = /^(?:bye|goodbye|see you(?:\s+(?:later|soon|tomorrow))?|later|cya|good night|take care|farewell)\b[!.?]*$/i;
const _HINT_THANKS_RE = /^(?:thanks|thank you|thx|ty|appreciate it|much obliged|grateful|cheers)\b[!.?]*$/i;
const _HINT_ACK_RE = /^(?:ok|okay|got it|understood|sure|will do|roger|acknowledged|makes sense|gotcha|i see)\b[!.?]*$/i;
const _HINT_YES_NO_RE = /^(?:yes|no|yep|nope|yeah|nah|yup)\b[!.?]*$/i;

const _HINT_OPENER_RE = /^(?:what'?s|whats|what|who'?s|whos|who|how'?s|hows|how|why|when|which|can you|can i|could you|do you|are you|is it|is there|will you|would you|should i|tell me|explain|describe|define)\b/i;

// Mirror of trivial_input.py's _CONVERSATIONAL_BLOCKED_KEYWORDS — any
// tool/realtime/system keyword forces the full pipeline so the dispatcher
// routes correctly ("what time is it" → SYSINFO, "what is today's weather"
// → WEB_SEARCH, "who wrote app.py" → tools).
// ⚠ KEEP IN SYNC with backend/src/core/trivial_input.py: if a keyword is
// added there, add it here too — otherwise a message like "what's my IP"
// gets a chat hint that bypasses the dispatcher once the server starts
// routing it to a tool.
const _HINT_BLOCKED_WORDS = [
  'weather', 'forecast', 'temperature', 'today', 'tomorrow', 'tonight',
  'latest', 'current', 'news', 'score', 'scores', 'match', 'matches',
  'game', 'games', 'price', 'prices', 'cost', 'exchange', 'stock',
  'shares', 'election', 'time', 'date', 'what day', 'day of the week',
  'ram', 'cpu', 'memory', 'disk', 'storage', 'specs', 'hardware',
  'installed', 'processor', 'gpu', 'search', 'fetch', 'web', 'browse',
  'url', 'http', 'download', 'open', 'read', 'write', 'create', 'edit',
  'delete', 'save', 'file', 'files', 'folder', 'directory', 'code',
  'script', 'program', 'function', 'bug', 'error', 'exception', 'crash',
  'run', 'execute', 'install', 'command', 'terminal', 'shell', 'python',
  'node', 'git', 'pdf', 'doc', 'docx', 'xlsx', 'csv', 'json', 'database',
  'api', 'test', 'tests', 'show', 'list', 'find', 'fix', 'debug', 'log', 'logs',
];
const _HINT_BLOCKED_RE = new RegExp(`\\b(?:${_HINT_BLOCKED_WORDS.join('|')})\\b`, 'i');
const _HINT_FILE_EXT_RE = /\b\w+\.(?:py|js|ts|tsx|jsx|md|json|txt|pdf|docx?|xlsx?|csv|html?|css|sh|sql)\b/i;
const _HINT_URL_RE = /https?:\/\//i;

const _HINT_MAX_CHARS = 140;
const _HINT_MAX_WORDS = 20;

/**
 * Deterministic client-side intent hint (B-2026-08-09-6 / ADR-11).
 *
 * Returns 'chat' only for obvious conversational sends, else undefined
 * (no hint → the backend runs its normal pipeline). NEVER returns a tool
 * intent — explicit tool selection is passed separately by the caller.
 */
export function classifyClientIntent(message: string): string | undefined {
  const trimmed = (message || '').trim();
  if (!trimmed) return undefined;

  const cleaned = trimmed.replace(/[!.?.,;:]+$/, '').trim();

  // Trivial inputs (greetings / farewells / thanks / acknowledgments / yes-no).
  if (cleaned.length <= 40 && cleaned.split(/\s+/).length <= 5) {
    if (
      _HINT_GREETING_RE.test(cleaned) ||
      _HINT_FAREWELL_RE.test(cleaned) ||
      _HINT_THANKS_RE.test(cleaned) ||
      _HINT_ACK_RE.test(cleaned) ||
      _HINT_YES_NO_RE.test(cleaned)
    ) {
      return 'chat';
    }
  }

  // Conversational questions: interrogative opener, no tool/realtime/system
  // keywords, reasonably short.
  if (cleaned.length > _HINT_MAX_CHARS) return undefined;
  if (cleaned.split(/\s+/).length > _HINT_MAX_WORDS) return undefined;
  if (!_HINT_OPENER_RE.test(cleaned)) return undefined;
  if (_HINT_BLOCKED_RE.test(cleaned)) return undefined;
  if (_HINT_FILE_EXT_RE.test(cleaned)) return undefined;
  if (_HINT_URL_RE.test(cleaned)) return undefined;
  return 'chat';
}

// ─── Types ─────────────────────────────────────────────────────────────

interface HealthResponse {
  status: string;
  version?: string;
  uptime?: number;
  provider_reachable?: boolean;
  engine_ready?: boolean;
  model?: string;
  adapter?: string;
}

interface ModelsResponse {
  models: ModelOption[];
  current: string;
  provider: string;
}

interface TerminalResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  duration: number;
  command: string;
  cwd: string;
}

interface TerminalSessionInfo {
  sessionId: string;
  cwd: string;
  historyCount: number;
  envCount: number;
  toolExecutionCount: number;
}

interface TerminalHistoryResponse {
  sessionId: string;
  commands: string[];
  count: number;
}

interface CompletionResponse {
  suggestions: string[];
  count: number;
}

interface ObservabilityResponse {
  session_id: string;
  intent: string | null;
  confidence: number | null;
  tools_used: string;
  memory_hits: number;
  context_tokens: number;
  latency_ms: number;
  tool_timeline: unknown[];
  stage_timings?: Record<string, { latency_ms: number; status: string }> | null;
  observation?: {
    timestamp: number;
    workspace: {
      git_available: boolean;
      git_branch: string;
      git_head: string;
      git_status: string;
      git_diff_stat: string;
      last_build_result?: {
        result?: string;
        command?: string;
        output_tail?: string;
        exit_code?: number | null;
        timestamp?: number | null;
      } | null;
      open_files: string[];
    };
    recent_events: Array<{
      type: string;
      data: Record<string, unknown>;
    }>;
  } | null;
}

interface PersistedSettings {
  adapter?: string;
  model?: string;
  ollamaUrl?: string;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asOptionalNumber(value: unknown): number | null | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : value === null ? null : undefined;
}

function mapStageTimings(raw: unknown): Record<string, StageTiming> | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const out: Record<string, StageTiming> = {};
  for (const [stage, entry] of Object.entries(raw as Record<string, unknown>)) {
    if (!entry || typeof entry !== 'object') continue;
    const e = entry as Record<string, unknown>;
    out[stage] = {
      latencyMs: typeof e.latency_ms === 'number' ? e.latency_ms : 0,
      status: (e.status === 'skipped' ? 'skipped' : e.status === 'running' ? 'running' : 'done') as StageTiming['status'],
    };
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function mapObservationSummary(raw: unknown): ObservationSummary | null {
  if (!raw || typeof raw !== 'object') return null;

  const summary = raw as Record<string, unknown>;
  const rawWorkspace = summary.workspace;
  const workspace = rawWorkspace && typeof rawWorkspace === 'object'
    ? rawWorkspace as Record<string, unknown>
    : {};
  const rawBuild = workspace.last_build_result;
  const build = rawBuild && typeof rawBuild === 'object'
    ? rawBuild as Record<string, unknown>
    : null;
  const rawEvents = Array.isArray(summary.recent_events) ? summary.recent_events : [];

  return {
    timestamp: asOptionalNumber(summary.timestamp) ?? 0,
    workspace: {
      gitAvailable: workspace.git_available === true,
      gitBranch: asString(workspace.git_branch),
      gitHead: asString(workspace.git_head),
      gitStatus: asString(workspace.git_status),
      gitDiffStat: asString(workspace.git_diff_stat),
      lastBuildResult: build
        ? {
            result: asString(build.result),
            command: asString(build.command),
            outputTail: asString(build.output_tail),
            exitCode: asOptionalNumber(build.exit_code),
            timestamp: asOptionalNumber(build.timestamp),
          }
        : null,
      openFiles: Array.isArray(workspace.open_files)
        ? workspace.open_files.filter((path): path is string => typeof path === 'string')
        : [],
    },
    recentEvents: rawEvents.flatMap((rawEvent) => {
      if (!rawEvent || typeof rawEvent !== 'object') return [];
      const event = rawEvent as Record<string, unknown>;
      const rawData = event.data;
      return [{
        type: asString(event.type) || 'event',
        data: rawData && typeof rawData === 'object' && !Array.isArray(rawData)
          ? rawData as Record<string, unknown>
          : {},
      }];
    }),
  };
}

// ─── Client ────────────────────────────────────────────────────────────

class LocalMindClient {
  private baseUrl: string;

  constructor() {
    // Allow Electron preload to override the API base URL for desktop mode.
    // In browser/dev mode, baseUrl is '' so requests go through the Vite proxy.
    this.baseUrl = (typeof window !== 'undefined' && (window as any).__LOCALMIND_API__) || '';
  }

  /**
   * Core request method with automatic 503 retry.
   *
   * During startup, the Vite proxy returns 503 when the backend isn't ready
   * yet. Instead of throwing immediately (which spams the browser console
   * with red errors on every poll), we retry up to 5 times with a 1s
   * backoff. This makes the frontend self-heal silently once the backend
   * finishes booting.
   *
   * Non-503 errors are thrown immediately — only the "backend starting"
   * case gets the retry treatment.
   */
  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const maxRetries = 5;
    const retryDelayMs = 1000;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      let res: Response;
      try {
        res = await fetch(`${this.baseUrl}${path}`, {
          ...options,
          headers: {
            'Content-Type': 'application/json',
            ...(options?.headers || {}),
          },
        });
      } catch (networkErr) {
        // Network-level failure (ECONNREFUSED etc.) — also a "backend
        // starting" symptom. Retry instead of throwing.
        if (attempt < maxRetries - 1) {
          await this._sleep(retryDelayMs);
          continue;
        }
        throw networkErr;
      }

      // 503 = backend starting (Vite proxy returns this cleanly).
      // Retry after a short delay instead of erroring.
      if (res.status === 503 && attempt < maxRetries - 1) {
        await this._sleep(retryDelayMs);
        continue;
      }

      if (!res.ok) {
        const detail = await this._extractError(res);
        throw new Error(detail);
      }
      return res.json() as Promise<T>;
    }
    // Exhausted all retries
    throw new Error('Backend unavailable after 5 retries (is the server starting?)');
  }

  private _sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async _extractError(res: Response): Promise<string> {
    try {
      const body = await res.json();
      return body.detail || body.error || `HTTP ${res.status}`;
    } catch {
      return `HTTP ${res.status}`;
    }
  }

  // ── Health ──────────────────────────────────────────────────────────

  async getHealth(): Promise<HealthResponse> {
    return this.request<HealthResponse>('/api/health');
  }

  // ── Sessions ────────────────────────────────────────────────────────

  async getSessions(): Promise<Session[]> {
    const data = await this.request<{ sessions: any[] }>('/api/sessions');
    // Map backend format → frontend Session type
    return (data.sessions || []).map((s) => ({
      id: s.id,
      title: s.title || 'New Chat',
      lastMessage: s.last_message || s.lastMessage || s.preview || '',
      timestamp: s.formattedDate || String(s.timestamp || ''),
      formattedDate: s.formattedDate,
      messageCount: s.messageCount ?? s.message_count ?? 0,
      active: false,
    }));
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request(`/api/sessions/${sessionId}`, { method: 'DELETE' });
  }

  async getSessionHistory(sessionId: string): Promise<ChatMessage[]> {
    const data = await this.request<{ history: any[] }>(
      `/api/sessions/${sessionId}/history`
    );      return (data.history || []).map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,

      // Backend stores timestamps as raw epoch floats (e.g. 1783586329.77).
      // Format to HH:MM for display — same format as live messages.
      timestamp: typeof m.timestamp === 'number'
        ? new Date(m.timestamp * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false })
        : m.timestamp || '',
      toolCalls: m.toolCalls,
      fileResults: m.fileResults,
    }));
  }

  // ── Chat (SSE streaming) ────────────────────────────────────────────

  /**
   * Stream a chat response via Server-Sent Events.
   *
   * @param message  User message text
   * @param sessionId  Active session ID
   * @param onChunk  Called with each raw SSE data payload (JSON string)
   * @param onDone   Called when the stream completes normally
   * @param onError  Called when the stream fails or is aborted
   * @param toolHint  Optional tool/intent hint (e.g. 'code_exec', 'shell') sent
   *                   as X-LocalMind-Intent header so the backend can skip the
   *                   dispatcher LLM call for trivial messages.
   * @returns An abort function — call it to cancel the stream
   */
  streamChat(
    message: string,
    sessionId: string,
    onChunk: (rawData: string) => void,
    onDone: () => void,
    onError: () => void,
    toolHint?: string
  ): () => void {
    const controller = new AbortController();

    const formData = new FormData();
    formData.append('message', message);
    formData.append('session_id', sessionId);

    const headers: Record<string, string> = {};
    if (toolHint) {
      headers['X-LocalMind-Intent'] = toolHint;
      headers['X-Intent-Confidence'] = '1.0';
    }

    fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
      headers,
    })
      .then(async (res) => {
        if (!res.ok || !res.body) {
          onError();
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let streamCompleted = false;
        const finish = (): void => {
          if (!streamCompleted) {
            streamCompleted = true;
            onDone();
          }
        };
        const parser = createSSEParser(onChunk, finish);

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            if (parser.push(decoder.decode(value, { stream: true }))) {
              return;
            }
          }

          // TextDecoder can retain an incomplete UTF-8 sequence between
          // chunks, so decode its final bytes before flushing the SSE line.
          if (parser.push(decoder.decode())) {
            return;
          }
          parser.flush();
          // Streams may end without [DONE]; still complete after the final
          // buffered event has been delivered.
          finish();
        } catch (_err) {
          // AbortError is expected when the user cancels
          if (controller.signal.aborted) {
            onDone();
          } else {
            onError();
          }
        }
      })
      .catch((_err) => {
        if (controller.signal.aborted) {
          onDone();
        } else {
          onError();
        }
      });

    return () => controller.abort();
  }

  /**
   * Queue a steering message for an in-flight agent turn (B-2026-08-02-5/A5).
   *
   * The backend drains it at the next agent-loop iteration boundary — the
   * agent sees it as a new user prompt and continues its turn instead of
   * being aborted and re-run.
   *
   * @returns true when accepted; false on 400 (blank message) or 409
   *          (queue full — the agent is mid-step, retry shortly).
   */
  async steer(sessionId: string, message: string): Promise<boolean> {
    const text = message.trim();
    if (!text) return false;
    try {
      await this.request<{ accepted: boolean }>(
        `/api/chat/${encodeURIComponent(sessionId)}/steer`,
        {
          method: 'POST',
          body: JSON.stringify({ message: text }),
        }
      );
      return true;
    } catch {
      return false;
    }
  }

  // ── Actions ─────────────────────────────────────────────────────────

  async getActions(sessionId: string): Promise<ActionItem[]> {
    try {
      const data = await this.request<ActionItem[]>(
        `/api/actions?session_id=${encodeURIComponent(sessionId)}`
      );
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  // ── File Tree ───────────────────────────────────────────────────────

  async getFileTree(path?: string): Promise<FileNode[]> {
    try {
      const queryPath = path || '';
      const data = await this.request<{ children: any[] }>(
        `/api/files?path=${encodeURIComponent(queryPath)}`
      );
      return (data.children || []).map((c) => ({
        name: c.name,
        type: c.type,
        path: c.path,
        children: c.children,
      }));
    } catch {
      return [];
    }
  }

  // ── Todos ───────────────────────────────────────────────────────────

  async getTodos(sessionId: string): Promise<TodoItem[]> {
    try {
      const data = await this.request<any[]>(
        `/api/todos?session_id=${encodeURIComponent(sessionId)}`
      );
      return Array.isArray(data)
        ? data.map((todo) => ({
            ...todo,
            text: todo.text || todo.content || '',
            sessionId: todo.sessionId || todo.session_id,
          }))
        : [];
    } catch {
      return [];
    }
  }

  async createTodo(sessionId: string, text: string): Promise<TodoItem> {
    return this.request<TodoItem>('/api/todos', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, content: text }),
    });
  }

  async updateTodo(id: string, updates: { completed?: boolean; content?: string }): Promise<void> {
    await this.request(`/api/todos/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    });
  }

  async deleteTodo(id: string): Promise<void> {
    await this.request(`/api/todos/${id}`, { method: 'DELETE' });
  }

  // ── Autonomous objectives ──────────────────────────────────────────

  async getObjectives(sessionId?: string): Promise<import('@/types').Objective[]> {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    try {
      const data = await this.request<{ objectives: any[] }>(`/api/objectives${query}`);
      return (data.objectives || []).map((item) => ({
        id: item.id,
        sessionId: item.session_id,
        prompt: item.prompt,
        status: item.status,
        priority: item.priority ?? 0,
        result: item.result,
        error: item.error,
        approval: item.approval,
        resumeMessage: item.resume_message,
        lastEvent: item.last_event,
        attempts: item.attempts ?? 0,
        cancelRequested: Boolean(item.cancel_requested),
        createdAt: item.created_at,
        updatedAt: item.updated_at,
        startedAt: item.started_at,
        completedAt: item.completed_at,
      }));
    } catch {
      return [];
    }
  }

  async createObjective(sessionId: string, prompt: string): Promise<import('@/types').Objective> {
    const item = await this.request<any>('/api/objectives', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, prompt }),
    });
    return this._mapObjective(item);
  }

  async pauseObjective(id: string): Promise<import('@/types').Objective> {
    return this._mapObjective(await this.request(`/api/objectives/${encodeURIComponent(id)}/pause`, { method: 'POST' }));
  }

  async resumeObjective(id: string): Promise<import('@/types').Objective> {
    return this._mapObjective(await this.request(`/api/objectives/${encodeURIComponent(id)}/resume`, { method: 'POST', body: JSON.stringify({}) }));
  }

  async cancelObjective(id: string): Promise<import('@/types').Objective> {
    return this._mapObjective(await this.request(`/api/objectives/${encodeURIComponent(id)}/cancel`, { method: 'POST' }));
  }

  private _mapObjective(item: any): import('@/types').Objective {
    return {
      id: item.id,
      sessionId: item.session_id,
      prompt: item.prompt,
      status: item.status,
      priority: item.priority ?? 0,
      result: item.result,
      error: item.error,
      approval: item.approval,
      resumeMessage: item.resume_message,
      lastEvent: item.last_event,
      attempts: item.attempts ?? 0,
      cancelRequested: Boolean(item.cancel_requested),
      createdAt: item.created_at,
      updatedAt: item.updated_at,
      startedAt: item.started_at,
      completedAt: item.completed_at,
    };
  }

  // ── Terminal ────────────────────────────────────────────────────────

  async getTerminalSessionInfo(sessionId: string): Promise<TerminalSessionInfo> {
    return this.request<TerminalSessionInfo>(
      `/api/terminal/session/${encodeURIComponent(sessionId)}`
    );
  }

  async getTerminalHistory(sessionId: string, limit: number = 50): Promise<TerminalHistoryResponse> {
    return this.request<TerminalHistoryResponse>(
      `/api/terminal/history/${encodeURIComponent(sessionId)}?limit=${limit}`
    );
  }

  async executeTerminal(
    command: string,
    cwd?: string,
    sessionId?: string
  ): Promise<TerminalResult> {
    return this.request<TerminalResult>('/api/terminal/execute', {
      method: 'POST',
      body: JSON.stringify({
        command,
        cwd: cwd || null,
        session_id: sessionId || 'default',
      }),
    });
  }

  async getTerminalCompletions(
    partial: string,
    sessionId: string
  ): Promise<CompletionSuggestion[]> {
    try {
      const data = await this.request<CompletionResponse>('/api/terminal/complete', {
        method: 'POST',
        body: JSON.stringify({
          partial,
          session_id: sessionId || 'default',
        }),
      });
      return (data.suggestions || []).map((s) => ({
        text: s,
        type: 'command' as const,
      }));
    } catch {
      return [];
    }
  }

  // ── Observability ───────────────────────────────────────────────────

  async getObservability(sessionId: string): Promise<ObservationData> {
    try {
      const data = await this.request<ObservabilityResponse>(
        `/api/observability/${encodeURIComponent(sessionId)}`
      );
      const observation = mapObservationSummary(data.observation);
      const toolsUsed = typeof data.tools_used === 'string'
        ? data.tools_used.split(',').filter(Boolean)
        : [];

      return {
        intent: (typeof data.intent === 'string' ? data.intent : 'chat') as ObservationData['intent'],
        confidence: typeof data.confidence === 'number' ? data.confidence : 0,
        toolsUsed,
        memoryHits: typeof data.memory_hits === 'number' ? data.memory_hits : 0,
        contextTokens: typeof data.context_tokens === 'number' ? data.context_tokens : 0,
        latency: typeof data.latency_ms === 'number' ? data.latency_ms : 0,
        observation,
        stageTimings: mapStageTimings(data.stage_timings),
      };
    } catch {
      return {
        intent: 'chat',
        confidence: 0,
        toolsUsed: [],
        memoryHits: 0,
        contextTokens: 0,
        latency: 0,
        observation: null,
      };
    }
  }

  // ── Capabilities ────────────────────────────────────────────────────

  async getCapabilities(): Promise<CapabilitiesData> {
    try {
      const data = await this.request<CapabilitiesResponseWire>('/api/capabilities');
      const families = Array.isArray(data.families)
        ? data.families.flatMap((rawFamily) => {
            if (!rawFamily || typeof rawFamily !== 'object') return [];
            const family = rawFamily as {
              id?: unknown;
              label?: unknown;
              capabilities?: unknown;
            };
            const rawCapabilities = Array.isArray(family.capabilities)
              ? family.capabilities
              : [];
            return [{
              id: typeof family.id === 'string' ? family.id : '',
              label: typeof family.label === 'string' ? family.label : '',
              capabilities: rawCapabilities.flatMap((rawCapability) => {
                if (!rawCapability || typeof rawCapability !== 'object') return [];
                const capability = rawCapability as {
                  id?: unknown;
                  description?: unknown;
                  tool_names?: unknown;
                  cognitive?: unknown;
                };
                return [{
                  id: typeof capability.id === 'string' ? capability.id : '',
                  description: typeof capability.description === 'string' ? capability.description : '',
                  toolNames: Array.isArray(capability.tool_names)
                    ? capability.tool_names.filter((tool): tool is string => typeof tool === 'string')
                    : [],
                  cognitive: capability.cognitive === true,
                }];
              }),
            }];
          })
        : [];

      return { families };
    } catch {
      return { families: [] };
    }
  }

  // ── Metrics ─────────────────────────────────────────────────────────

  async getMetrics(): Promise<PerformanceMetrics> {
    try {
      return await this.request<PerformanceMetrics>('/api/metrics');
    } catch {
      return {
        tokensPerSecond: 0,
        latency: 0,
        totalTokens: 0,
        promptTokens: 0,
        completionTokens: 0,
      };
    }
  }

  // ── Models ──────────────────────────────────────────────────────────

  async getModels(provider?: string): Promise<ModelsResponse> {
    // When `provider` is given, fetch models for that specific provider
    // (used by the Settings modal's "Add Key" form). Without it, returns
    // models for the currently active adapter (used by the chat sidebar).
    const query = provider ? `?provider=${encodeURIComponent(provider)}` : '';
    return this.request<ModelsResponse>(`/api/models${query}`);
  }

  async selectModel(modelId: string): Promise<void> {
    await this.request('/api/models/select', {
      method: 'POST',
      body: JSON.stringify({ model: modelId }),
    });
  }

  // ── Memory ──────────────────────────────────────────────────────────

  async getMemory(): Promise<MemoryFact[]> {
    try {
      const data = await this.request<{ facts: MemoryFact[] }>('/api/memory');
      return data.facts || [];
    } catch {
      return [];
    }
  }

  async storeMemory(content: string, source: string): Promise<void> {
    await this.request('/api/memory', {
      method: 'POST',
      body: JSON.stringify({
        fact: content,
        source: source || 'manual',
      }),
    });
  }

  async deleteMemory(factId: string): Promise<void> {
    await this.request(`/api/memory/${encodeURIComponent(factId)}`, {
      method: 'DELETE',
    });
  }

  // ── Settings / Adapter ──────────────────────────────────────────────

  async getSettings(): Promise<{
    adapter: string;
    model: string;
    embed_model?: string;
    providers: Record<string, unknown>;
  }> {
    return this.request('/api/settings');
  }

  async setAdapter(adapter: string, model?: string): Promise<void> {
    await this.request('/api/settings/adapter', {
      method: 'POST',
      body: JSON.stringify({ adapter, model }),
    });
    // Persist to localStorage so the adapter is restored on next launch
    this.savePersistedSettings({ adapter, model: model || '' });
  }

  async setProviderKey(
    provider: string,
    apiKey: string,
    model?: string,
  ): Promise<{ validated: boolean; validation_error: string | null; message: string }> {
    return this.request('/api/settings/provider-key', {
      method: 'POST',
      body: JSON.stringify({ provider, api_key: apiKey, model }),
    });
  }

  async deleteProviderKey(provider: string): Promise<void> {
    await this.request('/api/settings/provider-key', {
      method: 'DELETE',
      body: JSON.stringify({ provider }),
    });
  }

  // ── Ollama URL (Ollama adapter only) ────────────────────────────────

  async getOllamaUrl(): Promise<{ url: string; is_remote: boolean }> {
    return this.request('/api/ollama/url');
  }

  async setOllamaUrl(url: string): Promise<{ url: string; reachable: boolean; message: string }> {
    return this.request('/api/ollama/url', {
      method: 'POST',
      body: JSON.stringify({ url }),
    });
  }

  async resetOllamaUrl(): Promise<void> {
    await this.request('/api/ollama/url', { method: 'DELETE' });
  }

  // ── File Write Confirmation ─────────────────────────────────────────

  async confirmWrite(path: string, content: string): Promise<{ path: string; filename: string }> {
    return this.request('/api/confirm-write', {
      method: 'POST',
      body: JSON.stringify({ path, content }),
    });
  }

  // ── Persisted Settings (localStorage) ───────────────────────────────

  /**
   * Read adapter/model from localStorage. Used on app mount to restore
   * the user's last session without a blocking API call.
   */
  getPersistedSettings(): PersistedSettings {
    try {
      const raw = localStorage.getItem('localmind-settings');
      if (!raw) return {};
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }

  private savePersistedSettings(settings: PersistedSettings): void {
    try {
      localStorage.setItem('localmind-settings', JSON.stringify(settings));
    } catch {
      // localStorage may be unavailable (private mode, Electron sandbox)
    }
  }

  /**
   * Sync the frontend's localStorage settings from the backend.
   *
   * The backend's ~/LocalMind/settings.json is the source of truth — it's
   * loaded at startup and contains the adapter, model, and API keys.
   * Previously, this method PUSHED localStorage state to the backend on
   * mount via POST /api/settings/adapter, which overwrote the backend's
   * settings.json with stale localStorage values (or empty values when
   * localStorage was empty, wiping the saved model).
   *
   * Now: PULL from the backend instead. GET /api/settings returns the
   * current adapter+model, which we cache in localStorage for offline
   * display. The backend is never overwritten on mount — only when the
   * user explicitly changes a setting via the Settings modal.
   */
  async restorePersistedAdapter(): Promise<void> {
    try {
      const settings = await this.getSettings();
      if (settings.adapter) {
        this.savePersistedSettings({
          adapter: settings.adapter,
          model: settings.model || '',
        });
      }
    } catch {
      // Non-fatal: backend may not be ready yet.
      // The useModels/useHealth hooks will retry and sync once it's up.
    }
  }
}

// ─── Exports ───────────────────────────────────────────────────────────

export const localmindClient = new LocalMindClient();

export function getPersistedSettings(): PersistedSettings {
  return localmindClient.getPersistedSettings();
}
