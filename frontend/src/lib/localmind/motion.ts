/**
 * Shared motion vocabulary for the realtime-alive-ui surfaces
 * (Session 216). The chat Actions timeline, thinking stream, plan
 * checklist, panel action trace, and agent workspace all animate items
 * in with the same reduced-motion-aware "fade + slide" so the UI reads as
 * one live system. This hook is the single source of that pattern.
 *
 * Usage:
 *   const { reduce, enter } = useEnterMotion();
 *   <motion.div layout={!reduce} {...enter({ x: -6 })} className="…" />
 *
 * `reduce` is exposed so callers can also gate non-enter motion
 * (pulses, pings, height collapses, `layout`) on the same preference.
 */

import { useReducedMotion } from 'framer-motion';

export interface EnterOptions {
  /** Horizontal offset (px) the item slides in from. Default 0. */
  x?: number;
  /** Vertical offset (px) the item slides in from. Default 0. */
  y?: number;
  /** Enter duration in seconds. Default 0.2. */
  duration?: number;
}

export interface EnterMotionProps {
  initial: false | { opacity: number; x: number; y: number };
  animate: { opacity: number; x: number; y: number };
  transition: { duration: number; ease: 'easeOut' };
}

export function useEnterMotion() {
  const reduce = !!useReducedMotion();

  /**
   * Spreadable framer-motion props for an item entering the view. Under
   * reduced motion, `initial` is `false` so the item simply appears
   * (framer-motion skips the enter transition).
   */
  const enter = (opts: EnterOptions = {}): EnterMotionProps => ({
    initial: reduce ? false : { opacity: 0, x: opts.x ?? 0, y: opts.y ?? 0 },
    animate: { opacity: 1, x: 0, y: 0 },
    transition: { duration: opts.duration ?? 0.2, ease: 'easeOut' },
  });

  return { reduce, enter };
}
