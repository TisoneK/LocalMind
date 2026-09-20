/**
 * TitleTooltips — one themed tooltip for the whole app.
 *
 * The app labels hundreds of controls with a native `title`, which the browser draws as a
 * plain grey box after a long delay, with no wrapping control and none of our styling. Rather
 * than rewrite every control, this layer takes over: while the pointer (or keyboard focus) is on
 * an element with a `title`, the title is lifted into a styled tooltip and put back afterwards,
 * so the attribute — and screen readers — keep working.
 */

import { useEffect, useRef, useState } from 'react';

interface Tip {
  text: string;
  x: number;
  y: number;
  below: boolean;
}

const SHOW_DELAY_MS = 350;
const MARGIN = 8;
const MAX_WIDTH = 280;

/** Where to put a tooltip for `rect`: centred over it, or under it when there is no room above. */
export function placeTip(rect: { left: number; right: number; top: number; bottom: number }, viewportWidth: number) {
  const below = rect.top < 56;
  const half = MAX_WIDTH / 2;
  const centre = (rect.left + rect.right) / 2;
  const x = Math.min(Math.max(centre, half + MARGIN), viewportWidth - half - MARGIN);
  return { x, y: below ? rect.bottom + MARGIN : rect.top - MARGIN, below };
}

function titledAncestor(target: EventTarget | null): HTMLElement | null {
  const el = target instanceof Element ? target.closest<HTMLElement>('[title], [data-tip-title]') : null;
  return el;
}

export function TitleTooltips() {
  const [tip, setTip] = useState<Tip | null>(null);
  const active = useRef<HTMLElement | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const restore = () => {
      window.clearTimeout(timer.current);
      const el = active.current;
      if (el && el.dataset.tipTitle !== undefined) {
        el.setAttribute('title', el.dataset.tipTitle);
        delete el.dataset.tipTitle;
      }
      active.current = null;
      setTip(null);
    };

    const start = (el: HTMLElement) => {
      if (active.current === el) return;
      restore();
      const text = el.getAttribute('title') ?? el.dataset.tipTitle ?? '';
      if (!text.trim()) return;
      // Lift the title so the browser doesn't draw its own box on top of ours.
      el.dataset.tipTitle = text;
      el.removeAttribute('title');
      active.current = el;
      timer.current = window.setTimeout(() => {
        const rect = el.getBoundingClientRect();
        setTip({ text, ...placeTip(rect, window.innerWidth) });
      }, SHOW_DELAY_MS);
    };

    const onOver = (e: Event) => {
      const el = titledAncestor(e.target);
      if (el) start(el);
      else if (active.current) restore();
    };
    const onOut = (e: Event) => {
      const el = active.current;
      const to = (e as MouseEvent).relatedTarget as Node | null;
      if (el && !(to && el.contains(to))) restore();
    };

    document.addEventListener('pointerover', onOver);
    document.addEventListener('pointerout', onOut);
    document.addEventListener('focusin', onOver);
    document.addEventListener('focusout', restore);
    document.addEventListener('pointerdown', restore);
    document.addEventListener('keydown', restore);
    window.addEventListener('scroll', restore, true);
    return () => {
      restore();
      document.removeEventListener('pointerover', onOver);
      document.removeEventListener('pointerout', onOut);
      document.removeEventListener('focusin', onOver);
      document.removeEventListener('focusout', restore);
      document.removeEventListener('pointerdown', restore);
      document.removeEventListener('keydown', restore);
      window.removeEventListener('scroll', restore, true);
    };
  }, []);

  if (!tip) return null;
  const paragraphs = tip.text.split(/\n+/).filter(Boolean);
  return (
    <div
      role="tooltip"
      data-testid="app-tooltip"
      className="pointer-events-none fixed z-[100] rounded-md border border-brand-border bg-brand-bg-code/95 px-2.5 py-1.5 text-[11px] leading-snug text-brand-green-soft shadow-xl shadow-black/40 backdrop-blur animate-in fade-in-0 zoom-in-95"
      style={{
        left: tip.x,
        top: tip.y,
        maxWidth: MAX_WIDTH,
        transform: tip.below ? 'translateX(-50%)' : 'translate(-50%, -100%)',
      }}
    >
      {paragraphs.map((p, i) => (
        <p key={i} className={i > 0 ? 'mt-1' : undefined}>
          {p}
        </p>
      ))}
    </div>
  );
}
