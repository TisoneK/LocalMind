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

/**
 * After file work the backend appends a verification footer to the answer: a "✓ 1/1 criteria
 * met (file exists at …)" line and a "📁 Files:" list. The chat already shows the same facts as a
 * diff card and in the Files panel, so the footer only repeats them a third and fourth time
 * (with long paths). Hide it from the display; the stored text is unchanged.
 */
export function stripVerificationFooter(content: string): string {
  return content
    .replace(/\n*✓\s*\d+\/\d+\s+criteria met[^\n]*(?:\n(?![\n#>*-]|📁)[^\n]*)?/g, '')
    .replace(/\n*📁\s*Files:\s*\n(?:\s*[-•*][^\n]*\n?)+/g, '')
    .trim();
}
