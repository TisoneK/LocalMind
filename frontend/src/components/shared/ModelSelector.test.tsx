/**
 * Tests for ModelSelector — the type-to-filter picker.
 *
 * Providers like Zen expose 60+ models; scrolling to reach one is painful and
 * unreliable on macOS. The search box must make any model reachable, and
 * selecting one must call back with its id.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ModelSelector } from './ModelSelector';
import type { ModelOption } from '@/types';

const models: ModelOption[] = [
  { id: 'deepseek-v4-flash-free', name: 'deepseek-v4-flash-free', provider: 'zen', size: 'Cloud' },
  { id: 'claude-opus-4-8', name: 'claude-opus-4-8', provider: 'zen', size: 'Cloud' },
  { id: 'nemotron-3-ultra-free', name: 'nemotron-3-ultra-free', provider: 'zen', size: 'Cloud' },
  { id: 'nemotron-3.5-lightning-free', name: 'nemotron-3.5-lightning-free', provider: 'zen', size: 'Cloud' },
  { id: 'gpt-5', name: 'gpt-5', provider: 'zen', size: 'Cloud' },
];

function open(onModelChange = vi.fn()) {
  render(<ModelSelector selectedModel="deepseek-v4-flash-free" onModelChange={onModelChange} models={models} />);
  fireEvent.click(screen.getByTestId('model-selector-trigger'));
  return onModelChange;
}

describe('ModelSelector', () => {
  it('shows all models and a search box when opened', () => {
    open();
    expect(screen.getByTestId('model-search')).toBeInTheDocument();
    expect(screen.getByText('gpt-5')).toBeInTheDocument();
    expect(screen.getByText('nemotron-3-ultra-free')).toBeInTheDocument();
  });

  it('filters the list as the user types', () => {
    open();
    fireEvent.change(screen.getByTestId('model-search'), { target: { value: 'nemotron' } });
    expect(screen.getByText('nemotron-3-ultra-free')).toBeInTheDocument();
    expect(screen.getByText('nemotron-3.5-lightning-free')).toBeInTheDocument();
    // non-matching models are gone
    expect(screen.queryByText('gpt-5')).toBeNull();
    expect(screen.queryByText('claude-opus-4-8')).toBeNull();
  });

  it('shows an empty state when nothing matches', () => {
    open();
    fireEvent.change(screen.getByTestId('model-search'), { target: { value: 'zzznope' } });
    expect(screen.getByText(/No models match/)).toBeInTheDocument();
  });

  it('selecting a filtered model calls back with its id', () => {
    const onModelChange = open();
    fireEvent.change(screen.getByTestId('model-search'), { target: { value: 'nemotron' } });
    fireEvent.click(screen.getByText('nemotron-3-ultra-free'));
    expect(onModelChange).toHaveBeenCalledWith('nemotron-3-ultra-free');
  });

  it('Enter picks the first filtered model', () => {
    const onModelChange = open();
    fireEvent.change(screen.getByTestId('model-search'), { target: { value: 'nemotron' } });
    fireEvent.keyDown(screen.getByTestId('model-search'), { key: 'Enter' });
    expect(onModelChange).toHaveBeenCalledWith('nemotron-3-ultra-free');
  });
});
