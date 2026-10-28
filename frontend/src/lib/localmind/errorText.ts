/**
 * When a reply fails, the backend sends a friendly one-line fallback as ordinary answer
 * text alongside the structured error, so a turn can never end on an empty bubble. The chat
 * shows the structured error as a card, so that line just repeats it. Remove it when a card is
 * showing; keep any real answer text that came before the failure.
 */

const FALLBACKS = [
  /⚠️?\s*The model ran into an issue\.\s*Please try again,?\s*or switch to a larger model for this task\.?/gi,
  /The model provider rate-limited my request\.\s*Please try again in a moment\.?/gi,
  // Code-aware fallbacks (provider-death honesty): the backend now names the
  // provider and the canonical code instead of the generic try-again line.
  /⚠️?\s*[^\n]*?returned [`']?[a-z_]+[`']?; this turn can't continue because the failure is not retryable\.?/gi,
  /⚠️?\s*[^\n]*?returned [`']?[a-z_]+[`']? \(not retryable\); this turn can't continue\.?/gi,
  /I gathered the information you asked for, but [^\n]*?returned [`']?[a-z_]+[`']? \(not retryable\)[^\n]*?this turn can't continue\.?/gi,
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

/**
 * A failed tool's output carries text written for the MODEL, not for you: a
 * "[Tool 'shell' returned error_type='command_failed']" header and a "[RECOVERY]: …" paragraph
 * telling it how to retry. Show only what the command itself said.
 */
export function cleanToolFailure(text: string): string {
  return text
    .replace(/^\s*\[Tool '[^']*' returned error_type='[^']*'\]\s*/i, '')
    .replace(/\n*\s*\[RECOVERY\]:[\s\S]*$/i, '')
    .replace(/^Command failed:\s*/i, '')
    .replace(/^-{3,}\s*$/gm, '')
    .trim();
}

/** Loop-internal reasons an acceptance check was unmet, put in words for the person watching. */
export function friendlyUnmet(item: string): string {
  if (/^(model )?narrated (an action plan|a pending action)/i.test(item)) {
    return 'it said what it would do instead of doing it';
  }
  return item;
}

/**
 * A replanning row is the agent correcting course, which is normal and usually invisible work —
 * not a warning. Say so: "Adjusting the approach" with the reason, not "Replanning — analyze
 * criteria unmet" in amber, which reads like something broke.
 */
export function friendlyReplan(label: string, detail?: string): { label: string; detail?: string } {
  if (!/^replanning/i.test(label)) return { label, detail };
  const reason = detail?.replace(/^unmet:\s*/i, '').trim();
  return { label: 'Adjusting the approach', detail: reason ? `Because ${reason}` : undefined };
}
