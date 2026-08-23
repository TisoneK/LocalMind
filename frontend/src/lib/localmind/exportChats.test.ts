import { describe, it, expect, vi } from 'vitest';
import {
  sessionsToMarkdown,
  sessionsToJson,
  serializeSessions,
  exportFilename,
  exportSessions,
  type SessionExport,
} from './exportChats';
import type { Session, ChatMessage, TodoItem, ToolCall } from '@/types';

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

const todos: TodoItem[] = [
  { id: 't1', text: 'create the folder', completed: true, status: 'done' },
  { id: 't2', text: 'write a.txt', completed: false, status: 'pending' },
];

const richToolCall: ToolCall = {
  id: 'tc-1',
  name: 'shell',
  label: 'Running: ls',
  status: 'done',
  input: 'ls -la',
  output: 'total 8\ndrwxr-xr-x demo-todo',
  duration: 120,
  iteration: 1,
  reasoning: 'list the folder to check state',
  provider: 'local',
};

const richHistory: ChatMessage[] = [
  {
    id: 'm1',
    role: 'user',
    content: 'create the project',
    timestamp: '10:00',
  },
  {
    id: 'm2',
    role: 'assistant',
    content: 'Done — created demo-todo.',
    timestamp: '10:01',
    isAgent: true,
    thinking: 'I should check the folder first.',
    acknowledgement: 'Working on it',
    toolCalls: [richToolCall],
    fileResults: [
      { id: 'fr-1', filename: 'a.txt', path: 'demo-todo/a.txt', status: 'created' },
    ],
    performance: { latencyMs: 1500, promptTokens: 100, completionTokens: 50, tokensPerSecond: 33.3 },
    agentPhases: [{ id: 'p1', type: 'working', label: 'working', timestamp: 1784200000 }],
  },
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

  it('renders the todo checklist when present', () => {
    const md = sessionsToMarkdown([{ session: session(), history, todos }]);
    expect(md).toContain('**Task checklist:**');
    expect(md).toContain('- [x] create the folder');
    expect(md).toContain('- [ ] write a.txt');
  });

  it('skips the checklist when absent', () => {
    const md = sessionsToMarkdown([{ session: session(), history }]);
    expect(md).not.toContain('Task checklist');
  });

  it('renders full session info: thinking, tool args/output, files, metrics', () => {
    const md = sessionsToMarkdown([{ session: session(), history: richHistory }]);
    expect(md).toContain('💭 Reasoning');
    expect(md).toContain('I should check the folder first.');
    expect(md).toContain('**Tool steps:**');
    expect(md).toContain('**Running: ls** [done] · 120ms · local');
    expect(md).toContain('input: `ls -la`');
    expect(md).toContain('output: total 8');
    expect(md).toContain('why: list the folder to check state');
    expect(md).toContain('**Files:**');
    expect(md).toContain('demo-todo/a.txt');
    expect(md).toContain('_performance: 1500ms · 100 in · 50 out · 33.3 tok/s_');
    expect(md).toContain('_phases: working_');
    expect(md).toContain('_acknowledgement: Working on it_');
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

  it('includes todos and every persisted message field', () => {
    const json = sessionsToJson([{ session: session(), history: richHistory, todos }]);
    const doc = JSON.parse(json);
    const chat = doc.chats[0];
    expect(chat.todos).toHaveLength(2);
    expect(chat.todos[0]).toMatchObject({ id: 't1', text: 'create the folder', completed: true });

    const msg = chat.messages[1];
    expect(msg.thinking).toBe('I should check the folder first.');
    expect(msg.acknowledgement).toBe('Working on it');
    expect(msg.toolCalls[0]).toMatchObject({
      name: 'shell',
      input: 'ls -la',
      duration: 120,
      reasoning: 'list the folder to check state',
      provider: 'local',
    });
    expect(msg.toolCalls[0].output).toContain('total 8');
    expect(msg.fileResults[0]).toMatchObject({ path: 'demo-todo/a.txt', name: 'a.txt' });
    expect(msg.performance).toMatchObject({ latencyMs: 1500, promptTokens: 100 });
    expect(msg.agentPhases).toHaveLength(1);
  });

  it('bumps the schema version when the shape grows', () => {
    const doc = JSON.parse(sessionsToJson([{ session: session(), history }]));
    expect(doc.version).toBe(2);
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

  it('fetches todos for each selected session when provided', async () => {
    const sessions = [session({ id: 'a', title: 'A' })];
    const fetchHistory = vi.fn(async () => [] as ChatMessage[]);
    const fetchTodos = vi.fn(async (id: string) => [
      { id: 't1', text: `todo for ${id}`, completed: false } as TodoItem,
    ]);
    const n = await exportSessions(sessions, ['a'], 'markdown', fetchHistory, fetchTodos);
    expect(n).toBe(1);
    expect(fetchTodos).toHaveBeenCalledTimes(1);
    expect(fetchTodos).toHaveBeenCalledWith('a');
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

  it('survives a failing todos fetch', async () => {
    const sessions = [session({ id: 'a' })];
    const fetchHistory = vi.fn(async () => [] as ChatMessage[]);
    const fetchTodos = vi.fn(async () => {
      throw new Error('todos unreachable');
    });
    const n = await exportSessions(sessions, ['a'], 'markdown', fetchHistory, fetchTodos);
    expect(n).toBe(1);
  });
});
