/**
 * ThoughtText — the model's reasoning, set apart from the answer.
 *
 * Reasoning can run to pages. It is shown quietly (muted, with a rule down the side, so it
 * is never mistaken for the reply) and cut to a few lines with a toggle for the rest.
 */

import { useState } from 'react';

const PREVIEW_LINES = 5;

export function ThoughtText({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const body = text.trim();
  if (!body) return null;
  const lines = body.split('\n');
  const long = lines.length > PREVIEW_LINES;
  const shown = all || !long ? body : lines.slice(0, PREVIEW_LINES).join('\n');
  return (
    <div className="my-1 border-l-2 border-white/10 pl-3" data-testid="thought-text">
      <p className="whitespace-pre-wrap break-words text-[11px] italic leading-relaxed text-brand-green-muted">{shown}</p>
      {long && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-0.5 text-[10px] text-brand-blue hover:text-brand-blue-bright">
          {all ? 'Show less' : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}
