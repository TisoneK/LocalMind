import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { createRef } from 'react';
import { InputContextMenu } from './InputContextMenu';

function stubClipboard({ text = '' } = {}) {
  const writeText = vi.fn().mockResolvedValue(undefined);
  const readText = vi.fn().mockResolvedValue(text);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText, readText },
    configurable: true,
    writable: true,
  });
  return { writeText, readText };
}

async function openContextMenu() {
  await act(async () => {
    fireEvent.contextMenu(screen.getByTestId('editable'));
  });
}

async function renderInput({ value = '', clipboardText = '' } = {}) {
  const onChange = vi.fn();
  const ref = createRef<HTMLTextAreaElement>();
  const { writeText } = stubClipboard({ text: clipboardText });
  render(
    <InputContextMenu textareaRef={ref} value={value} onChange={onChange}>
      <textarea ref={ref} data-testid="editable" defaultValue={value} />
    </InputContextMenu>,
  );
  const el = screen.getByTestId('editable') as HTMLTextAreaElement;
  return { onChange, el, ref, writeText };
}

describe('InputContextMenu', () => {
  beforeEach(() => {
    stubClipboard();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders its child (the textarea) as the right-click surface', () => {
    renderInput();
    expect(screen.getByTestId('editable')).toBeInTheDocument();
    expect(screen.queryByTestId('ctx-paste')).not.toBeInTheDocument();
  });

  it('opens on right-click with Paste enabled and Cut/Copy disabled without a selection', async () => {
    await renderInput({ value: 'hello' });
    await openContextMenu();
    expect(screen.getByTestId('ctx-paste')).not.toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('ctx-cut')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('ctx-copy')).toHaveAttribute('aria-disabled', 'true');
    // There is text, so Select all is available.
    expect(screen.getByTestId('ctx-select-all')).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('enables Cut and Copy when the textarea has a selection', async () => {
    const { el } = await renderInput({ value: 'hello world' });
    act(() => {
      el.focus();
      el.setSelectionRange(0, 5);
    });
    await openContextMenu();
    expect(screen.getByTestId('ctx-cut')).not.toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByTestId('ctx-copy')).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('disables Select all when the input is empty', async () => {
    await renderInput({ value: '' });
    await openContextMenu();
    expect(screen.getByTestId('ctx-select-all')).toHaveAttribute('aria-disabled', 'true');
  });

  it('copies the selected text', async () => {
    const { el, writeText } = await renderInput({ value: 'hello world' });
    act(() => {
      el.focus();
      el.setSelectionRange(0, 5);
    });
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-copy'));
    });
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('cut delivers the shortened value to onChange and puts the text on the clipboard', async () => {
    const { onChange, el, writeText } = await renderInput({ value: 'hello world' });
    act(() => {
      el.focus();
      el.setSelectionRange(0, 6);
    });
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-cut'));
    });
    expect(writeText).toHaveBeenCalledWith('hello ');
    // Controlled update: "world" remains.
    expect(onChange).toHaveBeenCalledWith('world');
  });

  it('paste inserts clipboard text at the caret via onChange', async () => {
    const { onChange, el } = await renderInput({ value: 'hello', clipboardText: ' beautiful' });
    act(() => {
      el.focus();
      el.setSelectionRange(5, 5);
    });
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-paste'));
    });
    await act(async () => {});
    expect(onChange).toHaveBeenCalledWith('hello beautiful');
  });

  it('paste replaces the current selection', async () => {
    const { onChange, el } = await renderInput({ value: 'hello world', clipboardText: 'there' });
    act(() => {
      el.focus();
      el.setSelectionRange(0, 5);
    });
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-paste'));
    });
    await act(async () => {});
    expect(onChange).toHaveBeenCalledWith('there world');
  });

  it('paste without clipboard permission leaves the value untouched', async () => {
    const onChange = vi.fn();
    const ref = createRef<HTMLTextAreaElement>();
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn(), readText: vi.fn().mockRejectedValue(new Error('denied')) },
      configurable: true,
      writable: true,
    });
    render(
      <InputContextMenu textareaRef={ref} value="keep me" onChange={onChange}>
        <textarea ref={ref} data-testid="editable" defaultValue="keep me" />
      </InputContextMenu>,
    );
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-paste'));
    });
    await act(async () => {});
    expect(onChange).not.toHaveBeenCalled();
  });

  it('select all selects the whole input', async () => {
    const { el } = await renderInput({ value: 'selectable text' });
    await openContextMenu();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ctx-select-all'));
    });
    // jsdom does apply setSelectionRange synchronously.
    expect(el.selectionStart).toBe(0);
    expect(el.selectionEnd).toBe(el.value.length);
  });
});
