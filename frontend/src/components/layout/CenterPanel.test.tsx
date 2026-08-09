import { describe, expect, it } from 'vitest';
import { findRetryPrompt } from './CenterPanel';
import { ChatMessage as ChatMessageType } from '@/types';

function msg(role: 'user' | 'assistant', content: string, id: string): ChatMessageType {
  return { id, role, content, timestamp: '12:00' } as ChatMessageType;
}

describe('findRetryPrompt', () => {
  it('returns the user prompt preceding an assistant message', () => {
    const messages = [
      msg('user', 'what is my disk space?', 'u1'),
      msg('assistant', 'Here is the answer', 'a1'),
    ];
    expect(findRetryPrompt(messages, 1)).toBe('what is my disk space?');
  });

  it('walks back past intermediate messages to find the last user prompt', () => {
    const messages = [
      msg('user', 'first prompt', 'u1'),
      msg('assistant', 'first answer', 'a1'),
      msg('user', 'second prompt', 'u2'),
      msg('assistant', 'second answer', 'a2'),
    ];
    expect(findRetryPrompt(messages, 3)).toBe('second prompt');
  });

  it('returns undefined for user messages', () => {
    const messages = [msg('user', 'hi', 'u1')];
    expect(findRetryPrompt(messages, 0)).toBeUndefined();
  });

  it('returns undefined for an assistant message with no preceding user content', () => {
    const messages = [msg('assistant', 'standalone', 'a0')];
    expect(findRetryPrompt(messages, 0)).toBeUndefined();
  });

  it('skips empty user content', () => {
    const messages = [msg('user', '', 'u0'), msg('assistant', 'answer', 'a1')];
    expect(findRetryPrompt(messages, 1)).toBeUndefined();
  });
});
