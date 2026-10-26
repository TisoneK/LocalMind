/** True for the ⌘K / Ctrl+K chord. */
export function isPaletteShortcut(e: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey'>): boolean {
  return (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k';
}
