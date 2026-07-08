/**
 * Shared utility helpers for the shadcn/ui component library.
 *
 * The `cn` function merges Tailwind CSS class names intelligently,
 * resolving conflicts (later classes win) using tailwind-merge.
 *
 * This module is imported by every component in components/ui/.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge Tailwind class names, resolving conflicts.
 *
 * @example
 * cn('px-2 py-1', condition && 'bg-red-500', 'px-4')
 * // → 'py-1 bg-red-500 px-4'  (px-4 wins over px-2)
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
