// Export chat sessions to a downloadable file (Markdown or JSON).
//
// The chat list supports selecting multiple sessions and exporting them in one
// file. Serialization is kept pure (no DOM) so it is unit-testable; the actual
// browser download is a thin, separately-testable helper.
//
// B-2026-08-23-3: the export used to be "just chat" — role/content/timestamp
// plus bare tool names. The history payload carries much more (thinking,
// acknowledgement, error, full tool calls with args/output/reasoning/provider,
// per-turn metrics, agent runs/phases, file results), and the session's todo
// checklist lives in a separate endpoint. Both formats now include the full
// session: Markdown as a readable transcript, JSON as a complete record.

import type { ChatMessage, Session, TodoItem } from '@/types';

export type ExportFormat = 'markdown' | 'json';

/** A session paired with its fetched message history and todo checklist. */
export interface SessionExport {
  session: Session;
  history: ChatMessage[];
  /** The session's todo checklist (fetched from GET /api/todos). */
  todos?: TodoItem[];
}

function roleLabel(role: string): string {
  if (role === 'user') return 'User';
  if (role === 'assistant') return 'Assistant';
  if (role === 'system') return 'System';
  return role ? role[0].toUpperCase() + role.slice(1) : 'Unknown';
}

/** Render the session's todo checklist as a compact Markdown list. */
function todosToMarkdown(todos: TodoItem[] | undefined): string[] {
  if (!todos?.length) return [];
  const lines = ['', '**Task checklist:**', ''];
  for (const t of todos) {
    const done = t.completed ? 'x' : ' ';
    const status = t.status && !t.completed ? ` _(${t.status})_` : '';
    lines.push(`- [${done}] ${t.text || t.id}${status}`);
  }
  return lines;
}

/** Render one tool call as a readable step block. */
function toolCallToMarkdown(tc: NonNullable<ChatMessage['toolCalls']>[number]): string[] {
  const lines: string[] = [];
  const name = tc.label || tc.name || 'tool';
  const status = tc.status ? ` [${tc.status}]` : '';
  const dur = tc.duration !== undefined ? ` · ${tc.duration}ms` : '';
  const provider = tc.provider ? ` · ${tc.provider}` : '';
  lines.push(`- 🛠 **${name}**${status}${dur}${provider}`);
  if (tc.iteration !== undefined) {
    lines.push(`  _step ${tc.iteration}_`);
  }
  if (tc.input) {
    const snippet = tc.input.length > 300 ? `${tc.input.slice(0, 300)}…` : tc.input;
    lines.push(`  - input: \`${snippet}\``);
  }
  if (tc.output) {
    const snippet = tc.output.length > 500 ? `${tc.output.slice(0, 500)}…` : tc.output;
    lines.push(`  - output: ${snippet}`);
  }
  if (tc.error) {
    lines.push(`  - error: ${tc.error}`);
  }
  if (tc.reasoning) {
    const snippet = tc.reasoning.length > 300 ? `${tc.reasoning.slice(0, 300)}…` : tc.reasoning;
    lines.push(`  - why: ${snippet}`);
  }
  return lines;
}

/** Render one message's full session information as readable Markdown. */
function messageToMarkdown(m: ChatMessage): string[] {
  const lines: string[] = [];
  const ts = m.timestamp ? ` _(${m.timestamp})_` : '';
  lines.push('', `**${roleLabel(m.role)}**${ts}`, '');
  lines.push(m.content ?? '');

  if (m.acknowledgement) {
    lines.push('', `> _acknowledgement: ${m.acknowledgement}_`);
  }

  // Session 290: the thinking block (model reasoning) — collapsible in the
  // UI; in the export it's a quoted section after the message.
  if (m.thinking) {
    const snippet = m.thinking.length > 1000 ? `${m.thinking.slice(0, 1000)}…` : m.thinking;
    lines.push('', '<details>', '<summary>💭 Reasoning</summary>', '', '```', snippet, '```', '</details>');
  }

  if (m.error) {
    lines.push('', `> ⚠️ **Error:** ${m.error.message || JSON.stringify(m.error)}`);
  }

  if (m.toolCalls?.length) {
    lines.push('', '**Tool steps:**', '');
    for (const tc of m.toolCalls) {
      lines.push(...toolCallToMarkdown(tc));
    }
  }

  if (m.fileResults?.length) {
    lines.push('', '**Files:**', '');
    for (const f of m.fileResults) {
      // The live SSE path builds {filename, path, status} while the restored
      // history payload carries {name, size, type} — accept both shapes.
      const label = f.path || f.filename || f.name || f.id;
      const size = 'size' in f && f.size ? ` (${f.size} bytes)` : '';
      const status = f.status ? ` _${f.status}_` : '';
      lines.push(`- 📄 \`${label}\`${size}${status}`);
    }
  }

  if (m.performance) {
    const bits: string[] = [];
    if (m.performance.latencyMs !== undefined) bits.push(`${m.performance.latencyMs}ms`);
    if (m.performance.promptTokens !== undefined) bits.push(`${m.performance.promptTokens} in`);
    if (m.performance.completionTokens !== undefined) bits.push(`${m.performance.completionTokens} out`);
    if (m.performance.tokensPerSecond !== undefined) bits.push(`${m.performance.tokensPerSecond} tok/s`);
    if (bits.length) lines.push('', `_performance: ${bits.join(' · ')}_`);
  }

  if (m.agentPhases?.length) {
    const phases = m.agentPhases.map((p) => p.label || p.type || '').filter(Boolean);
    if (phases.length) lines.push('', `_phases: ${phases.join(' → ')}_`);
  }

  return lines;
}

