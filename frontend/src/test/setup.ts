/**
 * Vitest setup for component tests.
 *
 * Registers @testing-library/jest-dom matchers (toBeInTheDocument, etc.)
 * and stubs browser APIs that shadcn/radix + recharts components touch
 * during render but that jsdom does not implement (matchMedia,
 * ResizeObserver).
 */
import '@testing-library/jest-dom/vitest';

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
}
