/**
 * When a reply fails, the backend sends a friendly one-line fallback as ordinary answer
 * text alongside the structured error, so a turn can never end on an empty bubble. The chat
 * shows the structured error as a card, so that line just repeats it. Remove it when a card is
 * showing; keep any real answer text that came before the failure.
 */

const FALLBACKS = [
  /⚠️?\s*The model ran into an issue\.\s*Please try again,?\s*or switch to a larger model for this task\.?/gi,
  /The model provider rate-limited my request\.\s*Please try again in a moment\.?/gi,
];

export function stripFallbackErrorText(content: string): string {
  let out = content;
  for (const re of FALLBACKS) out = out.replace(re, '');
  return out.trim();
}
