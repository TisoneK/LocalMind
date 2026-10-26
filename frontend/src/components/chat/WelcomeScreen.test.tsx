import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { STARTERS, greetingFor } from '@/lib/localmind/welcomeContent';
import { WelcomeScreen } from './WelcomeScreen';

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

  it('tells the truth about the engine and holds the starters until it is up', () => {
    const onPick = vi.fn();
    const { rerender } = render(<WelcomeScreen onPick={onPick} status="checking" />);
    expect(screen.getByTestId('welcome-status')).toHaveTextContent(/starting the local engine/i);
    fireEvent.click(screen.getByText(STARTERS[0].label));
    expect(onPick).not.toHaveBeenCalled();
    rerender(<WelcomeScreen onPick={onPick} status="offline" />);
    expect(screen.getByTestId('welcome-status')).toHaveTextContent(/can't reach/i);
    rerender(<WelcomeScreen onPick={onPick} status="online" />);
    expect(screen.getByTestId('welcome-status')).toHaveTextContent(/ready/i);
    fireEvent.click(screen.getByText(STARTERS[1].label));
    expect(onPick).toHaveBeenCalledWith(STARTERS[1].prompt);
  });

  it('shows how many memories it holds, only when there are some', () => {
    const { rerender } = render(<WelcomeScreen onPick={vi.fn()} memoryCount={0} />);
    expect(screen.queryByText(/^\d+ memor/)).toBeNull();
    rerender(<WelcomeScreen onPick={vi.fn()} memoryCount={3} />);
    expect(screen.getByText('3 memories')).toBeInTheDocument();
  });

  it('greets by time of day', () => {
    expect([greetingFor(3), greetingFor(9), greetingFor(14), greetingFor(20)]).toEqual([
      'Still up?', 'Good morning', 'Good afternoon', 'Good evening',
    ]);
  });
});
