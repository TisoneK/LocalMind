import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { STARTERS, WelcomeScreen } from './WelcomeScreen';

describe('WelcomeScreen', () => {
  it('sends the starter prompt when a card is clicked', () => {
    const onPick = vi.fn();
    render(<WelcomeScreen onPick={onPick} />);
    fireEvent.click(screen.getByText(STARTERS[0].label));
    expect(onPick).toHaveBeenCalledWith(STARTERS[0].prompt);
  });

  it('is not only about code: covers machine, web, files and memory', () => {
    const labels = STARTERS.map((s) => s.label).join(' ');
    expect(labels).toMatch(/machine/i);
    expect(labels).toMatch(/look/i);
    expect(labels).toMatch(/file/i);
    expect(labels).toMatch(/remember/i);
  });
});