/** Render selected sessions as a full readable Markdown transcript. */
export function sessionsToMarkdown(entries: SessionExport[]): string {
  const parts: string[] = [];
  parts.push(`# LocalMind chat export`);
  parts.push(`_${entries.length} chat${entries.length === 1 ? '' : 's'} · exported ${new Date().toISOString()}_`);

  for (const { session, history, todos } of entries) {
    parts.push('');
    parts.push('---');
    parts.push('');
    parts.push(`## ${session.title || 'Untitled chat'}`);
    const meta = [
      session.formattedDate || session.timestamp,
      `${session.messageCount} message${session.messageCount === 1 ? '' : 's'}`,
    ]
      .filter(Boolean)
      .join(' · ');
    if (meta) parts.push(`_${meta}_`);

    parts.push(...todosToMarkdown(todos));

    if (!history.length) {
      parts.push('');
      parts.push('_No messages._');
      continue;
    }

    for (const m of history) {
      parts.push(...messageToMarkdown(m));
    }
  }
  parts.push('');
  return parts.join('\n');
}

/** Render selected sessions as a structured JSON document with ALL fields. */
export function sessionsToJson(entries: SessionExport[]): string {
  const doc = {
    app: 'LocalMind',
    kind: 'chat-export',
    version: 2,
    exportedAt: new Date().toISOString(),
    count: entries.length,
    chats: entries.map(({ session, history, todos }) => ({
      id: session.id,
      title: session.title,
      timestamp: session.timestamp,
      formattedDate: session.formattedDate ?? null,
      messageCount: session.messageCount,
      // B-2026-08-23-3: the session's task checklist now travels with the chat.
      todos: (todos ?? []).map((t) => ({
        id: t.id,
        text: t.text,
        completed: t.completed,
        status: t.status ?? null,
        order: t.order ?? null,
      })),
      messages: history.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
        // Full tool-call timeline: args, output, reasoning, provider, duration.
        toolCalls: m.toolCalls?.map((t) => ({
          id: t.id,
          name: t.name,
          label: t.label,
          status: t.status,
          input: t.input,
          output: t.output,
          error: t.error,
          duration: t.duration,
          iteration: t.iteration,
          todoId: t.todoId,
          reasoning: t.reasoning,
          agent: t.agent,
          provider: t.provider,
        })) ?? undefined,
        thinking: m.thinking ?? undefined,
        acknowledgement: m.acknowledgement ?? undefined,
        error: m.error ?? undefined,
        performance: m.performance ?? undefined,
        agentRuns: m.agentRuns ?? undefined,
        agentPhases: m.agentPhases ?? undefined,
        fileResults: m.fileResults?.map((f) => ({
          id: f.id,
          path: f.path,
          name: 'name' in f ? f.name : f.filename,
          size: 'size' in f ? f.size : undefined,
          type: 'type' in f ? f.type : undefined,
          status: 'status' in f ? f.status : undefined,
        })) ?? undefined,
      })),
    })),
  };
  return JSON.stringify(doc, null, 2);
}

/** A filesystem-safe filename for the export, e.g. localmind-chats-3-2026-08-15.md */
export function exportFilename(format: ExportFormat, count: number, now: Date = new Date()): string {
  const date = now.toISOString().slice(0, 10);
  const ext = format === 'json' ? 'json' : 'md';
  return `localmind-chats-${count}-${date}.${ext}`;
}

/** Serialize entries in the requested format. */
export function serializeSessions(entries: SessionExport[], format: ExportFormat): string {
  return format === 'json' ? sessionsToJson(entries) : sessionsToMarkdown(entries);
}

/**
 * Trigger a browser/Electron download of text content. In the Electron
 * renderer this opens the OS save dialog (default download behavior). Returns
 * false when the DOM APIs are unavailable (e.g. during SSR/tests).
 */
export function downloadTextFile(filename: string, content: string, mime: string): boolean {
  if (typeof document === 'undefined' || typeof URL === 'undefined' || !URL.createObjectURL) {
    return false;
  }
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke on the next tick so the download has a chance to start.
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return true;
}

const MIME: Record<ExportFormat, string> = {
  markdown: 'text/markdown;charset=utf-8',
  json: 'application/json;charset=utf-8',
};

/**
 * Fetch each session's history (+ optional todo checklist), serialize the
 * selected sessions, and download the result. `fetchHistory` and `fetchTodos`
 * are injected so this stays testable and decoupled from the client. Returns
 * the number of sessions exported.
 */
export async function exportSessions(
  sessions: Session[],
  ids: string[],
  format: ExportFormat,
  fetchHistory: (id: string) => Promise<ChatMessage[]>,
  fetchTodos?: (id: string) => Promise<TodoItem[]>,
): Promise<number> {
  const chosen = sessions.filter((s) => ids.includes(s.id));
  const entries: SessionExport[] = await Promise.all(
    chosen.map(async (session) => {
      let history: ChatMessage[] = [];
      try {
        history = await fetchHistory(session.id);
      } catch {
        history = []; // a single unreachable session must not sink the export
      }
      let todos: TodoItem[] | undefined;
      if (fetchTodos) {
        try {
          todos = await fetchTodos(session.id);
        } catch {
          todos = [];
        }
      }
      return { session, history, todos };
    }),
  );
  const content = serializeSessions(entries, format);
  downloadTextFile(exportFilename(format, entries.length), content, MIME[format]);
  return entries.length;
}
