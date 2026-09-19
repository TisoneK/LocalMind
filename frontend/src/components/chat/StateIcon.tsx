import { Check, Circle, Loader2, X } from 'lucide-react';
import type { StepState } from '@/lib/localmind/turnTimeline';

/** The one status glyph used by every live-activity surface (turn feed, rail). */
export function StateIcon({ state, className = 'h-3.5 w-3.5' }: { state: StepState; className?: string }) {
  if (state === 'running') return <Loader2 className={`${className} animate-spin text-brand-amber`} aria-label="running" />;
  if (state === 'failed') return <X className={`${className} text-red-400`} aria-label="failed" />;
  if (state === 'pending') return <Circle className={`${className} text-brand-green-muted`} aria-label="pending" />;
  return <Check className={`${className} text-brand-green`} aria-label="done" />;
}
