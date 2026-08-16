// Export chat sessions to a downloadable file (Markdown or JSON).
//
// The chat list supports selecting multiple sessions and exporting them in one
// file. Serialization is kept pure (no DOM) so it is unit-testable; the actual
// browser download is a thin, separately-testable helper.

import type { ChatMessage, Session } from '@/types';

export type ExportFormat = 'markdown' | 'json';

/** A session paired with its fetched message history. */
export interface SessionExport {
  session: Session;
  history: ChatMessage[];
}

function roleLabel(role: string): string {
  if (role === 'user') return 'User';
  if (role === 'assistant') return 'Assistant';
  if (role === 'system') return 'System';
  return role ? role[0].toUpperCase() + role.slice(1) : 'Unknown';
}

/** Render selected sessions as a single readable Markdown transcript. */
export function sessionsToMarkdown(entries: SessionExport[]): string {
  const parts: string[] = [];
  parts.push(`# LocalMind chat export`);
  parts.push(`_${entries.length} chat${entries.length === 1 ? '' : 's'} · exported ${new Date().toISOString()}_`);

  for (const { session, history } of entries) {
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

    if (!history.length) {
      parts.push('');
      parts.push('_No messages._');
      continue;
    }

    for (const m of history) {
      parts.push('');
      const ts = m.timestamp ? ` _(${m.timestamp})_` : '';
      parts.push(`**${roleLabel(m.role)}**${ts}`);
      parts.push('');
      parts.push(m.content ?? '');
      if (m.toolCalls?.length) {
        const names = m.toolCalls.map((t) => t.name).filter(Boolean).join(', ');
        if (names) parts.push(`\n> 🛠 tools: ${names}`);
      }
    }
  }
  parts.push('');
  return parts.join('\n');
}

/** Render selected sessions as a structured JSON document. */
export function sessionsToJson(entries: SessionExport[]): string {
  const doc = {
    app: 'LocalMind',
    kind: 'chat-export',
    version: 1,
    exportedAt: new Date().toISOString(),
    count: entries.length,
    chats: entries.map(({ session, history }) => ({
      id: session.id,
      title: session.title,
      timestamp: session.timestamp,
      formattedDate: session.formattedDate ?? null,
      messageCount: session.messageCount,
      messages: history.map((m) => ({
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
        toolCalls: m.toolCalls?.map((t) => ({ name: t.name, status: t.status })) ?? undefined,
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
 * Fetch each session's history, serialize the selected sessions, and download
 * the result. `fetchHistory` is injected so this stays testable and decoupled
 * from the client. Returns the number of sessions exported.
 */
export async function exportSessions(
  sessions: Session[],
  ids: string[],
  format: ExportFormat,
  fetchHistory: (id: string) => Promise<ChatMessage[]>,
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
      return { session, history };
    }),
  );
  const content = serializeSessions(entries, format);
  downloadTextFile(exportFilename(format, entries.length), content, MIME[format]);
  return entries.length;
}
