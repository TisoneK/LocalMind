import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { InjectedItemRow } from './CenterPanel';
import type { InjectedItem } from '@/types';

const item = (over: Partial<InjectedItem>): InjectedItem => ({
  kind: 'environment.clock',
  source: 'system clock',
  text: '- Current date: Wednesday, October 28, 2026',
  chars: 41,
  surface: 'loop_turn',
  ...over,
});

describe('InjectedItemRow (§U item 3)', () => {
  it('opens the exact injected text with its producer', () => {
    render(<InjectedItemRow item={item({})} />);
    fireEvent.click(screen.getByText('Clock'));
    expect(screen.getByText(/source: system clock/)).toBeInTheDocument();
    expect(screen.getByText(/- Current date: Wednesday, October 28, 2026/)).toBeInTheDocument();
  });

  it('renders an unknown kind opaque instead of hiding it', () => {
    render(<InjectedItemRow item={item({ kind: 'brand_new_kind', source: 'new producer', text: 'raw bytes' })} />);
    // The raw kind name is the label, with the opaque badge next to it —
    // the row is present and expandable, never dropped.
    expect(screen.getByText('brand_new_kind')).toBeInTheDocument();
    expect(screen.getByText('opaque')).toBeInTheDocument();
    fireEvent.click(screen.getByText('brand_new_kind'));
    expect(screen.getByText('raw bytes')).toBeInTheDocument();
  });

  it('a known kind never shows the opaque badge', () => {
    render(<InjectedItemRow item={item({})} />);
    expect(screen.queryByText('opaque')).toBeNull();
  });
});
