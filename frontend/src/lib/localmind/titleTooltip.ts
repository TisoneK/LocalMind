// Title-tooltip geometry — pure logic (the TitleTooltips component file
// exports only its component).

export const SHOW_DELAY_MS = 350;
export const MARGIN = 8;
export const MAX_WIDTH = 280;

/** Where to put a tooltip for `rect`: centred over it, or under it when there is no room above. */
export function placeTip(rect: { left: number; right: number; top: number; bottom: number }, viewportWidth: number) {
  const below = rect.top < 56;
  const half = MAX_WIDTH / 2;
  const centre = (rect.left + rect.right) / 2;
  const x = Math.min(Math.max(centre, half + MARGIN), viewportWidth - half - MARGIN);
  return { x, y: below ? rect.bottom + MARGIN : rect.top - MARGIN, below };
}
