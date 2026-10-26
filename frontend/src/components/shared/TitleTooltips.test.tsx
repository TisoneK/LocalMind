import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { placeTip } from '@/lib/localmind/titleTooltip';
import { TitleTooltips } from './TitleTooltips';

describe('TitleTooltips', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('shows a styled tooltip from a title, hides the native one, and puts the title back', () => {
    render(
      <>
        <button title="Copy this reply">Copy</button>
        <TitleTooltips />
      </>,
    );
    const btn = screen.getByText('Copy');
    fireEvent.pointerOver(btn);
    expect(btn).not.toHaveAttribute('title'); // native box suppressed
    expect(screen.queryByTestId('app-tooltip')).toBeNull(); // not instant
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(screen.getByTestId('app-tooltip')).toHaveTextContent('Copy this reply');
    fireEvent.pointerOut(btn, { relatedTarget: document.body });
    expect(screen.queryByTestId('app-tooltip')).toBeNull();
    expect(btn).toHaveAttribute('title', 'Copy this reply');
  });

  it('does not appear when the pointer leaves before the delay', () => {
    render(
      <>
        <button title="Hold on">x</button>
        <TitleTooltips />
      </>,
    );
    const btn = screen.getByText('x');
    fireEvent.pointerOver(btn);
    fireEvent.pointerOut(btn, { relatedTarget: document.body });
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(screen.queryByTestId('app-tooltip')).toBeNull();
  });

  it('closes on click, so it never lingers over what you just pressed', () => {
    render(
      <>
        <button title="Stop">s</button>
        <TitleTooltips />
      </>,
    );
    const btn = screen.getByText('s');
    fireEvent.pointerOver(btn);
    act(() => {
      vi.advanceTimersByTime(400);
    });
    fireEvent.pointerDown(btn);
    expect(screen.queryByTestId('app-tooltip')).toBeNull();
  });
});

describe('placeTip', () => {
  it('sits above, or below when there is no room above', () => {
    expect(placeTip({ left: 400, right: 440, top: 300, bottom: 320 }, 1000).below).toBe(false);
    expect(placeTip({ left: 400, right: 440, top: 20, bottom: 40 }, 1000).below).toBe(true);
  });
  it('stays inside the window near the edges', () => {
    const { x } = placeTip({ left: 0, right: 20, top: 300, bottom: 320 }, 1000);
    expect(x).toBeGreaterThanOrEqual(140 + 8);
    const right = placeTip({ left: 980, right: 1000, top: 300, bottom: 320 }, 1000);
    expect(right.x).toBeLessThanOrEqual(1000 - 140 - 8);
  });
});
