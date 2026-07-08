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
  TerminalLine,
  MemoryFact,
  PerformanceMetrics,
  ObservationData,
  ModelOption,
  CompletionSuggestion,
} from '@/types';

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
}

interface PersistedSettings {
  adapter?: string;
  model?: string;
  ollamaUrl?: string;
}

// ─── Client ────────────────────────────────────────────────────────────

class LocalMindClient {
  private baseUrl: string;

  constructor() {
    // Allow Electron preload to override the API base URL for desktop mode.
    // In browser/dev mode, baseUrl is '' so requests go through the Vite proxy.
    this.baseUrl = (typeof window !== 'undefined' && (window as any).__LOCALMIND_API__) || '';
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
    });
    if (!res.ok) {
      const detail = await this._extractError(res);
      throw new Error(detail);
    }
    return res.json() as Promise<T>;
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
      lastMessage: '',
      timestamp: s.formattedDate || String(s.timestamp || ''),
      messageCount: s.messageCount || 0,
      active: false,
    }));
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request(`/api/sessions/${sessionId}`, { method: 'DELETE' });
  }

  async getSessionHistory(sessionId: string): Promise<ChatMessage[]> {
    const data = await this.request<{ history: any[] }>(
      `/api/sessions/${sessionId}/history`
    );
    return (data.history || []).map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
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
   * @returns An abort function — call it to cancel the stream
   */
  streamChat(
    message: string,
    sessionId: string,
    onChunk: (rawData: string) => void,
    onDone: () => void,
    onError: () => void
  ): () => void {
    const controller = new AbortController();

    const formData = new FormData();
    formData.append('message', message);
    formData.append('session_id', sessionId);

    fetch(`${this.baseUrl}/api/chat`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok || !res.body) {
          onError();
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // SSE events are separated by double newlines
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                const data = line.slice(6);
                if (data === '[DONE]') {
                  onDone();
                  return;
                }
                onChunk(data);
              }
            }
          }
          // Stream ended without [DONE] — treat as complete
          onDone();
        } catch (err) {
          // AbortError is expected when the user cancels
          if (controller.signal.aborted) {
            onDone();
          } else {
            onError();
          }
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) {
          onDone();
        } else {
          onError();
        }
      });

    return () => controller.abort();
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
      const data = await this.request<TodoItem[]>(
        `/api/todos?session_id=${encodeURIComponent(sessionId)}`
      );
      return Array.isArray(data) ? data : [];
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
      return {
        intent: (data.intent || 'chat') as ObservationData['intent'],
        confidence: data.confidence ?? 0,
        toolsUsed: data.tools_used ? data.tools_used.split(',').filter(Boolean) : [],
        memoryHits: data.memory_hits || 0,
        contextTokens: data.context_tokens || 0,
        latency: data.latency_ms || 0,
      };
    } catch {
      return {
        intent: 'chat',
        confidence: 0,
        toolsUsed: [],
        memoryHits: 0,
        contextTokens: 0,
        latency: 0,
      };
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

  async getModels(): Promise<ModelsResponse> {
    return this.request<ModelsResponse>('/api/models');
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
  }

  async setProviderKey(provider: string, apiKey: string, model?: string): Promise<void> {
    await this.request('/api/settings/provider-key', {
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
   * Restore the persisted adapter on app mount.
   * Sends a POST /api/settings/adapter call if a saved adapter exists.
   * Failures are non-fatal — the backend keeps its current adapter.
   */
  async restorePersistedAdapter(): Promise<void> {
    const saved = this.getPersistedSettings();
    if (!saved.adapter) return;
    try {
      await this.setAdapter(saved.adapter, saved.model);
    } catch {
      // Non-fatal: backend may not be ready yet, or adapter may be invalid.
      // The user can reconfigure via the settings UI.
    }
  }
}

// ─── Exports ───────────────────────────────────────────────────────────

export const localmindClient = new LocalMindClient();

export function getPersistedSettings(): PersistedSettings {
  return localmindClient.getPersistedSettings();
}
