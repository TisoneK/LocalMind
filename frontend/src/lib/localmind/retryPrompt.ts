import type { ChatMessage } from '@/types';

/**
 * Find the user prompt that precedes an assistant message so Retry can
 * re-send it (regenerate semantics: append a new turn with the same prompt;
 * there is no backend replace/regenerate endpoint). Returns undefined for
 * user messages or when no preceding user message has content.
 */
export function findRetryPrompt(messages: ChatMessage[], index: number): string | undefined {
  if (messages[index]?.role !== 'assistant') return undefined;
  for (let j = index - 1; j >= 0; j--) {
    const prev = messages[j];
    if (prev.role === 'user' && prev.content) {
      return prev.content;
    }
  }
  return undefined;
}
