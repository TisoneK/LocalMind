/**
 * Vitest setup for component tests.
 *
 * Registers @testing-library/jest-dom matchers (toBeInTheDocument, etc.)
 * and stubs browser APIs that shadcn/radix + recharts components touch
 * during render but that jsdom does not implement (matchMedia,
 * ResizeObserver).
 */
import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';

// Radix modal menus set body `pointer-events: none` while open and only clear it when they
// close themselves. A test that unmounts with a menu still open leaves it behind, and the next
// menu in the same file then never opens. Reset it (and the scroll lock) between tests.
afterEach(() => {
  if (typeof document === 'undefined') return;
  document.body.style.pointerEvents = '';
  document.body.removeAttribute('data-scroll-locked');
});

if (typeof window !== 'undefined') {
  // matchMedia — used by use-mobile / responsive hooks and radix dialogs.
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }

  // ResizeObserver — used by recharts and some layout components.
  if (!(window as unknown as Record<string, unknown>).ResizeObserver) {
    class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    (window as unknown as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
  }

  // scrollTo — jsdom does not implement Element.scrollTo. CenterPanel's
  // messages-container effect calls container.scrollTo({behavior:'smooth'})
  // on mount; without this stub it throws and fails every render test.
  if (typeof Element !== 'undefined' && !Element.prototype.scrollTo) {
    Element.prototype.scrollTo = () => {};
  }

  // Pointer-capture and scrollIntoView — Radix menus and popovers call these when they open;
  // jsdom does not implement them, so a menu never appears in a test without the stubs.
  if (typeof Element !== 'undefined') {
    const proto = Element.prototype as unknown as Record<string, unknown>;
    if (!proto.hasPointerCapture) proto.hasPointerCapture = () => false;
    if (!proto.setPointerCapture) proto.setPointerCapture = () => {};
    if (!proto.releasePointerCapture) proto.releasePointerCapture = () => {};
    if (!proto.scrollIntoView) proto.scrollIntoView = () => {};
  }

  // Object URLs — on Node 24 the built-in Blob is not the Blob jsdom's URL.createObjectURL
  // expects, so the real call throws. Downloads are exercised through this stub.
  URL.createObjectURL = () => 'blob:mock';
  URL.revokeObjectURL = () => {};
}
