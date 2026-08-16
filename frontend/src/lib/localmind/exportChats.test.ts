import { describe, it, expect, vi } from 'vitest';
import {
  sessionsToMarkdown,
  sessionsToJson,
  serializeSessions,
  exportFilename,
  exportSessions,
  type SessionExport,
} from './exportChats';
import type { Session, ChatMessage } from '@/types';

function session(over: Partial<Session> = {}): Session {
  return {
    id: 's1',
    title: 'My chat',
    lastMessage: 'hi',
    timestamp: '2026-08-15T10:00:00Z',
    messageCount: 2,
    active: false,
    ...over,
  };
}

const history: ChatMessage[] = [
  { id: 'm1', role: 'user', content: 'Hello there', timestamp: '10:00' },
  { id: 'm2', role: 'assistant', content: 'Hi! How can I help?', timestamp: '10:01' },
];

describe('sessionsToMarkdown', () => {
  it('renders titles, roles, and content', () => {
    const entries: SessionExport[] = [{ session: session(), history }];
    const md = sessionsToMarkdown(entries);
    expect(md).toContain('# LocalMind chat export');
    expect(md).toContain('## My chat');
    expect(md).toContain('**User**');
    expect(md).toContain('Hello there');
    expect(md).toContain('**Assistant**');
    expect(md).toContain('Hi! How can I help?');
  });

  it('notes empty histories', () => {
    const md = sessionsToMarkdown([{ session: session({ messageCount: 0 }), history: [] }]);
    expect(md).toContain('_No messages._');
  });
});

describe('sessionsToJson', () => {
  it('produces a structured, parseable document', () => {
    const json = sessionsToJson([{ session: session(), history }]);
    const doc = JSON.parse(json);
    expect(doc.kind).toBe('chat-export');
    expect(doc.count).toBe(1);
    expect(doc.chats[0].id).toBe('s1');
    expect(doc.chats[0].messages).toHaveLength(2);
    expect(doc.chats[0].messages[0].role).toBe('user');
  });
});

describe('serializeSessions / exportFilename', () => {
  it('dispatches by format', () => {
    const entries = [{ session: session(), history }];
    expect(serializeSessions(entries, 'json')).toContain('"kind": "chat-export"');
    expect(serializeSessions(entries, 'markdown')).toContain('# LocalMind chat export');
  });

  it('builds a dated, extension-correct filename', () => {
    const now = new Date('2026-08-15T12:00:00Z');
    expect(exportFilename('markdown', 3, now)).toBe('localmind-chats-3-2026-08-15.md');
    expect(exportFilename('json', 1, now)).toBe('localmind-chats-1-2026-08-15.json');
  });
});

describe('exportSessions', () => {
  it('fetches only selected sessions and reports the count', async () => {
    const sessions = [session({ id: 'a', title: 'A' }), session({ id: 'b', title: 'B' }), session({ id: 'c', title: 'C' })];
    const fetchHistory = vi.fn(async (id: string) => [
      { id: `${id}-1`, role: 'user', content: `msg ${id}`, timestamp: '10:00' } as ChatMessage,
    ]);
    const n = await exportSessions(sessions, ['a', 'c'], 'json', fetchHistory);
    expect(n).toBe(2);
    expect(fetchHistory).toHaveBeenCalledTimes(2);
    expect(fetchHistory).toHaveBeenCalledWith('a');
    expect(fetchHistory).toHaveBeenCalledWith('c');
    expect(fetchHistory).not.toHaveBeenCalledWith('b');
  });

  it('survives a failing history fetch for one session', async () => {
    const sessions = [session({ id: 'a' }), session({ id: 'b' })];
    const fetchHistory = vi.fn(async (id: string) => {
      if (id === 'b') throw new Error('unreachable');
      return [{ id: 'a-1', role: 'user', content: 'ok', timestamp: '10:00' } as ChatMessage];
    });
    const n = await exportSessions(sessions, ['a', 'b'], 'markdown', fetchHistory);
    expect(n).toBe(2); // both still included; b just has empty history
  });
});
