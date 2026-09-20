import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ChatInput } from './ChatInput';

const base = { onSend: vi.fn(), onAbort: vi.fn(), isStreaming: false };

describe('ChatInput editing', () => {
  it('loads the prefilled message, shows the banner, and sends it through onEditSend', () => {
    const onEditSend = vi.fn();
    const onSend = vi.fn();
    render(<ChatInput {...base} onSend={onSend} prefill={{ text: 'old wording', key: 1 }} onEditSend={onEditSend} />);
    const box = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(box.value).toBe('old wording');
    expect(screen.getByTestId('editing-banner')).toBeInTheDocument();
    fireEvent.change(box, { target: { value: 'new wording' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(onEditSend).toHaveBeenCalledWith('new wording');
    expect(onSend).not.toHaveBeenCalled();
    expect(screen.queryByTestId('editing-banner')).toBeNull();
  });

  it('Esc cancels the edit and clears the box', () => {
    const onEditCancel = vi.fn();
    render(<ChatInput {...base} prefill={{ text: 'x', key: 2 }} onEditSend={vi.fn()} onEditCancel={onEditCancel} />);
    const box = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.keyDown(box, { key: 'Escape' });
    expect(onEditCancel).toHaveBeenCalled();
    expect(box.value).toBe('');
  });
});
